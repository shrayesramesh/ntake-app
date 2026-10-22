"""``build_world_view`` — a deterministic, plain-text "state of the world".

The ambient family state the LINK call reasons over, rendered to a compact text
block for the prompt: family members, non-archived work items (``done``
INCLUDED, ``archived`` EXCLUDED), and events in a past window (default 7 days
back, forward open-ended). Ids are inline (they matter for later whitelisted
targeting); times render in the **family timezone**, start + end.

Behaviour-faithful to the self-hosted reference
(``git show main:app/assistant/context/world.py``): same sections, ordering,
``- (none)`` placeholders, suffixes, event formatting, and 7-day window. Two
adaptations the AWS rebuild forces, both behaviour-preserving:

* **Reads come from the** :class:`core.repository.Repository` **seam**, not a
  SQLAlchemy ``Session`` — ``list_members`` + ``list_work_items`` (non-archived,
  done included) + ``list_events`` (all events; the window is applied here, in
  code, so deep-context can reuse the same unfiltered read — AWS_LLD §3.1).
* **Ids are ULID strings**, so the id token is ``[w:<id>]`` / ``[e:<id>]`` /
  ``[m:<id>]`` (type tag + colon + ULID, Option A) — the reference's type-tagged
  bracket shape with an unambiguous separator (the old ``[w1]`` glued a letter to
  a short int; a bare ULID would run together).

No LLM here — pure repository reads + formatting. The window + done-included +
archived-excluded knobs are parameters with defaults, tunable later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.repository import Repository
from core.schemas import Event

# --- row shapes (internal) -------------------------------------------------
# Thin rows the formatter consumes — kept so the rendering is a pure function of
# plain values, independently testable from the reads (mirrors the reference).


@dataclass(frozen=True)
class _MemberRow:
    id: str
    display_name: str
    role: str


@dataclass(frozen=True)
class _WorkItemRow:
    id: str
    title: str
    status: str


@dataclass(frozen=True)
class _EventRow:
    id: str
    title: str
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date: date | None


# --- selection (over the repository reads, deterministic) ------------------


def _members(repo: Repository, family_id: str) -> list[_MemberRow]:
    rows = [
        _MemberRow(id=m.id, display_name=m.display_name, role=m.role)
        for m in repo.list_members(family_id)
    ]
    rows.sort(key=lambda r: r.id)  # reference ordered by id (deterministic)
    return rows


def _work_items(repo: Repository, family_id: str) -> list[_WorkItemRow]:
    """Non-archived work items (``done`` included; archived dropped by the repo)."""
    rows = [
        _WorkItemRow(id=wi.id, title=wi.title, status=wi.status)
        for wi in repo.list_work_items(family_id)
    ]
    rows.sort(key=lambda r: r.id)
    return rows


def _events(
    repo: Repository, family_id: str, now: datetime, tz: str, window_days: int
) -> list[_EventRow]:
    """Events from ``now - window_days`` onward (forward open-ended).

    The window is applied here (``list_events`` returns all events) so a
    participated event outside the window is still reachable by deep-context,
    which reuses the same unfiltered read. Timed events compare on their UTC
    ``start_at``; all-day events compare ``start_date`` against the cutoff's date
    in the family tz.
    """
    cutoff_dt = now - timedelta(days=window_days)
    cutoff_date = cutoff_dt.astimezone(ZoneInfo(tz)).date()
    cutoff_utc = cutoff_dt.astimezone(UTC)
    rows: list[_EventRow] = []
    for ev in repo.list_events(family_id):
        if ev.all_day:
            if ev.start_date is not None and ev.start_date >= cutoff_date:
                rows.append(_to_row(ev))
        elif ev.start_at is not None and _as_utc(ev.start_at) >= cutoff_utc:
            rows.append(_to_row(ev))
    rows.sort(key=_event_sort_key)
    return rows


def _event_sort_key(ev: _EventRow) -> tuple[int, str, str]:
    """Order by start instant, then id — the reference's (start_at, start_date, id)."""
    if not ev.all_day and ev.start_at is not None:
        return (0, _as_utc(ev.start_at).isoformat(), ev.id)
    if ev.all_day and ev.start_date is not None:
        return (0, ev.start_date.isoformat(), ev.id)
    return (1, "", ev.id)


def _to_row(ev: Event) -> _EventRow:
    return _EventRow(
        id=ev.id,
        title=ev.title,
        all_day=ev.all_day,
        start_at=ev.start_at,
        end_at=ev.end_at,
        start_date=ev.start_date,
        end_date=ev.end_date,
    )


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


# --- formatting (rows -> text; pure) ---------------------------------------

_DATETIME_FMT = "%a %b %-d, %-I:%M %p"  # "Fri Sep 5, 3:00 PM"
_DATE_FMT = "%a %b %-d"  # "Fri Sep 5"


def _fmt_event(ev: _EventRow, tz: str) -> str:
    if ev.all_day:
        start = ev.start_date.strftime(_DATE_FMT) if ev.start_date else "?"
        end = ev.end_date.strftime(_DATE_FMT) if ev.end_date else start
        when = start if start == end else f"{start} – {end}"
        return f"- [e:{ev.id}] {ev.title} — {when} (all day)"
    zone = ZoneInfo(tz)
    start = _fmt_local(ev.start_at, zone) if ev.start_at else "?"
    end = _fmt_local(ev.end_at, zone) if ev.end_at else start
    when = start if start == end else f"{start} – {end}"
    return f"- [e:{ev.id}] {ev.title} — {when}"


def _fmt_local(dt: datetime, zone: ZoneInfo) -> str:
    """Format a stored (UTC) datetime in the family zone."""
    return _as_utc(dt).astimezone(zone).strftime(_DATETIME_FMT)


def _render(
    members: list[_MemberRow],
    items: list[_WorkItemRow],
    events: list[_EventRow],
    tz: str,
) -> str:
    lines: list[str] = ["FAMILY MEMBERS:"]
    lines += [f"- [m:{m.id}] {m.display_name} ({m.role})" for m in members] or [
        "- (none)"
    ]
    lines += ["", "OPEN WORK ITEMS:"]
    lines += [f"- [w:{wi.id}] {wi.title} ({wi.status})" for wi in items] or ["- (none)"]
    lines += ["", "EVENTS:"]
    lines += [_fmt_event(ev, tz) for ev in events] or ["- (none)"]
    return "\n".join(lines)


# --- public API ------------------------------------------------------------


def build_world_view(
    repo: Repository,
    family_id: str,
    now: datetime,
    tz: str,
    *,
    window_days: int = 7,
) -> str:
    """Render the family's ambient state as a plain-text block for the LINK prompt.

    Deterministic: members + non-archived work items (done included) + events in
    ``[now - window_days, ∞)``, ids inline (``[w:<id>]`` etc.), times in family tz.
    """
    return _render(
        _members(repo, family_id),
        _work_items(repo, family_id),
        _events(repo, family_id, now, tz, window_days),
        tz,
    )

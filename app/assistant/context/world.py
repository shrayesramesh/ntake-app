"""``build_world_view`` — a deterministic, plain-text "state of the world".

The ambient family state the assistant reasons over, rendered to a compact text
block for the prompt: family members, non-archived work items (``done``
INCLUDED, ``archived`` EXCLUDED), and events in a past window (default 7 days
back, forward open-ended). Ids are inline (they matter for later whitelisted
targeting); times render in the **family timezone**, start + end.

No LLM here — pure DB reads + formatting. Kept LLM-agnostic (both the fake and
local-LLM paths can use it), so it lives in ``app/assistant/`` rather than the
``local_llm`` package. The query helpers and the formatter are split so each is
independently testable (rows from seeded DB; text from rows).

The knobs the owner chose are **parameters with defaults**, tunable later:
``window_days=7``; done included; archived excluded; times in family tz with
date + time, start + end.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Member, WorkItem

# --- row shapes (internal; not exported) ----------------------------------
# Thin rows the queries return and the formatter consumes. Plain values, no ORM
# objects, so the formatter needs no session and stays trivially testable.


@dataclass(frozen=True)
class _MemberRow:
    id: int
    display_name: str
    role: str


@dataclass(frozen=True)
class _WorkItemRow:
    id: int
    title: str
    status: str


@dataclass(frozen=True)
class _EventRow:
    id: int
    title: str
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date: date | None


# --- queries (templated select() over the family, deterministic) ----------


def _query_members(session: Session, family_id: int) -> list[_MemberRow]:
    stmt = select(Member).where(Member.family_id == family_id).order_by(Member.id)
    return [
        _MemberRow(id=m.id, display_name=m.display_name, role=m.role)
        for m in session.scalars(stmt).all()
    ]


def _query_work_items(session: Session, family_id: int) -> list[_WorkItemRow]:
    """Non-archived work items (``done`` included, ``archived`` excluded)."""
    stmt = (
        select(WorkItem)
        .where(WorkItem.family_id == family_id, WorkItem.archived_at.is_(None))
        .order_by(WorkItem.id)
    )
    return [
        _WorkItemRow(id=wi.id, title=wi.title, status=wi.status)
        for wi in session.scalars(stmt).all()
    ]


def _query_events(
    session: Session, family_id: int, now: datetime, tz: str, window_days: int
) -> list[_EventRow]:
    """Events from ``now - window_days`` onward (forward open-ended).

    Timed events compare on their UTC ``start_at``; all-day events compare on
    ``start_date`` against the cutoff's date in the family tz (all-day dates are
    tz-naive calendar dates).
    """
    cutoff_dt = now - timedelta(days=window_days)
    cutoff_date = cutoff_dt.astimezone(ZoneInfo(tz)).date()
    # DB datetimes come back tz-naive (SQLite drops tzinfo) but represent UTC, so
    # compare against a naive-UTC cutoff.
    cutoff_naive_utc = cutoff_dt.astimezone(UTC).replace(tzinfo=None)
    stmt = (
        select(Event)
        .where(Event.family_id == family_id)
        .order_by(Event.start_at, Event.start_date, Event.id)
    )
    rows: list[_EventRow] = []
    for ev in session.scalars(stmt).all():
        if ev.all_day:
            if ev.start_date is not None and ev.start_date >= cutoff_date:
                rows.append(_to_event_row(ev))
        else:
            if ev.start_at is not None and ev.start_at >= cutoff_naive_utc:
                rows.append(_to_event_row(ev))
    return rows


def _to_event_row(ev: Event) -> _EventRow:
    return _EventRow(
        id=ev.id,
        title=ev.title,
        all_day=ev.all_day,
        start_at=ev.start_at,
        end_at=ev.end_at,
        start_date=ev.start_date,
        end_date=ev.end_date,
    )


# --- formatting (rows -> text; pure, no session) --------------------------

_DATETIME_FMT = "%a %b %-d, %-I:%M %p"  # "Fri Sep 5, 3:00 PM"
_DATE_FMT = "%a %b %-d"  # "Fri Sep 5"


def _fmt_event(ev: _EventRow, tz: str) -> str:
    if ev.all_day:
        start = ev.start_date.strftime(_DATE_FMT) if ev.start_date else "?"
        end = ev.end_date.strftime(_DATE_FMT) if ev.end_date else start
        when = f"{start}" if start == end else f"{start} – {end}"
        return f"- [e{ev.id}] {ev.title} — {when} (all day)"
    zone = ZoneInfo(tz)
    start = _fmt_utc_naive(ev.start_at, zone) if ev.start_at else "?"
    end = _fmt_utc_naive(ev.end_at, zone) if ev.end_at else start
    when = start if start == end else f"{start} – {end}"
    return f"- [e{ev.id}] {ev.title} — {when}"


def _fmt_utc_naive(dt: datetime, zone: ZoneInfo) -> str:
    """Format a stored (tz-naive, UTC) datetime in the family zone.

    DB datetimes come back naive but represent UTC; attach UTC, then convert.
    """
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return aware.astimezone(zone).strftime(_DATETIME_FMT)


def _render(
    members: list[_MemberRow],
    items: list[_WorkItemRow],
    events: list[_EventRow],
    tz: str,
) -> str:
    lines: list[str] = ["FAMILY MEMBERS:"]
    lines += [f"- [m{m.id}] {m.display_name} ({m.role})" for m in members] or [
        "- (none)"
    ]
    lines += ["", "OPEN WORK ITEMS:"]
    lines += [f"- [w{wi.id}] {wi.title} ({wi.status})" for wi in items] or ["- (none)"]
    lines += ["", "EVENTS:"]
    lines += [_fmt_event(ev, tz) for ev in events] or ["- (none)"]
    return "\n".join(lines)


# --- public API -----------------------------------------------------------


def build_world_view(
    session: Session,
    family_id: int,
    now: datetime,
    tz: str,
    *,
    window_days: int = 7,
) -> str:
    """Render the family's ambient state as a plain-text block for the prompt.

    Deterministic: members + non-archived work items (done included) + events in
    ``[now - window_days, ∞)``, with ids inline and times in the family tz.
    """
    members = _query_members(session, family_id)
    items = _query_work_items(session, family_id)
    events = _query_events(session, family_id, now, tz, window_days)
    return _render(members, items, events, tz)

"""Validate LINK ids and render narrow, detailed context for PROPOSE.

Behaviour-faithful to the reference (git show
main:app/assistant/context/deep.py). Adaptations the AWS rebuild forces, all
behaviour-preserving:

* Reads go through the :class:`core.repository.Repository` seam, not a SQLAlchemy
  ``Session``. The family whitelist loads use ``get_work_item`` / ``get_event`` /
  ``get_member`` (each already family-scoped); the assignee scan flattens
  ``list_work_items`` and the participant scan flattens ``list_events``.
* A work item's updates + checklist are **nested on the aggregate** (one
  ``get_work_item``), not separate queries. Updates render in
  ``(created_at, update_id)`` order; checklist in ``position`` order.
* Ids are ULID strings → ``[w:<id>]`` / ``[e:<id>]`` / ``[m:<id>]`` (Option A).

``resolve_ids`` is the id whitelist (what the resolver stores on the context);
``deep_context`` is the rendered records — both scoped to the family.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from core.repository import Repository
from core.schemas import Event, Member, WorkItem

_DATETIME_FMT = "%a %b %-d, %-I:%M %p"
_DATE_FMT = "%a %b %-d"


def resolve_ids(
    repo: Repository,
    member: Member,
    work_item_ids: list[str],
    event_ids: list[str],
    member_ids: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Whitelist untrusted linked ids to ``member``'s family (validate-don't-trust).

    Drops any id that doesn't exist in the capturing member's family, so ONLY
    validated ids reach ``FocusedContext`` (and become attachable targets). Input
    order preserved. Applies to work items, events, AND members.
    """
    fam = member.family_id
    valid_wi = {wi.id for wi in _load_items(repo, fam, work_item_ids)}
    valid_ev = {ev.id for ev in _load_events(repo, fam, event_ids)}
    valid_mem = {mm.id for mm in _load_members(repo, fam, member_ids)}
    return (
        _keep_in_order(work_item_ids, valid_wi),
        _keep_in_order(event_ids, valid_ev),
        _keep_in_order(member_ids, valid_mem),
    )


def _keep_in_order(ids: list[str], valid: set[str]) -> list[str]:
    """Keep ids present in ``valid``, first-seen order, **de-duplicated**.

    Dedup here (not just at render): a duplicate resolved id is meaningless and
    would otherwise ride on ``FocusedContext`` into the primary-id accessors and
    PROPOSE's enum-over-whitelist. (The reference left dups in and relied on the
    render to dedup — masking a latent bug; we fix it at the source.)
    """
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i in valid and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def deep_context(
    repo: Repository,
    member: Member,
    work_item_ids: list[str],
    event_ids: list[str],
    member_ids: list[str] | None = None,
) -> str:
    """Render the deep, narrow context for the PROPOSE call.

    Validates the linked ids to ``member``'s family and renders a member header +
    each relevant work item with its FULL update history + the relevant events.
    The footprint (assigned work items + participated events) of BOTH the
    capturing member AND any ``member_ids`` LINK resolved is folded in.
    """
    fam = member.family_id
    family = repo.get_family(fam)
    zone = ZoneInfo(family.timezone if family is not None else "UTC")

    linked_members = _load_members(repo, fam, member_ids or [])
    footprint = _dedup([member, *linked_members])

    items = _work_item_context(repo, fam, work_item_ids, footprint)
    events = _event_context(repo, fam, event_ids, footprint)

    return _render(member, items, events, linked_members, zone)


# --- context resolution ----------------------------------------------------


def _work_item_context(
    repo: Repository, fam: str, linked_ids: list[str], footprint: list[Member]
) -> list[WorkItem]:
    """Linked work items plus every footprint member's assigned work."""
    items = _load_items(repo, fam, linked_ids)
    for m in footprint:
        items += [wi for wi in repo.list_work_items(fam) if wi.assigned_to == m.id]
    return _dedup(items)


def _event_context(
    repo: Repository, fam: str, linked_ids: list[str], footprint: list[Member]
) -> list[Event]:
    """Linked events plus every footprint member's participated events."""
    events = _load_events(repo, fam, linked_ids)
    for m in footprint:
        events += _participated(repo, fam, m)
    return _dedup(events)


# --- loads (family-scoped = the whitelist) ---------------------------------


def _load_items(repo: Repository, fam: str, ids: list[str]) -> list[WorkItem]:
    out = [repo.get_work_item(fam, i) for i in ids]
    return [wi for wi in out if wi is not None]


def _load_events(repo: Repository, fam: str, ids: list[str]) -> list[Event]:
    out = [repo.get_event(fam, i) for i in ids]
    return [ev for ev in out if ev is not None]


def _load_members(repo: Repository, fam: str, ids: list[str]) -> list[Member]:
    """Members in this family whose ids are in ``ids``, preserving order."""
    loaded = {i: repo.get_member(fam, i) for i in ids}
    return [m for i in ids if (m := loaded[i]) is not None]


def _participated(repo: Repository, fam: str, member: Member) -> list[Event]:
    """Family events whose participant names match the member display name."""
    target = member.display_name.strip().casefold()
    return [
        ev
        for ev in repo.list_events(fam)
        if any(
            isinstance(n, str) and n.strip().casefold() == target
            for n in (ev.participants or [])
        )
    ]


def _dedup(rows: list) -> list:
    """De-duplicate DTOs by ``.id``, preserving first-seen order."""
    seen: set[str] = set()
    out: list = []
    for r in rows:
        if r.id not in seen:
            seen.add(r.id)
            out.append(r)
    return out


# --- render ----------------------------------------------------------------


def _render(
    member: Member,
    items: list[WorkItem],
    events: list[Event],
    linked_members: list[Member],
    zone: ZoneInfo,
) -> str:
    lines: list[str] = []
    others = [lm for lm in linked_members if lm.id != member.id]
    if others:
        who = ", ".join(f"[m:{lm.id}] {lm.display_name} ({lm.role})" for lm in others)
        lines.append(f"ALSO ABOUT: {who}")
        lines.append("")
    lines += _render_items(items, zone)
    lines += _render_events(events, zone)
    return "\n".join(lines)


def _render_items(items: list[WorkItem], zone: ZoneInfo) -> list[str]:
    lines = ["RELEVANT WORK ITEMS:"]
    if not items:
        return [*lines, "- (none)", ""]
    for wi in items:
        due = f", due {_fmt_dt(wi.due_at, zone)}" if wi.due_at else ""
        tags = f" [tags: {', '.join(wi.tags)}]" if wi.tags else ""
        lines.append(f"- [w:{wi.id}] {wi.title} ({wi.status}{due}){tags}")
        if wi.description:
            lines.append(f"    DESCRIPTION: {wi.description}")
        checklist = sorted(wi.checklist, key=lambda c: c.position)
        if checklist:
            lines.append("    CHECKLIST:")
            for c in checklist:
                mark = "x" if c.checked else " "
                lines.append(f"    · [{mark}] {c.text}")
        updates = sorted(wi.updates, key=lambda u: (u.created_at, u.update_id))
        if updates:
            lines.append("    UPDATES:")
            for u in updates:
                ts = _fmt_dt(u.created_at, zone)
                lines.append(f"    · [{u.source} · {ts}] {u.body}")
    return [*lines, ""]


def _render_events(events: list[Event], zone: ZoneInfo) -> list[str]:
    if not events:
        return ["RELEVANT EVENTS:", "- (none)"]
    return ["RELEVANT EVENTS:", *[_fmt_event(ev, zone) for ev in events]]


def _fmt_event(ev: Event, zone: ZoneInfo) -> str:
    tags = f" [tags: {', '.join(ev.tags)}]" if ev.tags else ""
    if ev.all_day:
        start = ev.start_date.strftime(_DATE_FMT) if ev.start_date else "?"
        return f"- [e:{ev.id}] {ev.title} — {start} (all day){tags}"
    start = _fmt_dt(ev.start_at, zone) if ev.start_at else "?"
    end = _fmt_dt(ev.end_at, zone) if ev.end_at else start
    when = start if start == end else f"{start} – {end}"
    return f"- [e:{ev.id}] {ev.title} — {when}{tags}"


def _fmt_dt(dt: datetime, zone: ZoneInfo) -> str:
    """Format a stored UTC timestamp in the family's local timezone."""
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return aware.astimezone(zone).strftime(_DATETIME_FMT)

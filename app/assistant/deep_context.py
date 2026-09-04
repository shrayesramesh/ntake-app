"""deep_context.py — turn the LINK call's ids into the PROPOSE call's deep context.

Named for its output (the ``deep_context`` string) and to avoid colliding with the
``CaptureResolver`` seam impl in ``fake/resolver.py`` — this module is the shared
deep-fetch *stage* between the two LLM calls, not a seam.

Stage between the two LLM calls (see spec/LLD-assistant-pipeline.md):

    LINK JSON {work_item_ids, event_ids}
        → parse_ids()        tolerant parse of untrusted model output
        → deep_context()     validate (whitelist to family) + union the member's
                             footprint + render full records → the deep_context
                             string handed to build_propose_prompt

Two deliberate properties:

* **Validate, don't trust.** The prompt asks the model not to invent ids, but we
  enforce it: only ids that exist AND belong to the capturing member's family
  survive; anything else is silently dropped (graceful-degrade).
* **Member footprint is always included.** Beyond what the note linked, the
  capturing member's own work is context — their **assigned work items** and the
  **events they participate in** (their id in the event's ``participants``) are
  unioned in (deduped) so PROPOSE can reason about the member's load.

App-coupled (takes a Session), like world.py; returns a plain string.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Member, WorkItem, WorkItemUpdate

_DATETIME_FMT = "%a %b %-d, %-I:%M %p"
_DATE_FMT = "%a %b %-d"


def parse_ids(link_json: dict) -> tuple[list[int], list[int]]:
    """Parse the LINK call's JSON into (work_item_ids, event_ids).

    Tolerant of untrusted model output: missing keys → empty; non-list values →
    empty; non-int entries (strings, floats, None) are dropped. ``bool`` is
    excluded even though it subclasses ``int``.
    """
    return _int_list(link_json.get("work_item_ids")), _int_list(
        link_json.get("event_ids")
    )


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, int) and not isinstance(x, bool)]


def deep_context(
    session: Session,
    member: Member,
    work_item_ids: list[int],
    event_ids: list[int],
) -> str:
    """Render the deep, narrow context for the PROPOSE call.

    Validates the linked ids to ``member``'s family, unions in the member's
    assigned work items, and renders a member header + each work item with its
    FULL update history + the linked events. Session in, string out.
    """
    fam_id = member.family_id

    # Work items: linked (validated to family) ∪ the member's assigned items, deduped.
    linked_items = _load_family_items(session, fam_id, work_item_ids)
    footprint_items = _load_assigned_items(session, fam_id, member.id)
    items = _dedup_by_id(linked_items + footprint_items)

    # Events: the linked ones (validated to family) ∪ events the member
    # participates in (participants list contains their member_id), deduped.
    linked_events = _load_family_events(session, fam_id, event_ids)
    participated = _load_participated_events(session, fam_id, member.id)
    events = _dedup_events(linked_events + participated)

    return _render(session, member, items, events)


# --- loads (all scoped to family = the whitelist) -------------------------


def _load_family_items(
    session: Session, family_id: int, ids: list[int]
) -> list[WorkItem]:
    if not ids:
        return []
    stmt = select(WorkItem).where(WorkItem.family_id == family_id, WorkItem.id.in_(ids))
    return list(session.scalars(stmt).all())


def _load_assigned_items(
    session: Session, family_id: int, member_id: int
) -> list[WorkItem]:
    stmt = (
        select(WorkItem)
        .where(WorkItem.family_id == family_id, WorkItem.assigned_to == member_id)
        .order_by(WorkItem.id)
    )
    return list(session.scalars(stmt).all())


def _load_family_events(
    session: Session, family_id: int, ids: list[int]
) -> list[Event]:
    if not ids:
        return []
    stmt = select(Event).where(Event.family_id == family_id, Event.id.in_(ids))
    return list(session.scalars(stmt).all())


def _load_participated_events(
    session: Session, family_id: int, member_id: int
) -> list[Event]:
    """Family events the member participates in (their id is in ``participants``).

    ``participants`` is a JSON list of ``{member_id?, name}``; at family scale we
    fetch the family's events and filter in Python (a JSON-containment SQL query
    is awkward/non-portable for a handful of rows).
    """
    stmt = select(Event).where(Event.family_id == family_id).order_by(Event.id)
    return [
        ev
        for ev in session.scalars(stmt).all()
        if any(
            isinstance(p, dict) and p.get("member_id") == member_id
            for p in (ev.participants or [])
        )
    ]


def _dedup_events(events: list[Event]) -> list[Event]:
    seen: set[int] = set()
    out: list[Event] = []
    for ev in events:
        if ev.id not in seen:
            seen.add(ev.id)
            out.append(ev)
    return out


def _dedup_by_id(items: list[WorkItem]) -> list[WorkItem]:
    seen: set[int] = set()
    out: list[WorkItem] = []
    for wi in items:
        if wi.id not in seen:
            seen.add(wi.id)
            out.append(wi)
    return out


# --- render (plain text for the prompt) -----------------------------------


def _item_updates(session: Session, work_item_id: int) -> list[WorkItemUpdate]:
    stmt = (
        select(WorkItemUpdate)
        .where(WorkItemUpdate.work_item_id == work_item_id)
        .order_by(WorkItemUpdate.created_at, WorkItemUpdate.id)
    )
    return list(session.scalars(stmt).all())


def _render(
    session: Session, member: Member, items: list[WorkItem], events: list[Event]
) -> str:
    lines = [f"NOTE FROM: [m{member.id}] {member.display_name} ({member.role})", ""]

    lines.append("RELEVANT WORK ITEMS:")
    if items:
        for wi in items:
            due = f", due {wi.due_at.isoformat()}" if wi.due_at else ""
            lines.append(f"- [w{wi.id}] {wi.title} ({wi.status}{due})")
            updates = _item_updates(session, wi.id)
            for u in updates:
                lines.append(f"    · [{u.source}] {u.body}")
            if not updates:
                lines.append("    · (no updates yet)")
    else:
        lines.append("- (none)")

    lines += ["", "RELEVANT EVENTS:"]
    lines += [_fmt_event(ev) for ev in events] or ["- (none)"]
    return "\n".join(lines)


def _fmt_event(ev: Event) -> str:
    if ev.all_day:
        start = ev.start_date.strftime(_DATE_FMT) if ev.start_date else "?"
        return f"- [e{ev.id}] {ev.title} — {start} (all day)"
    start = _fmt_dt(ev.start_at) if ev.start_at else "?"
    end = _fmt_dt(ev.end_at) if ev.end_at else start
    when = start if start == end else f"{start} – {end}"
    return f"- [e{ev.id}] {ev.title} — {when}"


def _fmt_dt(dt: datetime) -> str:
    # DB datetimes come back tz-naive (UTC). Show UTC (deep context is for the
    # model to reason over; grounding to family tz happens in param output).
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return aware.strftime(_DATETIME_FMT)

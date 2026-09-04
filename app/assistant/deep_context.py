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

App-coupled (takes a Session), like world_view.py; returns a plain string.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChecklistItem, Event, Family, Member, WorkItem, WorkItemUpdate

_DATETIME_FMT = "%a %b %-d, %-I:%M %p"
_DATE_FMT = "%a %b %-d"


def parse_ids(link_json: dict) -> tuple[list[int], list[int], list[int]]:
    """Parse the LINK call's JSON into (work_item_ids, event_ids, member_ids).

    Tolerant of untrusted model output: missing keys → empty; non-list values →
    empty. Each entry is coerced to the entity's **integer** id (see
    ``_coerce_ids``): an int, a numeric string, or the matching-prefix token
    (``w`` for work items, ``e`` for events, ``m`` for members,
    case-insensitive); anything else is dropped.
    """
    return (
        _coerce_ids(link_json.get("work_item_ids"), "w"),
        _coerce_ids(link_json.get("event_ids"), "e"),
        _coerce_ids(link_json.get("member_ids"), "m"),
    )


def _coerce_ids(value: object, prefix: str) -> list[int]:
    """Coerce a list of untrusted id tokens to ints for one entity kind.

    Accepts: a bare ``int`` (not ``bool``); a numeric string (``"5"``); or the
    kind's token ``<prefix><digits>`` (``"e8"``, case-insensitive). Drops
    everything else (wrong prefix, non-numeric, floats, None).
    """
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for x in value:
        coerced = _coerce_one(x, prefix)
        if coerced is not None:
            out.append(coerced)
    return out


def _coerce_one(x: object, prefix: str) -> int | None:
    if isinstance(x, bool):  # bool subclasses int — never an id
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        token = x.strip()
        # Strip one leading matching-prefix letter (w3/e8), case-insensitive.
        if token[:1].lower() == prefix:
            token = token[1:]
        return int(token) if token.isdigit() else None
    return None


def resolve_ids(
    session: Session,
    member: Member,
    work_item_ids: list[int],
    event_ids: list[int],
    member_ids: list[int],
) -> tuple[list[int], list[int], list[int]]:
    """Whitelist untrusted linked ids to ``member``'s family (validate-don't-trust).

    The LINK call's ids are well-formed but untrusted (a model may hallucinate or
    name another family's entity). This drops any id that doesn't exist in the
    capturing member's family, so ONLY validated ids reach ``FocusedContext``
    (and thus become attachable targets). Input order is preserved. Applies to
    work items, events, AND members (the note may name a person to attribute).

    The counterpart to ``deep_context`` (same family whitelist): the resolver
    calls this for the ids it stores on the context, and ``deep_context`` for the
    rendered records — both scoped to the family.
    """
    fam_id = member.family_id
    valid_wi = {wi.id for wi in _load_family_items(session, fam_id, work_item_ids)}
    valid_ev = {ev.id for ev in _load_family_events(session, fam_id, event_ids)}
    valid_mem = {mm.id for mm in _load_family_members(session, fam_id, member_ids)}
    return (
        [i for i in work_item_ids if i in valid_wi],
        [i for i in event_ids if i in valid_ev],
        [i for i in member_ids if i in valid_mem],
    )


def deep_context(
    session: Session,
    member: Member,
    work_item_ids: list[int],
    event_ids: list[int],
    member_ids: list[int] | None = None,
) -> str:
    """Render the deep, narrow context for the PROPOSE call.

    Validates the linked ids to ``member``'s family and renders a member header +
    each relevant work item with its FULL update history + the relevant events.
    The footprint (assigned work items + participated events) of BOTH the
    capturing member AND any ``member_ids`` the LINK step resolved (people the
    note names) is folded in — so the LLM can judge each named person's workload
    when deciding what to do (e.g. "Alex day off Monday" → see what Alex already
    has). Session in, string out.
    """
    fam_id = member.family_id
    family = session.get(Family, fam_id)
    zone = ZoneInfo(family.timezone if family is not None else "UTC")

    # Linked members (people the note names): validated to family. Their full
    # footprint is folded in below so the LLM can judge each person's workload.
    linked_members = _load_family_members(session, fam_id, member_ids or [])

    # The members whose footprint we render: the capturing member + any the note
    # linked (deduped, capturing member first).
    footprint_members = _dedup_members([member, *linked_members])

    items = _resolve_work_item_context(
        session, fam_id, work_item_ids, footprint_members
    )
    events = _resolve_event_context(session, fam_id, event_ids, footprint_members)

    return _render(session, member, items, events, linked_members, zone)


# --- domain context: resolve work items and events independently -----------


def _resolve_work_item_context(
    session: Session,
    family_id: int,
    linked_ids: list[int],
    footprint_members: list[Member],
) -> list[WorkItem]:
    """Linked work items plus every footprint member's assigned work."""
    linked_items = _load_family_items(session, family_id, linked_ids)
    assigned_items: list[WorkItem] = []
    for member in footprint_members:
        assigned_items += _load_assigned_items(session, family_id, member.id)
    return _dedup_by_id(linked_items + assigned_items)


def _resolve_event_context(
    session: Session,
    family_id: int,
    linked_ids: list[int],
    footprint_members: list[Member],
) -> list[Event]:
    """Linked events plus every footprint member's participated events."""
    linked_events = _load_family_events(session, family_id, linked_ids)
    participated_events: list[Event] = []
    for member in footprint_members:
        participated_events += _load_participated_events(session, family_id, member.id)
    return _dedup_events(linked_events + participated_events)


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


def _load_family_members(
    session: Session, family_id: int, ids: list[int]
) -> list[Member]:
    """Members in this family whose ids are in ``ids`` (the LINK-named people),
    preserving the given order. The member whitelist (validate-don't-trust)."""
    if not ids:
        return []
    stmt = select(Member).where(Member.family_id == family_id, Member.id.in_(ids))
    by_id = {mm.id: mm for mm in session.scalars(stmt).all()}
    return [by_id[i] for i in ids if i in by_id]


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


def _dedup_members(members: list[Member]) -> list[Member]:
    seen: set[int] = set()
    out: list[Member] = []
    for mm in members:
        if mm.id not in seen:
            seen.add(mm.id)
            out.append(mm)
    return out


# --- render (plain text for the prompt) -----------------------------------


def _item_updates(session: Session, work_item_id: int) -> list[WorkItemUpdate]:
    stmt = (
        select(WorkItemUpdate)
        .where(WorkItemUpdate.work_item_id == work_item_id)
        .order_by(WorkItemUpdate.created_at, WorkItemUpdate.id)
    )
    return list(session.scalars(stmt).all())


def _item_checklist(session: Session, work_item_id: int) -> list[ChecklistItem]:
    stmt = (
        select(ChecklistItem)
        .where(ChecklistItem.work_item_id == work_item_id)
        .order_by(ChecklistItem.position, ChecklistItem.id)
    )
    return list(session.scalars(stmt).all())


def _render(
    session: Session,
    member: Member,
    items: list[WorkItem],
    events: list[Event],
    linked_members: list[Member],
    zone: ZoneInfo,
) -> str:
    lines = [f"NOTE FROM: [m{member.id}] {member.display_name} ({member.role})"]

    # People the note is about (beyond the author) — their workload/events are
    # folded into the sections below so the model can judge what to do for them.
    others = [lm for lm in linked_members if lm.id != member.id]
    if others:
        who = ", ".join(f"[m{lm.id}] {lm.display_name} ({lm.role})" for lm in others)
        lines.append(f"ALSO ABOUT: {who}")
    lines.append("")

    lines += _render_work_item_context(session, items, zone)
    lines += _render_event_context(events, zone)
    return "\n".join(lines)


def _render_work_item_context(
    session: Session, items: list[WorkItem], zone: ZoneInfo
) -> list[str]:
    """Render all work-item state and update history before event context."""
    lines = ["RELEVANT WORK ITEMS:"]
    if not items:
        return [*lines, "- (none)", ""]
    for wi in items:
        due = f", due {_fmt_dt(wi.due_at, zone)}" if wi.due_at else ""
        lines.append(f"- [w{wi.id}] {wi.title} ({wi.status}{due})")

        checklist = _item_checklist(session, wi.id)
        if checklist:
            lines.append("    CHECKLIST:")
            for item in checklist:
                mark = "x" if item.checked else " "
                lines.append(f"    · [{mark}] {item.text}")

        updates = _item_updates(session, wi.id)
        if updates:
            lines.append("    UPDATES:")
            for update in updates:
                timestamp = _fmt_dt(update.created_at, zone)
                lines.append(f"    · [{update.source} · {timestamp}] {update.body}")
    return [*lines, ""]


def _render_event_context(events: list[Event], zone: ZoneInfo) -> list[str]:
    """Render all event state after the work-item context section."""
    if not events:
        return ["RELEVANT EVENTS:", "- (none)"]
    return ["RELEVANT EVENTS:", *[_fmt_event(event, zone) for event in events]]


def _fmt_event(ev: Event, zone: ZoneInfo) -> str:
    if ev.all_day:
        start = ev.start_date.strftime(_DATE_FMT) if ev.start_date else "?"
        return f"- [e{ev.id}] {ev.title} — {start} (all day)"
    start = _fmt_dt(ev.start_at, zone) if ev.start_at else "?"
    end = _fmt_dt(ev.end_at, zone) if ev.end_at else start
    when = start if start == end else f"{start} – {end}"
    return f"- [e{ev.id}] {ev.title} — {when}"


def _fmt_dt(dt: datetime, zone: ZoneInfo) -> str:
    """Format a stored UTC timestamp in the family's local timezone."""
    # SQLite returns stored UTC timestamps as tz-naive values.
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return aware.astimezone(zone).strftime(_DATETIME_FMT)

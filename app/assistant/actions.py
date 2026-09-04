"""ntake action plugin — registers the app's actions into the routing engine.

The domain-agnostic machinery (registry, validate, dispatch, describe, the
ActionSpec/ProposedAction shapes, ActionError) lives in ``app.routing``. This
module is the **plugin**: the ntake-specific handlers that actually mutate work
items and events, their ``describe`` text, and the registration that wires them
into an engine :class:`ActionRegistry`.

Each handler receives the **opaque context** the app injects at dispatch time —
here an :class:`NtakeActionContext` carrying ``(session, member, target_id,
target_type)`` — and does the ORM mutation plus, when it targets a work item, the
``source=assistant`` update append (WORKITEM-3; conditional per task 12). The
engine never sees SQLAlchemy.

``apply_action`` / ``describe_action`` / ``ACTIONS`` / ``ActionError`` are kept as
the stable public surface the endpoints and tests use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    ChecklistItem,
    Event,
    Member,
    TargetType,
    WorkItem,
    WorkItemUpdate,
)

# Engine (domain-agnostic) — the plugin builds on these.
from app.routing.engine import (
    ActionContext,
    ActionError,
    ActionRegistry,
    ActionSpec,
    DataType,
    Param,
    require_params,
)


@dataclass
class NtakeActionContext(ActionContext):
    """The opaque context ntake injects into the engine at dispatch time.

    The engine never inspects this; the handlers below unpack it. ``target_type``
    ("work_item" | "event" | None) generalizes the target (task 12): the
    conditional log rule lives in the handlers (only a work-item target appends a
    source=assistant update).
    """

    session: Session
    member: Member
    target_id: int | None
    target_type: str | None


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ActionError(f"invalid datetime: {value!r}") from e


def _load_item(session: Session, target_id: int | None) -> WorkItem:
    wi = session.get(WorkItem, target_id) if target_id is not None else None
    if wi is None:
        raise ActionError(f"work item not found: {target_id}")
    return wi


def _load_event(session: Session, target_id: int | None) -> Event:
    ev = session.get(Event, target_id) if target_id is not None else None
    if ev is None:
        raise ActionError(f"event not found: {target_id}")
    return ev


def _append_assistant_update(
    session: Session, member: Member, work_item_id: int, body: str
) -> WorkItemUpdate:
    """Append the source=assistant narration; author is the confirming member."""
    upd = WorkItemUpdate(
        work_item_id=work_item_id,
        author_id=member.id,
        source="assistant",
        body=body,
        created_at=datetime.now(UTC),
    )
    session.add(upd)
    session.flush()  # assign id (create_event links to it)
    return upd


# --- handlers: (context, params) -> summary -------------------------------


def _apply_set_due_date(ctx: NtakeActionContext, params: dict) -> str:
    require_params(params, ["due_at"])
    due = _parse_dt(params["due_at"])
    wi = _load_item(ctx.session, ctx.target_id)
    wi.due_at = due
    wi.updated_at = datetime.now(UTC)
    _append_assistant_update(
        ctx.session, ctx.member, wi.id, f"Set due date to {due.isoformat()}"
    )
    return f"Set due date to {due.isoformat()}"


def _apply_complete(ctx: NtakeActionContext, params: dict) -> str:
    wi = _load_item(ctx.session, ctx.target_id)
    now = datetime.now(UTC)
    wi.status = "done"
    wi.completed_at = now
    wi.updated_at = now
    _append_assistant_update(ctx.session, ctx.member, wi.id, "Marked done")
    return "Marked done"


def _set_status(ctx: NtakeActionContext, status: str, note: str) -> str:
    """Shared status-transition handler: set status, log, return the note."""
    wi = _load_item(ctx.session, ctx.target_id)
    wi.status = status
    wi.updated_at = datetime.now(UTC)
    _append_assistant_update(ctx.session, ctx.member, wi.id, note)
    return note


def _apply_start(ctx: NtakeActionContext, params: dict) -> str:
    return _set_status(ctx, "doing", "Started work")


def _apply_move_to_on_deck(ctx: NtakeActionContext, params: dict) -> str:
    return _set_status(ctx, "on_deck", "Moved to On deck")


def _apply_move_to_todo(ctx: NtakeActionContext, params: dict) -> str:
    return _set_status(ctx, "todo", "Moved to Todo")


def _apply_reopen(ctx: NtakeActionContext, params: dict) -> str:
    """Reopen a completed item: back to todo and clear completed_at."""
    wi = _load_item(ctx.session, ctx.target_id)
    wi.status = "todo"
    wi.completed_at = None
    wi.updated_at = datetime.now(UTC)
    _append_assistant_update(ctx.session, ctx.member, wi.id, "Reopened")
    return "Reopened"


def _apply_assign(ctx: NtakeActionContext, params: dict) -> str:
    """Assign the work item to a family member.

    ``member_id`` is a context id the model chose; whitelist-validate it belongs
    to the confirming member's family (else ActionError — the first instance of
    the validate-a-model-chosen-id pattern).
    """
    require_params(params, ["member_id"])
    wi = _load_item(ctx.session, ctx.target_id)
    member_id = params["member_id"]
    assignee = ctx.session.get(Member, member_id)
    if assignee is None or assignee.family_id != ctx.member.family_id:
        raise ActionError(f"member not in family: {member_id}")
    wi.assigned_to = assignee.id
    wi.updated_at = datetime.now(UTC)
    note = f"Assigned to {assignee.display_name}"
    _append_assistant_update(ctx.session, ctx.member, wi.id, note)
    return note


def _apply_reschedule_event(ctx: NtakeActionContext, params: dict) -> str:
    """Move an existing event to new timing (modify-existing; event-only).

    Updates ONLY the timing fields, keyed by which timing pair was supplied
    (timed ``start_at``/``end_at`` OR all-day ``start_date``/``end_date``).
    Event-only: appends NO work-item update.
    """
    ev = _load_event(ctx.session, ctx.target_id)
    if params.get("start_at"):
        ev.all_day = False
        ev.start_at = _parse_dt(params["start_at"])
        ev.end_at = _parse_dt(params["end_at"]) if params.get("end_at") else ev.start_at
        ev.start_date = ev.end_date = None
    elif params.get("start_date"):
        ev.all_day = True
        ev.start_date = date.fromisoformat(params["start_date"])
        ev.end_date = (
            date.fromisoformat(params["end_date"])
            if params.get("end_date")
            else ev.start_date
        )
        ev.start_at = ev.end_at = None
    else:
        raise ActionError("reschedule_event requires a timed or all-day timing pair")
    ev.updated_at = datetime.now(UTC)
    return f"Rescheduled event “{ev.title}”"


def _apply_archive_work_item(ctx: NtakeActionContext, params: dict) -> str:
    """Archive a work item. Invariant (GROOM-4): only a ``done`` item may be
    archived — else ActionError."""
    wi = _load_item(ctx.session, ctx.target_id)
    if wi.status != "done":
        raise ActionError("only a done work item may be archived")
    now = datetime.now(UTC)
    wi.archived_at = now
    wi.updated_at = now
    _append_assistant_update(ctx.session, ctx.member, wi.id, "Archived")
    return "Archived"


def _apply_add_checklist_items(ctx: NtakeActionContext, params: dict) -> str:
    """Insert checklist items (grocery-list style) onto the target work item.

    v1 add-only: takes ``items: [str]`` and appends rows after the current max
    position. (check/uncheck/remove — which need by-name/by-id addressing — are
    deferred.)
    """
    require_params(params, ["items"])
    items = params["items"]
    if not isinstance(items, list) or not items:
        raise ActionError("items must be a non-empty list of strings")
    wi = _load_item(ctx.session, ctx.target_id)
    start_pos = (
        ctx.session.query(func.max(ChecklistItem.position))
        .filter(ChecklistItem.work_item_id == wi.id)
        .scalar()
    )
    pos = (start_pos or 0) + 1
    for text in items:
        ctx.session.add(ChecklistItem(work_item_id=wi.id, text=str(text), position=pos))
        pos += 1
    note = f"Added {len(items)} checklist item(s)"
    _append_assistant_update(ctx.session, ctx.member, wi.id, note)
    return note


def _apply_create_event(ctx: NtakeActionContext, params: dict) -> str:
    """Create an event — standalone OR driven by a work item (task 12).

    * **From a work item** (``target_type == "work_item"`` and a ``target_id``):
      append the driving ``source=assistant`` update, then link the event back to
      it via ``source_update_id`` (EVENT-7). This is the labor-log path.
    * **Standalone** (no work-item target): just insert the event. Events aren't
      part of the labor log, so NO work_item_update is appended (WORKITEM-3).
    """
    require_params(params, ["title"])
    now = datetime.now(UTC)

    source_update_id = None
    family_id = ctx.member.family_id
    if ctx.target_type == "work_item" and ctx.target_id is not None:
        wi = _load_item(ctx.session, ctx.target_id)
        family_id = wi.family_id
        upd = _append_assistant_update(
            ctx.session, ctx.member, wi.id, f"Created calendar event: {params['title']}"
        )
        source_update_id = upd.id

    all_day = bool(params.get("start_date"))
    ev = Event(
        family_id=family_id,
        title=params["title"],
        description=params.get("description"),
        location=params.get("location"),
        all_day=all_day,
        start_at=_parse_dt(params["start_at"]) if params.get("start_at") else None,
        end_at=_parse_dt(params["end_at"]) if params.get("end_at") else None,
        participants=params.get("participants") or [],
        source_update_id=source_update_id,
        created_at=now,
        updated_at=now,
    )
    ctx.session.add(ev)
    return f"Created event: {params['title']}"


def _apply_create_work_item(ctx: NtakeActionContext, params: dict) -> str:
    require_params(params, ["title"])
    now = datetime.now(UTC)
    wi = WorkItem(
        family_id=ctx.member.family_id,
        title=params["title"],
        description=params.get("description"),
        tags=params.get("tags", []),
        assigned_to=params.get("assigned_to"),
        created_at=now,
        updated_at=now,
    )
    ctx.session.add(wi)
    ctx.session.flush()
    _append_assistant_update(
        ctx.session, ctx.member, wi.id, f"Created work item: {params['title']}"
    )
    return f"Created work item: {params['title']}"


def _apply_no_action(ctx: NtakeActionContext, params: dict) -> str:
    return "No action"


def _apply_deconflict_events(ctx: NtakeActionContext, params: dict) -> str:
    """Move the target event to the next day to resolve an overlap (task 10).

    A deliberate PLACEHOLDER proving calendar context flows in → action out →
    apply — NOT smart scheduling. Event-only: it mutates just the event and
    appends NO work-item update (events aren't part of the labor log). Shifts the
    timing pair (timed start_at/end_at, or all-day start_date/end_date) by +1 day.
    """
    ev = _load_event(ctx.session, ctx.target_id)
    day = timedelta(days=1)
    if ev.all_day:
        if ev.start_date is not None:
            ev.start_date = ev.start_date + day
        if ev.end_date is not None:
            ev.end_date = ev.end_date + day
    else:
        if ev.start_at is not None:
            ev.start_at = ev.start_at + day
        if ev.end_at is not None:
            ev.end_at = ev.end_at + day
    ev.updated_at = datetime.now(UTC)
    return f"Moved event “{ev.title}” to the next day"


# --- describe fns: params -> deterministic action_summary -----------------
# Pure functions of params (ground truth for the card). They run on UNCONFIRMED
# proposals, so they must tolerate missing/partial params and never raise.


def _describe_set_due_date(params: dict) -> str:
    due = params.get("due_at")
    return f"Set due date to {due}" if due else "Set a due date"


def _describe_complete(params: dict) -> str:
    return "Mark the work item done"


def _describe_start(params: dict) -> str:
    return "Start work on the item (move to Doing)"


def _describe_move_to_on_deck(params: dict) -> str:
    return "Move the item to On deck"


def _describe_move_to_todo(params: dict) -> str:
    return "Move the item to Todo"


def _describe_reopen(params: dict) -> str:
    return "Reopen the item (back to Todo)"


def _describe_assign(params: dict) -> str:
    mid = params.get("member_id")
    return f"Assign the item to member {mid}" if mid else "Assign the item"


def _describe_reschedule_event(params: dict) -> str:
    when = params.get("start_at") or params.get("start_date")
    return f"Reschedule the event to {when}" if when else "Reschedule the event"


def _describe_archive(params: dict) -> str:
    return "Archive the (done) work item"


def _describe_add_checklist_items(params: dict) -> str:
    items = params.get("items")
    if isinstance(items, list) and items:
        return f"Add checklist items: {', '.join(str(i) for i in items)}"
    return "Add checklist items"


def _describe_create_event(params: dict) -> str:
    title = params.get("title")
    when = params.get("start_at") or params.get("start_date")
    if title and when:
        return f"Create event “{title}” at {when}"
    if title:
        return f"Create event “{title}”"
    return "Create a calendar event"


def _describe_create_work_item(params: dict) -> str:
    title = params.get("title")
    return f"Create work item “{title}”" if title else "Create a work item"


def _describe_no_action(params: dict) -> str:
    return "No action"


def _describe_deconflict(params: dict) -> str:
    return "Move the event to the next day (deconflict)"


# The ntake action set (spec/ASSISTANT_ACTIONS.md, v1). A plain dict of engine
# The ntake action set (spec/ASSISTANT_ACTIONS.md, v1). A name→spec dict kept
# public as ``ACTIONS`` for callers/tests; the engine ActionRegistry is built
# from its values (the flat spec list is the config — no imperative registration).
# Each spec's ``name`` is the identifier the model emits and the registry keys on;
# the dict key mirrors it for lookup ergonomics.
ACTIONS: dict[str, ActionSpec[NtakeActionContext]] = {
    "set_due_date": ActionSpec(
        name="set_due_date",
        description="Set a work item's due date.",
        params=[Param("due_at", DataType.DATETIME, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_set_due_date,
        describe=_describe_set_due_date,
    ),
    "complete_work_item": ActionSpec(
        name="complete_work_item",
        description="Mark a work item done.",
        target_type=TargetType.WORK_ITEM,
        apply=_apply_complete,
        describe=_describe_complete,
    ),
    "start_work_item": ActionSpec(
        name="start_work_item",
        description="Start work on an item (move it to Doing).",
        target_type=TargetType.WORK_ITEM,
        apply=_apply_start,
        describe=_describe_start,
    ),
    "move_to_on_deck": ActionSpec(
        name="move_to_on_deck",
        description="Move a work item to On deck (queued up next).",
        target_type=TargetType.WORK_ITEM,
        apply=_apply_move_to_on_deck,
        describe=_describe_move_to_on_deck,
    ),
    "move_to_todo": ActionSpec(
        name="move_to_todo",
        description="Move a work item back to Todo.",
        target_type=TargetType.WORK_ITEM,
        apply=_apply_move_to_todo,
        describe=_describe_move_to_todo,
    ),
    "reopen_work_item": ActionSpec(
        name="reopen_work_item",
        description="Reopen a completed item (back to Todo; clears completion).",
        target_type=TargetType.WORK_ITEM,
        apply=_apply_reopen,
        describe=_describe_reopen,
    ),
    "assign_work_item": ActionSpec(
        name="assign_work_item",
        description="Assign a work item to a family member.",
        params=[Param("member_id", DataType.INTEGER, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_assign,
        describe=_describe_assign,
    ),
    "archive_work_item": ActionSpec(
        name="archive_work_item",
        description="Archive a work item (only a done item may be archived).",
        target_type=TargetType.WORK_ITEM,
        apply=_apply_archive_work_item,
        describe=_describe_archive,
    ),
    "add_checklist_items": ActionSpec(
        name="add_checklist_items",
        description="Add checklist items (e.g. a grocery list) to a work item.",
        params=[Param("items", DataType.ARRAY_STRING, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_add_checklist_items,
        describe=_describe_add_checklist_items,
    ),
    "create_event": ActionSpec(
        name="create_event",
        description="Create a calendar event (timed OR all-day).",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("description", DataType.STRING),
            Param("location", DataType.STRING),
            Param("start_at", DataType.DATETIME),
            Param("end_at", DataType.DATETIME),
            Param("start_date", DataType.DATE),
            Param("end_date", DataType.DATE),
            Param("participants", DataType.OBJECT),
        ],
        exclusive_params=[["start_at", "end_at"], ["start_date", "end_date"]],
        # A creator: targets nothing by default. (Confirm may still attach a
        # work_item target for a create-from-item, set on the proposal/payload —
        # not a spec default.)
        target_type=None,
        apply=_apply_create_event,
        describe=_describe_create_event,
    ),
    "reschedule_event": ActionSpec(
        name="reschedule_event",
        description="Move an existing event to new timing (timed OR all-day).",
        params=[
            Param("start_at", DataType.DATETIME),
            Param("end_at", DataType.DATETIME),
            Param("start_date", DataType.DATE),
            Param("end_date", DataType.DATE),
        ],
        exclusive_params=[["start_at", "end_at"], ["start_date", "end_date"]],
        # Targets an existing event; event-only so it appends NO work-item update.
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_reschedule_event,
        describe=_describe_reschedule_event,
    ),
    "create_work_item": ActionSpec(
        name="create_work_item",
        description="Create a new work item (a task/todo).",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("description", DataType.STRING),
            Param("tags", DataType.ARRAY_STRING),
        ],
        target_type=None,
        apply=_apply_create_work_item,
        describe=_describe_create_work_item,
    ),
    "no_action": ActionSpec(
        name="no_action",
        description="Nothing to suggest.",
        target_type=None,
        logs=False,
        apply=_apply_no_action,
        describe=_describe_no_action,
    ),
    "deconflict_events": ActionSpec(
        name="deconflict_events",
        description="Move an event to the next day to resolve a same-time conflict.",
        # Targets an existing event; event-only so it appends NO work-item update.
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_deconflict_events,
        describe=_describe_deconflict,
    ),
}

# The engine registry the app dispatches through — built from the flat spec list.
REGISTRY: ActionRegistry[NtakeActionContext] = ActionRegistry(list(ACTIONS.values()))


def apply_action(
    session: Session,
    member: Member,
    name: str,
    target_id: int | None,
    params: dict,
    target_type: str | None = None,
) -> str:
    """Validate + apply a confirmed action via the engine. Returns a summary.

    Builds the ntake opaque context and calls ``REGISTRY.dispatch``. For
    backwards compatibility, a present ``target_id`` with no explicit
    ``target_type`` is treated as a work-item target, so existing work-item
    confirms keep logging + linking.

    Does not commit — the caller commits so the write publishes once via the seam.
    Raises ActionError for unknown names / missing params / bad targets.
    """
    if target_type is None and target_id is not None:
        target_type = "work_item"
    context = NtakeActionContext(
        session=session,
        member=member,
        target_id=target_id,
        target_type=target_type,
    )
    summary = REGISTRY.dispatch(name, params, context)
    session.flush()  # autoflush is off; make all pending rows visible pre-commit
    return summary

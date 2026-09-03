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
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Event, Member, WorkItem, WorkItemUpdate

# Engine (domain-agnostic) — the plugin builds on these.
from app.routing import (
    ActionContext,
    ActionError,
    ActionRegistry,
    ActionSpec,
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
        params=[Param("due_at", "datetime", required=True)],
        apply=_apply_set_due_date,
        describe=_describe_set_due_date,
    ),
    "complete_work_item": ActionSpec(
        name="complete_work_item",
        description="Mark a work item done.",
        apply=_apply_complete,
        describe=_describe_complete,
    ),
    "create_event": ActionSpec(
        name="create_event",
        description="Create a calendar event (timed OR all-day).",
        params=[
            Param("title", "string", required=True),
            Param("description", "string"),
            Param("location", "string"),
            Param("start_at", "datetime"),
            Param("end_at", "datetime"),
            Param("start_date", "date"),
            Param("end_date", "date"),
        ],
        exclusive_params=[["start_at", "end_at"], ["start_date", "end_date"]],
        apply=_apply_create_event,
        describe=_describe_create_event,
    ),
    "create_work_item": ActionSpec(
        name="create_work_item",
        description="Create a new work item (a task/todo).",
        params=[
            Param("title", "string", required=True),
            Param("description", "string"),
            Param("tags", "array<string>"),
        ],
        needs_target=False,
        apply=_apply_create_work_item,
        describe=_describe_create_work_item,
    ),
    "no_action": ActionSpec(
        name="no_action",
        description="Nothing to suggest.",
        needs_target=False,
        logs=False,
        apply=_apply_no_action,
        describe=_describe_no_action,
    ),
    "deconflict_events": ActionSpec(
        name="deconflict_events",
        description="Move an event to the next day to resolve a same-time conflict.",
        # Targets an existing event; event-only so it appends NO work-item update.
        needs_target=True,
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

"""Action registry + apply-handlers (Phase 4, task 2).

The registry ``ACTIONS`` is a plain ``dict[str, ActionSpec]`` — the confirmable
capabilities the assistant may propose (see spec/ASSISTANT_ACTIONS.md, v1 set).
``apply_action`` is called ONLY on human Confirm (never auto): it validates the
params lightly, runs the handler's mutation, and — except ``no_action`` — appends
a ``source=assistant`` work_item_updates row authored by the confirming member
(the universal on-confirm rule, WORKITEM-3). It does NOT commit; the caller
commits so the change publishes once via the 1d seam.

``work_item_id`` (the capture target) is passed by the server, never taken from
model params — the model doesn't guess row IDs. It is ``None`` for actions that
don't operate on an existing item (``create_work_item``, ``no_action``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import Event, Member, WorkItem, WorkItemUpdate


class ActionError(Exception):
    """Raised for an unknown action, missing/invalid params, or a bad target.

    The caller (confirm endpoint / propose validation) catches this and drops
    the action rather than failing the whole request.
    """


# Handler signature: (session, member, target_id, target_type, params) -> summary.
# target_type is "work_item" | "event" | None — handlers that can target more
# than one thing (create_event) branch on it; work-item-only handlers ignore it.
Handler = Callable[[Session, Member, int | None, str | None, dict], str]

# describe signature: (params) -> deterministic action_summary str. A pure fn of
# params only (no app types) so it is engine-extractable.
DescribeFn = Callable[[dict], str]


@dataclass(frozen=True)
class ActionSpec:
    required: list[str] = field(default_factory=list)
    needs_target: bool = True  # operates on an existing work item?
    logs: bool = True  # appends a source=assistant update on apply?
    apply: Handler = None  # type: ignore[assignment]
    # describe(params) -> the deterministic, registry-derived ``action_summary``:
    # what the action WILL do, built from params. This is ground truth, distinct
    # from any LLM narration (``llm_rationale``). Pure fn of params — no Session,
    # no ORM, no app types — so it moves cleanly into the reusable engine later.
    # Must tolerate missing/partial params (it runs on unconfirmed proposals).
    describe: DescribeFn = None  # type: ignore[assignment]


def _require(params: dict, keys: list[str]) -> None:
    for k in keys:
        if params.get(k) in (None, ""):
            raise ActionError(f"missing required param: {k}")


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


# --- handlers -------------------------------------------------------------


def _apply_set_due_date(session, member, target_id, target_type, params) -> str:
    _require(params, ["due_at"])
    due = _parse_dt(params["due_at"])
    wi = _load_item(session, target_id)
    wi.due_at = due
    wi.updated_at = datetime.now(UTC)
    _append_assistant_update(
        session, member, wi.id, f"Set due date to {due.isoformat()}"
    )
    return f"Set due date to {due.isoformat()}"


def _apply_complete(session, member, target_id, target_type, params) -> str:
    wi = _load_item(session, target_id)
    now = datetime.now(UTC)
    wi.status = "done"
    wi.completed_at = now
    wi.updated_at = now
    _append_assistant_update(session, member, wi.id, "Marked done")
    return "Marked done"


def _apply_create_event(session, member, target_id, target_type, params) -> str:
    """Create an event — standalone OR driven by a work item (task 12).

    * **From a work item** (``target_type == "work_item"`` and a ``target_id``):
      append the driving ``source=assistant`` update, then link the event back to
      it via ``source_update_id`` (EVENT-7). This is the labor-log path.
    * **Standalone** (no work-item target): just insert the event. Events aren't
      part of the labor log, so NO work_item_update is appended (WORKITEM-3).
    """
    _require(params, ["title"])
    now = datetime.now(UTC)

    source_update_id = None
    family_id = member.family_id
    if target_type == "work_item" and target_id is not None:
        wi = _load_item(session, target_id)
        family_id = wi.family_id
        upd = _append_assistant_update(
            session, member, wi.id, f"Created calendar event: {params['title']}"
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
    session.add(ev)
    return f"Created event: {params['title']}"


def _apply_create_work_item(session, member, target_id, target_type, params) -> str:
    _require(params, ["title"])
    now = datetime.now(UTC)
    wi = WorkItem(
        family_id=member.family_id,
        title=params["title"],
        description=params.get("description"),
        tags=params.get("tags", []),
        assigned_to=params.get("assigned_to"),
        created_at=now,
        updated_at=now,
    )
    session.add(wi)
    session.flush()
    _append_assistant_update(
        session, member, wi.id, f"Created work item: {params['title']}"
    )
    return f"Created work item: {params['title']}"


def _apply_no_action(session, member, target_id, target_type, params) -> str:
    return "No action"


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


ACTIONS: dict[str, ActionSpec] = {
    "set_due_date": ActionSpec(
        required=["due_at"],
        apply=_apply_set_due_date,
        describe=_describe_set_due_date,
    ),
    "complete_work_item": ActionSpec(
        apply=_apply_complete, describe=_describe_complete
    ),
    "create_event": ActionSpec(
        required=["title"],
        apply=_apply_create_event,
        describe=_describe_create_event,
    ),
    "create_work_item": ActionSpec(
        required=["title"],
        needs_target=False,
        apply=_apply_create_work_item,
        describe=_describe_create_work_item,
    ),
    "no_action": ActionSpec(
        needs_target=False,
        logs=False,
        apply=_apply_no_action,
        describe=_describe_no_action,
    ),
}


def describe_action(name: str, params: dict) -> str:
    """Registry seam: the deterministic action_summary for ``name`` + ``params``.

    Looks up the spec and calls its ``describe``. Callers (the capture endpoint)
    use this rather than reaching into ``ACTIONS`` so the lookup is decoupled —
    when the registry is extracted into the reusable engine this becomes
    ``registry.describe(name, params)`` with a one-line repoint. Unknown names
    fall back to the name itself (never raises; describe is display-only).
    """
    spec = ACTIONS.get(name)
    if spec is None or spec.describe is None:
        return name
    return spec.describe(params)


def apply_action(
    session: Session,
    member: Member,
    name: str,
    target_id: int | None,
    params: dict,
    target_type: str | None = None,
) -> str:
    """Validate + apply a confirmed action. Returns a human summary.

    ``target_type`` ("work_item" | "event" | None) generalizes the target (task
    12): the conditional log rule lives in the handlers (only a work-item target
    appends a source=assistant update). For backwards compatibility, a present
    ``target_id`` with no explicit ``target_type`` is treated as a work-item
    target, so existing work-item confirms keep logging + linking.

    Does not commit — the caller commits so the write publishes once via the seam.
    Raises ActionError for unknown names / missing params / bad targets.
    """
    spec = ACTIONS.get(name)
    if spec is None:
        raise ActionError(f"unknown action: {name}")
    _require(params, spec.required)
    if target_type is None and target_id is not None:
        target_type = "work_item"
    summary = spec.apply(session, member, target_id, target_type, params)
    session.flush()  # autoflush is off; make all pending rows visible pre-commit
    return summary

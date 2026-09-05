"""Work-item action specs, application handlers, and proposal card details."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.persistence.models import ChecklistItem, Member, TargetType, WorkItem
from app.routing.engine import ActionError, ActionSpec, DataType, Param, require_params

from .context import NtakeActionContext
from .shared import _append_assistant_update, _load_item, _normalized_tags, _parse_dt


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


def _apply_append_update(ctx: NtakeActionContext, params: dict) -> str:
    """Append assistant-composed context to an existing work item's log only."""
    require_params(params, ["body"])
    wi = _load_item(ctx.session, ctx.target_id)
    body = params["body"]
    _append_assistant_update(ctx.session, ctx.member, wi.id, body)
    return "Appended work-item update"


def _apply_set_work_item_tags(ctx: NtakeActionContext, params: dict) -> str:
    require_params(params, ["tags"])
    work_item = _load_item(ctx.session, ctx.target_id)
    work_item.tags = _normalized_tags(params["tags"])
    work_item.updated_at = datetime.now(UTC)
    rendered_tags = ", ".join(work_item.tags) or "(none)"
    note = f"Set tags: {rendered_tags}"
    _append_assistant_update(ctx.session, ctx.member, work_item.id, note)
    return note


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


def _apply_archive_all_done(ctx: NtakeActionContext, params: dict) -> str:
    """Archive every unarchived Done item in the confirming member's family."""
    now = datetime.now(UTC)
    items = list(
        ctx.session.scalars(
            select(WorkItem).where(
                WorkItem.family_id == ctx.member.family_id,
                WorkItem.status == "done",
                WorkItem.archived_at.is_(None),
            )
        ).all()
    )
    for item in items:
        item.archived_at = now
        item.updated_at = now
    count = len(items)
    noun = "item" if count == 1 else "items"
    return f"Archived {count} done work {noun}"


def _validated_checklist_items(value: object) -> list[str]:
    """Return a non-empty list of non-blank checklist strings or raise."""
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(text, str) or not text.strip() for text in value)
    ):
        raise ActionError("items must be a non-empty list of strings")
    return value


def _apply_add_checklist_items(ctx: NtakeActionContext, params: dict) -> str:
    """Insert checklist items (grocery-list style) onto the target work item.

    v1 add-only: takes ``items: [str]`` and appends rows after the current max
    position. (check/uncheck/remove — which need by-name/by-id addressing — are
    deferred.)
    """
    require_params(params, ["items"])
    items = _validated_checklist_items(params["items"])
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


def _apply_check_off_items(ctx: NtakeActionContext, params: dict) -> str:
    """Mark named checklist entries complete on the target work item."""
    require_params(params, ["items"])
    requested = _validated_checklist_items(params["items"])
    work_item = _load_item(ctx.session, ctx.target_id)
    checklist = list(
        ctx.session.scalars(
            select(ChecklistItem)
            .where(ChecklistItem.work_item_id == work_item.id)
            .order_by(ChecklistItem.position, ChecklistItem.id)
        ).all()
    )
    requested_names = {item.strip().casefold() for item in requested}
    matched_names = {
        item.text.strip().casefold()
        for item in checklist
        if item.text.strip().casefold() in requested_names
    }
    missing = requested_names - matched_names
    if missing:
        raise ActionError(f"checklist items not found: {', '.join(sorted(missing))}")

    matched = [
        item for item in checklist if item.text.strip().casefold() in requested_names
    ]
    for item in matched:
        item.checked = True
    work_item.updated_at = datetime.now(UTC)
    count = len(matched)
    noun = "item" if count == 1 else "items"
    note = f"Checked off {count} checklist {noun}"
    _append_assistant_update(ctx.session, ctx.member, work_item.id, note)
    return note


def _apply_create_work_item(ctx: NtakeActionContext, params: dict) -> str:
    """Create a standalone work item, optionally with its initial checklist."""
    require_params(params, ["title"])
    checklist_items = (
        _validated_checklist_items(params["checklist_items"])
        if "checklist_items" in params
        else []
    )
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
    for position, text in enumerate(checklist_items, start=1):
        ctx.session.add(ChecklistItem(work_item_id=wi.id, text=text, position=position))

    note = f"Created work item: {params['title']}"
    if checklist_items:
        note += f" with {len(checklist_items)} checklist item(s)"
    _append_assistant_update(ctx.session, ctx.member, wi.id, note)
    return note


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


def _describe_append_update(params: dict) -> str:
    body = params.get("body")
    return f"Append update: {body}" if body else "Append a work-item update"


def _describe_set_work_item_tags(params: dict) -> str:
    tags = params.get("tags")
    if isinstance(tags, list):
        return f"Set work-item tags: {', '.join(str(tag) for tag in tags)}"
    return "Set work-item tags"


def _describe_archive(params: dict) -> str:
    return "Archive the (done) work item"


def _describe_archive_all_done(params: dict) -> str:
    return "Archive all Done work items"


def _describe_add_checklist_items(params: dict) -> str:
    items = params.get("items")
    if isinstance(items, list) and items:
        return f"Add checklist items: {', '.join(str(i) for i in items)}"
    return "Add checklist items"


def _describe_check_off_items(params: dict) -> str:
    items = params.get("items")
    if isinstance(items, list) and items:
        return f"Check off checklist items: {', '.join(str(item) for item in items)}"
    return "Check off checklist items"


def _describe_create_work_item(params: dict) -> str:
    title = params.get("title")
    return f"Create work item “{title}”" if title else "Create a work item"


def _member_label(resolved: dict, member_id: object) -> str:
    """Resolve a member id to its name via the app-supplied map, else an id token."""
    names = resolved.get("member_names") or {}
    if isinstance(member_id, int) and member_id in names:
        return str(names[member_id])
    return f"member {member_id}"


def _render_assign(params: dict, resolved: dict) -> list[str]:
    return [f"Assign to: {_member_label(resolved, params.get('member_id'))}"]


def _render_set_due_date(params: dict, resolved: dict) -> list[str]:
    due = params.get("due_at")
    return [f"Due: {due}"] if due else []


def _render_set_work_item_tags(params: dict, resolved: dict) -> list[str]:
    tags = params.get("tags")
    if isinstance(tags, list):
        return [f"Tags: {', '.join(str(tag) for tag in tags) or '(none)'}"]
    return []


def _render_create_work_item(params: dict, resolved: dict) -> list[str]:
    lines: list[str] = []
    if params.get("title"):
        lines.append(f"Title: {params['title']}")
    if params.get("description"):
        lines.append(f"Notes: {params['description']}")
    tags = params.get("tags")
    if isinstance(tags, list) and tags:
        lines.append(f"Tags: {', '.join(str(t) for t in tags)}")
    checklist_items = params.get("checklist_items")
    if isinstance(checklist_items, list) and checklist_items:
        lines.append(f"Checklist: {', '.join(str(item) for item in checklist_items)}")
    return lines


def _render_append_update(params: dict, resolved: dict) -> list[str]:
    body = params.get("body")
    return [f"Update: {body}"] if body else []


def _render_add_checklist_items(params: dict, resolved: dict) -> list[str]:
    items = params.get("items")
    if isinstance(items, list) and items:
        return [f"Items: {', '.join(str(i) for i in items)}"]
    return []


def _render_check_off_items(params: dict, resolved: dict) -> list[str]:
    items = params.get("items")
    if isinstance(items, list) and items:
        return [f"Check off: {', '.join(str(item) for item in items)}"]
    return []


WORK_ITEM_ACTIONS: dict[str, ActionSpec[NtakeActionContext]] = {
    "create_work_item": ActionSpec(
        name="create_work_item",
        description="Create a new work item (a task/todo).",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("description", DataType.STRING),
            Param("tags", DataType.ARRAY_STRING),
            Param("checklist_items", DataType.ARRAY_STRING),
        ],
        target_type=None,
        apply=_apply_create_work_item,
        describe=_describe_create_work_item,
        render_card=_render_create_work_item,
    ),
    "append_update": ActionSpec(
        name="append_update",
        description="Append assistant context to an existing work item.",
        params=[Param("body", DataType.STRING, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_append_update,
        describe=_describe_append_update,
        render_card=_render_append_update,
    ),
    "set_due_date": ActionSpec(
        name="set_due_date",
        description="Set a work item's due date.",
        params=[Param("due_at", DataType.DATETIME, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_set_due_date,
        describe=_describe_set_due_date,
        render_card=_render_set_due_date,
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
        render_card=_render_assign,
    ),
    "set_work_item_tags": ActionSpec(
        name="set_work_item_tags",
        description="Replace a work item's complete shared tag list.",
        params=[Param("tags", DataType.ARRAY_STRING, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_set_work_item_tags,
        describe=_describe_set_work_item_tags,
        render_card=_render_set_work_item_tags,
    ),
    "archive_work_item": ActionSpec(
        name="archive_work_item",
        description="Archive a work item (only a done item may be archived).",
        target_type=TargetType.WORK_ITEM,
        apply=_apply_archive_work_item,
        describe=_describe_archive,
    ),
    "archive_all_done": ActionSpec(
        name="archive_all_done",
        description="Archive every unarchived Done work item in the family.",
        target_type=None,
        logs=False,
        apply=_apply_archive_all_done,
        describe=_describe_archive_all_done,
    ),
    "add_checklist_items": ActionSpec(
        name="add_checklist_items",
        description="Add checklist items (e.g. a grocery list) to a work item.",
        params=[Param("items", DataType.ARRAY_STRING, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_add_checklist_items,
        describe=_describe_add_checklist_items,
        render_card=_render_add_checklist_items,
    ),
    "check_off_items": ActionSpec(
        name="check_off_items",
        description="Mark named checklist items complete.",
        params=[Param("items", DataType.ARRAY_STRING, required=True)],
        target_type=TargetType.WORK_ITEM,
        apply=_apply_check_off_items,
        describe=_describe_check_off_items,
        render_card=_render_check_off_items,
    ),
}

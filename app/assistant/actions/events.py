"""Calendar-event action specs, application handlers, and card details."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.persistence.models import Event, TargetType
from app.routing.engine import ActionError, ActionSpec, DataType, Param, require_params

from .context import NtakeActionContext
from .shared import (
    _append_assistant_update,
    _load_event,
    _load_item,
    _normalized_tags,
    _parse_dt,
)


def _normalized_participant_names(
    value: object, *, require_nonempty: bool = False
) -> list[str]:
    """Validate and normalize a name-only participant list.

    Participants deliberately model people as plain names: household members and
    everyone else use the same string shape. Keep the first spelling/order and
    de-duplicate later case-insensitive repeats.
    """
    if value is None and not require_nonempty:
        return []
    if not isinstance(value, list) or (require_nonempty and not value):
        raise ActionError("participants must be a non-empty list of names")

    names: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            raise ActionError("each participant must be a non-empty name")
        name = raw.strip()
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _normalized_location(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ActionError("location must be a non-empty string")
    return value.strip()


def _reschedule_event(ctx: NtakeActionContext, params: dict, *, all_day: bool) -> str:
    """Apply one explicit timing shape to an existing event."""
    ev = _load_event(ctx.session, ctx.target_id)
    if all_day:
        require_params(params, ["start_date"])
        ev.all_day = True
        ev.start_date = date.fromisoformat(params["start_date"])
        ev.end_date = (
            date.fromisoformat(params["end_date"])
            if params.get("end_date")
            else ev.start_date
        )
        ev.start_at = ev.end_at = None
    else:
        require_params(params, ["start_at", "end_at"])
        ev.all_day = False
        ev.start_at = _parse_dt(params["start_at"])
        ev.end_at = _parse_dt(params["end_at"])
        ev.start_date = ev.end_date = None
    ev.updated_at = datetime.now(UTC)
    return f"Rescheduled event “{ev.title}”"


def _apply_reschedule_timed_event(ctx: NtakeActionContext, params: dict) -> str:
    return _reschedule_event(ctx, params, all_day=False)


def _apply_reschedule_all_day_event(ctx: NtakeActionContext, params: dict) -> str:
    return _reschedule_event(ctx, params, all_day=True)


def _create_event(ctx: NtakeActionContext, params: dict, *, all_day: bool) -> str:
    """Create one explicit timing shape, standalone or from a work item."""
    require_params(params, ["title"])
    if all_day:
        require_params(params, ["start_date"])
    else:
        require_params(params, ["start_at", "end_at"])

    now = datetime.now(UTC)
    source_update_id = None
    family_id = ctx.member.family_id
    if ctx.target_type == "work_item" and ctx.target_id is not None:
        wi = _load_item(ctx.session, ctx.target_id)
        family_id = wi.family_id
        update = _append_assistant_update(
            ctx.session, ctx.member, wi.id, f"Created calendar event: {params['title']}"
        )
        source_update_id = update.id

    event = Event(
        family_id=family_id,
        title=params["title"],
        description=params.get("description"),
        location=params.get("location"),
        all_day=all_day,
        start_at=_parse_dt(params["start_at"]) if not all_day else None,
        end_at=_parse_dt(params["end_at"]) if not all_day else None,
        start_date=(date.fromisoformat(params["start_date"]) if all_day else None),
        end_date=(
            date.fromisoformat(params["end_date"])
            if all_day and params.get("end_date")
            else (date.fromisoformat(params["start_date"]) if all_day else None)
        ),
        participants=_normalized_participant_names(params.get("participants")),
        tags=_normalized_tags(params.get("tags")),
        source_update_id=source_update_id,
        created_at=now,
        updated_at=now,
    )
    ctx.session.add(event)
    return f"Created event: {params['title']}"


def _apply_create_timed_event(ctx: NtakeActionContext, params: dict) -> str:
    return _create_event(ctx, params, all_day=False)


def _apply_create_all_day_event(ctx: NtakeActionContext, params: dict) -> str:
    return _create_event(ctx, params, all_day=True)


def _apply_set_event_location(ctx: NtakeActionContext, params: dict) -> str:
    require_params(params, ["location"])
    event = _load_event(ctx.session, ctx.target_id)
    event.location = _normalized_location(params["location"])
    event.updated_at = datetime.now(UTC)
    return f"Set event location to {event.location}"


def _apply_add_event_participants(ctx: NtakeActionContext, params: dict) -> str:
    require_params(params, ["participants"])
    event = _load_event(ctx.session, ctx.target_id)
    additions = _normalized_participant_names(
        params["participants"], require_nonempty=True
    )
    event.participants = _normalized_participant_names(event.participants) + additions
    event.participants = _normalized_participant_names(event.participants)
    event.updated_at = datetime.now(UTC)
    return f"Added {len(additions)} event participant(s)"


def _apply_set_event_tags(ctx: NtakeActionContext, params: dict) -> str:
    require_params(params, ["tags"])
    event = _load_event(ctx.session, ctx.target_id)
    event.tags = _normalized_tags(params["tags"])
    event.updated_at = datetime.now(UTC)
    return f"Set {len(event.tags)} event tag(s)"


def _apply_delete_event(ctx: NtakeActionContext, params: dict) -> str:
    """Delete an existing event (event-only; appends NO work-item update).

    Removes the resolved target event. Like the other event-only actions
    (reschedule/deconflict) it is not part of the labor log. A missing target is
    an ActionError via ``_load_event``.
    """
    ev = _load_event(ctx.session, ctx.target_id)
    title = ev.title
    ctx.session.delete(ev)
    return f"Deleted event “{title}”"


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


def _describe_reschedule_event(params: dict) -> str:
    when = params.get("start_at") or params.get("start_date")
    return f"Reschedule the event to {when}" if when else "Reschedule the event"


def _describe_create_event(params: dict) -> str:
    title = params.get("title")
    when = params.get("start_at") or params.get("start_date")
    if title and when:
        return f"Create event “{title}” at {when}"
    if title:
        return f"Create event “{title}”"
    return "Create a calendar event"


def _describe_set_event_location(params: dict) -> str:
    location = params.get("location")
    return f"Set event location to {location}" if location else "Set event location"


def _describe_add_event_participants(params: dict) -> str:
    participants = params.get("participants")
    if isinstance(participants, list) and participants:
        names = ", ".join(str(name) for name in participants)
        return f"Add event participants: {names}"
    return "Add event participants"


def _describe_set_event_tags(params: dict) -> str:
    tags = params.get("tags")
    if isinstance(tags, list):
        return f"Set event tags: {', '.join(str(tag) for tag in tags)}"
    return "Set event tags"


def _describe_delete_event(params: dict) -> str:
    return "Delete the event"


def _describe_deconflict(params: dict) -> str:
    return "Move the event to the next day (deconflict)"


def _when(params: dict) -> str | None:
    """A readable timing string from timed/all-day params, or None."""
    return params.get("start_at") or params.get("start_date") or None


def _render_reschedule(params: dict, resolved: dict) -> list[str]:
    lines: list[str] = []
    label = resolved.get("target_label")
    if label:
        lines.append(f"Event: {label}")
    when = _when(params)
    if when:
        lines.append(f"New time: {when}")
    return lines


def _render_create_event(params: dict, resolved: dict) -> list[str]:
    lines: list[str] = []
    if params.get("title"):
        lines.append(f"Title: {params['title']}")
    when = _when(params)
    if when:
        lines.append(f"When: {when}")
    if params.get("location"):
        lines.append(f"Location: {params['location']}")
    if params.get("description"):
        lines.append(f"Notes: {params['description']}")
    return lines


def _render_set_event_location(params: dict, resolved: dict) -> list[str]:
    location = params.get("location")
    return [f"Location: {location}"] if location else []


def _render_add_event_participants(params: dict, resolved: dict) -> list[str]:
    participants = params.get("participants")
    if isinstance(participants, list) and participants:
        return [f"Participants: {', '.join(str(name) for name in participants)}"]
    return []


def _render_set_event_tags(params: dict, resolved: dict) -> list[str]:
    tags = params.get("tags")
    if isinstance(tags, list):
        return [f"Tags: {', '.join(str(tag) for tag in tags) or '(none)'}"]
    return []


EVENT_ACTIONS: dict[str, ActionSpec[NtakeActionContext]] = {
    "create_timed_event": ActionSpec(
        name="create_timed_event",
        description="Create a timed calendar event.",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("start_at", DataType.DATETIME, required=True),
            Param("end_at", DataType.DATETIME, required=True),
            Param("description", DataType.STRING),
            Param("location", DataType.STRING),
            Param("participants", DataType.ARRAY_STRING),
            Param("tags", DataType.ARRAY_STRING),
        ],
        target_type=None,
        apply=_apply_create_timed_event,
        describe=_describe_create_event,
        render_card=_render_create_event,
    ),
    "create_all_day_event": ActionSpec(
        name="create_all_day_event",
        description="Create an all-day calendar event.",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("start_date", DataType.DATE, required=True),
            Param("end_date", DataType.DATE),
            Param("description", DataType.STRING),
            Param("location", DataType.STRING),
            Param("participants", DataType.ARRAY_STRING),
            Param("tags", DataType.ARRAY_STRING),
        ],
        target_type=None,
        apply=_apply_create_all_day_event,
        describe=_describe_create_event,
        render_card=_render_create_event,
    ),
    "reschedule_timed_event": ActionSpec(
        name="reschedule_timed_event",
        description="Move an existing event to a timed range.",
        params=[
            Param("start_at", DataType.DATETIME, required=True),
            Param("end_at", DataType.DATETIME, required=True),
        ],
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_reschedule_timed_event,
        describe=_describe_reschedule_event,
        render_card=_render_reschedule,
    ),
    "reschedule_all_day_event": ActionSpec(
        name="reschedule_all_day_event",
        description="Move an existing event to all-day date(s).",
        params=[
            Param("start_date", DataType.DATE, required=True),
            Param("end_date", DataType.DATE),
        ],
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_reschedule_all_day_event,
        describe=_describe_reschedule_event,
        render_card=_render_reschedule,
    ),
    "set_event_location": ActionSpec(
        name="set_event_location",
        description="Set an existing event's location.",
        params=[Param("location", DataType.STRING, required=True)],
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_set_event_location,
        describe=_describe_set_event_location,
        render_card=_render_set_event_location,
    ),
    "add_event_participants": ActionSpec(
        name="add_event_participants",
        description="Add people by name to an existing event.",
        params=[Param("participants", DataType.ARRAY_STRING, required=True)],
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_add_event_participants,
        describe=_describe_add_event_participants,
        render_card=_render_add_event_participants,
    ),
    "set_event_tags": ActionSpec(
        name="set_event_tags",
        description="Replace an existing event's complete shared tag list.",
        params=[Param("tags", DataType.ARRAY_STRING, required=True)],
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_set_event_tags,
        describe=_describe_set_event_tags,
        render_card=_render_set_event_tags,
    ),
    "delete_event": ActionSpec(
        name="delete_event",
        description="Delete an existing event (e.g. it was cancelled).",
        # Targets an existing event; event-only so it appends NO work-item update.
        target_type=TargetType.EVENT,
        logs=False,
        apply=_apply_delete_event,
        describe=_describe_delete_event,
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

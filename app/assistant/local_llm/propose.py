"""PROPOSE stage: prompt/tools schema, tolerant parsing, and action planning."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.assistant.actions.registry import REGISTRY
from app.assistant.capture import FocusedContext, ProposedAction
from app.assistant.local_llm.protocol import LLM
from app.assistant.tools_view import build_ntake_tools_view
from app.persistence.models import TargetType
from app.persistence.temporal import validate_family_local_datetime
from app.routing.engine import (
    ActionError,
    ActionRegistry,
    ActionSpec,
    AssistantClient,
    DataType,
)

# --- CALL 2: PROPOSE (action planning) ------------------------------------
# Input: the tools view (menu) + the DEEP, NARROW context (full records —
# incl. the target work item's whole update history — for only the linked ids)
# + the note. Output: zero or more tool calls, WITHOUT ids (the server attaches
# the target from what LINK resolved).

PROPOSE_SYSTEM = """\
You are a household assistant. A family member typed a short note. Propose the
actions from AVAILABLE TOOLS that carry out what they mean — nothing more.

You are also given CONTEXT: the specific item(s)/event(s) the note is about,
including a work item's recent update history, so you can reason about what has
already happened.

Rules:
- Propose ONLY tools from AVAILABLE TOOLS, using their exact names and parameter
  names. If a tool lists "(exactly one of: ...)", supply exactly one such group.
- Do NOT include any entity id in params — the item/event being acted on is
  already known from CONTEXT and is attached for you. Only supply the payload
  params a tool lists.
- Create versus modify: use a work-item modifier (for example,
  `add_checklist_items`, `append_update`, or `move_to_on_deck`) only when
  CONTEXT contains its existing resolved work item. If no relevant work item is
  in CONTEXT, use `create_work_item` for a new task/list or `no_action`; never
  propose a work-item modifier without that existing target. `create_work_item`
  needs only a title; include optional `checklist_items` only when the note
  supplies concrete entries.
  Similarly, use an event modifier only for an existing resolved event. Use
  `create_timed_event` when the note supplies times, or `create_all_day_event`
  for an all-day date range.
- Event participants are plain display names, never IDs or objects. When a new
  event is about a named person in THE NOTE or CONTEXT, include that name in its
  `participants` list unless the note explicitly says otherwise.
- Calendar frame: the family timezone is {timezone}; its current local date and
  time is {local_now} ({local_weekday}). A bare weekday means its next occurrence
  after the current local date.
- Timed tool values are offset-free ISO-8601 family-local wall times, for example
  `2026-09-04T19:00:00`. Never emit UTC, a `Z` suffix, an offset, or a timezone;
  the server supplies the family timezone and converts only when persisting.
  All-day values are local `YYYY-MM-DD` dates.
- If nothing sensible applies, return exactly one no_action.
- When a note reports that work has begun, prefer `start_work_item`. When it
  reports named checklist items were obtained or completed, prefer
  `check_off_items` with those names.
- Use `append_update` only when no structured action captures the reported
  change. Return multiple actions when a note reports multiple independent
  structured updates.
- Prefer one precise action over several speculative ones.

Return JSON exactly:
{{"actions": [{{"name": "<tool>", "params": {{ ... }}}}, ...]}}
"""

PROPOSE_CONTEXT = """\
{tools_view}

CAPTURE:
FROM: {capture_author}
NOTE: "{note}"

CONTEXT:
{deep_context}
"""


def build_propose_prompt(
    *,
    tools_view: str,
    capture_author: str,
    deep_context: str,
    note: str,
    now: datetime,
    timezone: str,
):
    """Return the system and user messages for the family-local PROPOSE call."""
    aware_now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    local_now = aware_now.astimezone(ZoneInfo(timezone))
    system = PROPOSE_SYSTEM.format(
        timezone=timezone,
        local_now=local_now.replace(tzinfo=None).isoformat(),
        local_weekday=local_now.strftime("%A"),
    )
    user = PROPOSE_CONTEXT.format(
        tools_view=tools_view,
        capture_author=capture_author,
        deep_context=deep_context,
        note=note,
    )
    return system, user


def build_tools_schema(registry: ActionRegistry) -> dict:
    """Render every registered action as the PROPOSE output JSON schema."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["actions"],
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "oneOf": [_action_item(spec) for spec in registry.all()],
                },
            }
        },
    }


def _action_item(spec: ActionSpec) -> dict:
    """One action as a discriminated ``{name, params}`` schema branch."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "params"],
        "properties": {
            "name": {"const": spec.name},
            "params": _params_schema(spec),
        },
    }


def _params_schema(spec: ActionSpec) -> dict:
    """Assemble one action's parameters from its declared ``Param`` values."""
    schema: dict = {
        "type": "object",
        "properties": {p.name: p.datatype.json_schema for p in spec.params},
        "additionalProperties": False,
    }
    required = spec.required
    if required:
        schema["required"] = required
    if spec.exclusive_params:
        schema["oneOf"] = [
            {"required": required + group} for group in spec.exclusive_params
        ]
    return schema


class LocalLlmAssistant(AssistantClient[FocusedContext]):
    """Propose actions for a focused context via one constrained LLM call."""

    def __init__(self, llm: LLM, registry: ActionRegistry = REGISTRY) -> None:
        self._llm = llm
        self._registry = registry

    def propose(self, ctx: FocusedContext) -> list[ProposedAction]:
        system, user = build_propose_prompt(
            tools_view=build_ntake_tools_view(self._registry),
            capture_author=ctx.capture_author or "(unknown)",
            deep_context=ctx.deep_context,
            note=ctx.text,
            now=ctx.now,
            timezone=ctx.timezone,
        )
        reply = self._llm.complete(
            system=system, user=user, schema=build_tools_schema(self._registry)
        )
        proposals: list[ProposedAction] = []
        for call in _parse_actions(reply):
            spec = self._registry.get(call["name"])
            # Drop unknown actions and structurally invalid calls. Deep temporal
            # validation (including DST) happens uniformly at confirm/write time.
            if (
                spec is None
                or not spec.accepts(call["params"])
                or not _has_valid_local_times(spec, call["params"], ctx.timezone)
            ):
                continue
            proposal = self._attach(call, ctx)
            if spec.needs_target and proposal.target_id is None:
                continue
            proposals.append(proposal)
        return proposals

    def _attach(self, call: dict, ctx: FocusedContext) -> ProposedAction:
        """Attach a server-known target to a validated model tool call."""
        name = call["name"]
        spec = self._registry.get(name)
        target_type = spec.target_type if spec is not None else None
        target_id: int | None = None
        if target_type == TargetType.WORK_ITEM:
            target_id = ctx.primary_work_item_id
        elif target_type == TargetType.EVENT:
            target_id = ctx.primary_event_id
        return ProposedAction(
            name=name,
            params=call["params"],
            target_id=target_id,
            target_type=target_type,
        )


def _parse_actions(reply: dict) -> list[dict]:
    """Extract valid-shape ``{name, params}`` calls from untrusted model output."""
    actions = reply.get("actions")
    if not isinstance(actions, list):
        return []
    calls: list[dict] = []
    for entry in actions:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        params = entry.get("params", {})
        if not isinstance(name, str) or not isinstance(params, dict):
            continue
        calls.append({"name": name, "params": params})
    return calls


def _has_valid_local_times(spec: ActionSpec, params: dict, timezone: str) -> bool:
    """Reject non-local or DST-invalid timed model values without rewriting them."""
    try:
        for param in spec.params:
            if param.datatype is DataType.LOCAL_DATETIME and param.name in params:
                value = params[param.name]
                if not isinstance(value, str):
                    return False
                validate_family_local_datetime(value, timezone)
    except ActionError:
        return False
    return True

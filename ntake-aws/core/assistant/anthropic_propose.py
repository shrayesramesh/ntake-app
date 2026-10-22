"""PROPOSE stage — plan actions over the registry via one Anthropic tool-use call.

The stage-2 :class:`AssistantClient` (AWS_LLD §3.2): the registry is projected to
Anthropic ``tools``; the model is asked — with ``tool_choice: {type: "any"}`` — to
select the verb(s) that carry out the note, and the ``tool_use`` block(s) it emits
are mapped to :class:`ProposedAction` cards. ``no_action`` is a registered tool, so
"nothing to propose" is a normal selection.

**Selection, not execution.** This maps tool calls to proposal cards and stops. It
never executes an action, never writes through the repository, never returns a
``tool_result``, and never loops — execution happens only on human Confirm, via
``ActionSpec.execute`` (the propose-and-confirm contract, AWS_LLD §3.2).

**The §3.6 action/parameter split.** PROPOSE is factored into three separable
pieces so the deferred GENERATE⇒DECIDE reshape is a localized swap:

1. **action-space projection** — :func:`build_tools_schema` (registry → ``tools``,
   pure; carries the per-request id-enum overlay);
2. **the model call** — the one swappable unit behind the ``AnthropicClient`` seam
   (:meth:`AnthropicAssistant.propose`, today one Claude call);
3. **result mapping** — :func:`_proposals_from` (``tool_use`` block(s) →
   ``ProposedAction``: id re-validate, drop-invalid, target attach; pure given the
   context).

Only piece 2 changes under the refactor; v1 builds **no** separate
parameter-generator or decision-model interface (YAGNI — AWS_LLD §3.6).

**Graceful degrade.** The model call is untrusted: any failure (API error, missing
blocks, malformed ``input``) degrades to **no proposals** — it never raises into the
request path (the engine's ``propose_bounded`` bounds the clock; this bounds the
content).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo

from core.actions.registry import REGISTRY
from core.assistant.anthropic_client import AnthropicClient
from core.assistant.capture import FocusedContext, ProposedAction
from core.engine.engine import (
    ActionError,
    ActionRegistry,
    ActionSpec,
    AssistantClient,
    DataType,
    Param,
)
from core.schemas import TargetType
from core.temporal import validate_family_local_datetime

# Params whose value is an in-family entity id the model chooses from a whitelist
# (enum-over-whitelist, AWS_LLD §3.2). v1 has exactly one: ``member_id`` (assign).
# The target work-item/event id is NOT a param — the app attaches it from LINK's
# resolved ids (``_attach``), so only member selection is enum-constrained here.
_MEMBER_ID_PARAM = "member_id"

_PROPOSE_SYSTEM = """\
You are a household assistant. A family member typed a short note. Use the tools \
to carry out exactly what they mean — nothing more.

CONTEXT names the specific item(s)/event(s) the note is about, including a work \
item's recent update history, so you can reason about what already happened. The \
item/event being acted on is already known from CONTEXT and attached for you — do \
NOT pass any entity id; supply only a tool's payload params.

Rules:
- Use a modifier tool only for an existing resolved item/event in CONTEXT; \
otherwise use a create tool or no_action. Never modify a target that isn't there.
- Event participants are plain display names. Include a named person from the \
note in a new event's participants unless the note says otherwise.
- The family timezone is {timezone}; now is {local_now} ({local_weekday}). A bare \
weekday means its next occurrence. Timed values are offset-free ISO-8601 \
family-local wall times (e.g. 2026-09-04T19:00:00) — never UTC, a Z suffix, an \
offset, or a timezone. All-day values are local YYYY-MM-DD dates.
- Return multiple tool calls for multiple independent updates; prefer one precise \
action over several speculative ones. If nothing sensible applies, use no_action."""

_PROPOSE_USER = """\
CAPTURE:
FROM: {capture_author}
NOTE: "{note}"

CONTEXT:
{deep_context}"""


def _id_whitelists(ctx: FocusedContext) -> dict[str, list[str]]:
    """The per-request id enums, keyed by param name (AWS_LLD §3.2).

    Only ``member_id`` is an enum-constrained param in v1; its whitelist is LINK's
    resolved member ids. (The work-item/event target is attached by the app, not a
    model-chosen param, so it is not an enum here.)
    """
    return {_MEMBER_ID_PARAM: list(ctx.resolved_member_ids)}


def _param_schema(param: Param, whitelists: dict[str, list[str]]) -> dict[str, Any]:
    """One param's JSON-Schema fragment, overlaying the id enum when applicable."""
    if param.name in whitelists:
        # enum-over-whitelist: the model picks WHICH resolved id, not a new one.
        return {**param.datatype.json_schema, "enum": list(whitelists[param.name])}
    return dict(param.datatype.json_schema)


def _input_schema(spec: ActionSpec, whitelists: dict[str, list[str]]) -> dict[str, Any]:
    """Assemble one action's ``input_schema`` from its declared params (§3.3)."""
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {p.name: _param_schema(p, whitelists) for p in spec.params},
    }
    if spec.required:
        schema["required"] = spec.required
    if spec.exclusive_params:
        schema["oneOf"] = [
            {"required": spec.required + group} for group in spec.exclusive_params
        ]
    return schema


def _omit_for_empty_enum(spec: ActionSpec, whitelists: dict[str, list[str]]) -> bool:
    """Whether to drop a tool because a REQUIRED id param has an empty whitelist.

    An empty ``enum`` is invalid JSON Schema and would force the model toward a
    tool it cannot fill, so when the whitelist for a required id-bearing param is
    empty we omit the tool entirely (AWS_LLD §3.2 empty-whitelist edge). An
    optional id param with an empty whitelist does not justify omission — the model
    can simply leave it out — so only required ones trigger the drop.
    """
    required = set(spec.required)
    return any(
        name in required and not whitelists[name]
        for name in whitelists
        if any(p.name == name for p in spec.params)
    )


def build_tools_schema(
    registry: ActionRegistry, whitelists: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """Project the action registry onto Anthropic ``tools`` (AWS_LLD §3.2/§3.3).

    One tool per registered action — ``name`` = action name, ``description`` =
    ``ActionSpec.description``, ``input_schema`` = the JSON Schema assembled from
    ``params`` with the per-request id-enum overlay. A tool whose required id param
    has an empty whitelist is omitted (the empty-``enum`` edge), so a degraded LINK
    lands on ``no_action`` / a no-target create rather than an unfillable tool.

    Pure — piece 1 of the §3.6 split (action-space projection).
    """
    tools: list[dict[str, Any]] = []
    for spec in registry.all():
        if _omit_for_empty_enum(spec, whitelists):
            continue
        tools.append(
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": _input_schema(spec, whitelists),
            }
        )
    return tools


def _tool_use_blocks(response: dict[str, Any]) -> list[dict[str, Any]]:
    """The well-formed ``tool_use`` blocks in a Messages response (tolerant)."""
    blocks: list[dict[str, Any]] = []
    for block in response.get("content", []):
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name")
        data = block.get("input")
        if isinstance(name, str) and isinstance(data, dict):
            blocks.append({"name": name, "input": data})
    return blocks


def _has_valid_local_times(spec: ActionSpec, params: dict, timezone: str) -> bool:
    """Reject non-local / DST-invalid timed model values without rewriting them.

    A ``LOCAL_DATETIME`` param must be an offset-free, existent, unambiguous
    family-local wall time (BUG-002 / the UTC-leak drop). A ``Z``-suffixed or
    offset-bearing value, or a nonexistent/ambiguous local time, is dropped rather
    than exposed as a proposal. Deep validation is deferred to confirm/write time;
    this only guards the shape PROPOSE surfaces.
    """
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


def _ids_on_whitelist(
    spec: ActionSpec, params: dict, whitelists: dict[str, list[str]]
) -> bool:
    """App-side re-validation of enum-constrained id params (defense-in-depth).

    The enum in the tool schema already constrains the model, but constrained
    decoding is best-effort, so every id-bearing param value is re-checked against
    its whitelist here regardless (AWS_LLD §3.2). A value off the whitelist drops
    the whole call.
    """
    for name, allowed in whitelists.items():
        if name in params and params[name] not in allowed:
            return False
    return True


class AnthropicAssistant(AssistantClient[FocusedContext]):
    """Propose actions for a focused context via one Anthropic tool-use call."""

    def __init__(
        self, client: AnthropicClient, registry: ActionRegistry = REGISTRY
    ) -> None:
        self._client = client
        self._registry = registry

    def propose(self, ctx: FocusedContext) -> list[ProposedAction]:
        """One PROPOSE call → proposal cards; degrades to ``[]`` on any failure."""
        try:
            whitelists = _id_whitelists(ctx)
            tools = build_tools_schema(self._registry, whitelists)
            system, user = build_propose_prompt(ctx)
            response = self._client.create_message(
                system,
                [{"role": "user", "content": [{"type": "text", "text": user}]}],
                tools=tools,
                tool_choice={"type": "any"},
            )
            return self._proposals_from(response, ctx, whitelists)
        except Exception:  # noqa: BLE001 — never raise into the request path
            return []

    def _proposals_from(
        self,
        response: dict[str, Any],
        ctx: FocusedContext,
        whitelists: dict[str, list[str]],
    ) -> list[ProposedAction]:
        """Map ``tool_use`` block(s) → validated, target-attached cards (§3.6 #3)."""
        proposals: list[ProposedAction] = []
        for call in _tool_use_blocks(response):
            spec = self._registry.get(call["name"])
            params = call["input"]
            # Drop unknown actions and structurally/temporally invalid calls, and
            # re-validate enum ids against the whitelist (defense-in-depth).
            if (
                spec is None
                or not spec.accepts(params)
                or not _has_valid_local_times(spec, params, ctx.timezone)
                or not _ids_on_whitelist(spec, params, whitelists)
            ):
                continue
            proposal = self._attach(spec, params, ctx)
            if spec.needs_target and proposal.target_id is None:
                continue
            proposals.append(proposal)
        return proposals

    def _attach(
        self, spec: ActionSpec, params: dict, ctx: FocusedContext
    ) -> ProposedAction:
        """Attach the server-known target (from LINK's resolved ids) to a call."""
        target_type = spec.target_type
        target_id: str | None = None
        if target_type == TargetType.WORK_ITEM:
            target_id = ctx.primary_work_item_id
        elif target_type == TargetType.EVENT:
            target_id = ctx.primary_event_id
        return ProposedAction(
            name=spec.name,
            params=params,
            target_id=target_id,
            target_type=target_type,
        )


def build_propose_prompt(ctx: FocusedContext) -> tuple[str, str]:
    """Return (system, user) for the PROPOSE call (family-local ``now`` in prompt)."""
    aware = ctx.now if ctx.now.tzinfo else ctx.now.replace(tzinfo=UTC)
    local = aware.astimezone(ZoneInfo(ctx.timezone))
    system = _PROPOSE_SYSTEM.format(
        timezone=ctx.timezone,
        local_now=local.replace(tzinfo=None).isoformat(),
        local_weekday=local.strftime("%A"),
    )
    user = _PROPOSE_USER.format(
        capture_author=ctx.capture_author or "(unknown)",
        note=ctx.text,
        deep_context=ctx.deep_context,
    )
    return system, user

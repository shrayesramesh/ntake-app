"""``LocalLlmAssistant`` — the PROPOSE call (LLM call 2).

Stage-2 seam (:class:`AssistantClient`) backed by a real model. It composes the
already-built pieces — ``build_propose_prompt`` (the prompt) + ``build_tools_schema``
(the constrained-output schema) — calls the injected :class:`LLM` seam, then turns
the reply into ``[ProposedAction]``: parse the actions array, keep only calls
that name a registered action **and** whose params satisfy that action's contract
(``ActionSpec.accepts`` — required present + exactly one exclusive group), and
attach the server-known target from the resolved ids in the ``FocusedContext``.

The model emits **id-free** ``{name, params}``; ids never come from the model. The
target is attached here (LLD OQ-4, v1): type-based, ≤1 resolved entity per type,
driven by the action's declared ``ActionSpec.target_type`` (the single source both
assistants read) — ``"work_item"`` → the primary work-item id, ``"event"`` → the
primary event id, ``None`` (a creator / ``no_action``) → no target.

Depends on the ``LLM`` protocol, never on httpx. Parse here is deliberately
lenient (drop what doesn't fit) so a sloppy model degrades to fewer/zero
proposals rather than raising; the exhaustive adversarial hardening is step 6.
"""

from __future__ import annotations

from app.assistant.actions import REGISTRY
from app.assistant.capture import FocusedContext, ProposedAction
from app.assistant.local_llm.protocol import LLM
from app.assistant.local_llm.tools_schema import build_tools_schema
from app.assistant.prompts import build_propose_prompt
from app.assistant.tools_view import build_tools_view
from app.models import TargetType
from app.routing.engine import ActionRegistry, AssistantClient


class LocalLlmAssistant(AssistantClient[FocusedContext]):
    """Propose actions for a focused context via one constrained LLM call."""

    def __init__(self, llm: LLM, registry: ActionRegistry = REGISTRY) -> None:
        self._llm = llm
        self._registry = registry

    def propose(self, ctx: FocusedContext) -> list[ProposedAction]:
        system, user = build_propose_prompt(
            tools_view=build_tools_view(self._registry),
            deep_context=ctx.deep_context,
            note=ctx.text,
            now=ctx.now,
            timezone=ctx.timezone,
        )
        schema = build_tools_schema(self._registry)
        reply = self._llm.complete(system=system, user=user, schema=schema)
        proposals: list[ProposedAction] = []
        for call in _parse_actions(reply):
            spec = self._registry.get(call["name"])
            # Drop unknown actions and calls that don't satisfy the spec's param
            # contract (missing required / wrong exclusive-group) — graceful
            # degrade to fewer proposals, never a raise (LLD OQ-5).
            if spec is None or not spec.accepts(call["params"]):
                continue
            proposals.append(self._attach(call, ctx))
        return proposals

    def _attach(self, call: dict, ctx: FocusedContext) -> ProposedAction:
        """Turn a validated ``{name, params}`` into a targeted ProposedAction.

        The target category comes from the action's declared
        ``ActionSpec.target_type`` (single source): ``"work_item"`` → the primary
        resolved work-item id, ``"event"`` → the primary resolved event id,
        ``None`` (a creator / no_action) → no target. Ids come from the context,
        never the model.
        """
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
    """Extract the ``{name, params}`` tool calls from the model reply.

    Tolerant of untrusted output: a missing/non-list ``actions`` → ``[]``; each
    entry must be a dict with a string ``name`` (``params`` defaults to ``{}`` and
    must be a dict). Anything malformed is dropped (graceful-degrade; step 6
    tightens the adversarial cases).
    """
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

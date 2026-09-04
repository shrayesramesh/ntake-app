"""``LocalLlmAssistant`` — the PROPOSE call (LLM call 2).

Stage-2 seam (:class:`AssistantClient`) backed by a real model. It composes the
already-built pieces — ``build_propose_prompt`` (the prompt) + ``build_tools_schema``
(the constrained-output schema) — calls the injected :class:`LLM` seam, then turns
the reply into ``[ProposedAction]``: parse the actions array, keep only calls
naming a registered action, and attach the server-known target from the resolved
ids in the ``FocusedContext``.

The model emits **id-free** ``{name, params}``; ids never come from the model. The
target is attached here (LLD OQ-4, v1): type-based, ≤1 resolved entity per type —
a ``needs_target`` action gets the context's primary work-item id, except the
event-targeting actions, which get the primary event id. Creators / ``no_action``
(``needs_target=False``) get no target.

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
from app.routing.engine import ActionRegistry, AssistantClient

# Actions whose target is an event (not a work item). Everything else that
# ``needs_target`` targets a work item; ``needs_target=False`` targets nothing.
# (v1's two event-targeting actions; kept explicit here — the attach seam's small
# bit of domain knowledge, mirroring what FakeAssistant encodes per-action.)
_EVENT_TARGET_ACTIONS = frozenset({"reschedule_event", "deconflict_events"})


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
        return [
            self._attach(call, ctx)
            for call in _parse_actions(reply)
            if self._registry.get(call["name"]) is not None
        ]

    def _attach(self, call: dict, ctx: FocusedContext) -> ProposedAction:
        """Turn a validated ``{name, params}`` into a targeted ProposedAction."""
        name = call["name"]
        spec = self._registry.get(name)
        target_id: int | None = None
        target_type: str | None = None
        if spec is not None and spec.needs_target:
            if name in _EVENT_TARGET_ACTIONS:
                target_id, target_type = ctx.primary_event_id, "event"
            else:
                target_id, target_type = ctx.primary_work_item_id, "work_item"
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

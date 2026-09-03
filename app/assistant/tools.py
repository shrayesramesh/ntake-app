"""``build_tools_view`` — the LLM-facing render of the action registry.

The parallel of ``build_world_view``: where the world view is "state of the
world", the tools view is "the tools you can call" — the menu of actions the
model may propose, rendered to plain text for the prompt from each spec's
``prompt_line``.

Vocabulary: "actions" are what we *execute* (the engine's ``ActionSpec`` /
``ActionRegistry`` / ``ProposedAction``); "tools" are how those same actions are
*presented to the LLM*. An action becomes a tool only here, at the model
boundary. This renders generic spec fields (name/description/params) and imports
nothing model-specific, so it lives in ``app/assistant/`` alongside the world view.
"""

from __future__ import annotations

from app.routing.engine import ActionRegistry


def build_tools_view(registry: ActionRegistry) -> str:
    """Render every registered action as the LLM's tool menu (one line each)."""
    lines = ["AVAILABLE TOOLS:"]
    lines += [spec.prompt_line for spec in registry.all()]
    return "\n".join(lines)

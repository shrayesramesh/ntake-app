"""Non-mutating meta actions accepted by the assistant planner."""

from __future__ import annotations

from app.routing.engine import ActionSpec

from .context import NtakeActionContext


def _apply_no_action(ctx: NtakeActionContext, params: dict) -> str:
    return "No action"


def _describe_no_action(params: dict) -> str:
    return "No action"


META_ACTIONS: dict[str, ActionSpec[NtakeActionContext]] = {
    "no_action": ActionSpec(
        name="no_action",
        description="Nothing to suggest.",
        target_type=None,
        logs=False,
        apply=_apply_no_action,
        describe=_describe_no_action,
    ),
}

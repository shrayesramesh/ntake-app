"""Non-mutating meta actions accepted by the assistant planner.

Session 3: re-specialized to the ported :class:`NtakeActionContext` (built on
the ``Repository`` seam) now that the registry is live, per the Session-1
banner. ``no_action`` ignores its context entirely — it is the registered
"nothing to propose" tool (AWS_LLD §3.2).
"""

from __future__ import annotations

from core.engine.engine import ActionSpec

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

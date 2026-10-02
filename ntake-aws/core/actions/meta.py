"""Non-mutating meta actions accepted by the assistant planner.

Session 1: typed against the engine's base ``ActionContext`` so this stays a
LIVE, gated module — ``no_action`` ignores its context entirely, so it needs no
plugin-specific context. Session 2 re-specializes the registry (and this spec's
``ContextT``) to the rebuilt ``NtakeActionContext`` once that is ported onto the
``Repository`` seam (AWS_LLD §2). ``no_action`` is the registered "nothing to
propose" tool (AWS_LLD §3.2).
"""

from __future__ import annotations

from core.engine.engine import ActionContext, ActionSpec


def _apply_no_action(ctx: ActionContext, params: dict) -> str:
    return "No action"


def _describe_no_action(params: dict) -> str:
    return "No action"


META_ACTIONS: dict[str, ActionSpec[ActionContext]] = {
    "no_action": ActionSpec(
        name="no_action",
        description="Nothing to suggest.",
        target_type=None,
        logs=False,
        apply=_apply_no_action,
        describe=_describe_no_action,
    ),
}

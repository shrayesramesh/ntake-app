"""The meta action (core/actions/meta.py) — the only live action module in
Session 1 (it imports just the engine; the work-item/event handlers are parked
for Session 2). ``no_action`` is the registered "nothing to propose" tool
(AWS_LLD §3.2), so it must dispatch cleanly over the engine with an opaque ctx.
"""

from __future__ import annotations

from core.actions.meta import META_ACTIONS
from core.engine.engine import ActionContext, ActionRegistry


def test_no_action_spec_shape() -> None:
    spec = META_ACTIONS["no_action"]
    assert spec.name == "no_action"
    assert spec.target_type is None and spec.needs_target is False
    assert spec.logs is False
    assert spec.params == []


def test_no_action_describe_and_apply() -> None:
    spec = META_ACTIONS["no_action"]
    assert spec.describe({}) == "No action"
    assert spec.apply(ActionContext(), {}) == "No action"


def test_no_action_dispatches_over_the_engine() -> None:
    reg = ActionRegistry(list(META_ACTIONS.values()))
    assert reg.dispatch("no_action", {}, ActionContext()) == "No action"
    assert reg.describe("no_action", {}) == "No action"

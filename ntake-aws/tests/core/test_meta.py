"""The meta action (core/actions/meta.py) — ``no_action``, the registered
"nothing to propose" tool (AWS_LLD §3.2). Session 3 re-specialized it to the
ported ``NtakeActionContext`` (the ``Repository`` seam), so it must still
dispatch cleanly over the engine with that context — which ``no_action`` ignores.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.actions.context import NtakeActionContext
from core.actions.meta import META_ACTIONS
from core.engine.engine import ActionRegistry
from core.repository_memory import InMemoryRepository
from core.schemas import Member


def _ctx() -> NtakeActionContext:
    """A minimal context — ``no_action`` ignores every field."""
    member = Member(
        id="mem1",
        family_id="fam1",
        display_name="Alex",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return NtakeActionContext(
        repo=InMemoryRepository(),
        member=member,
        family_timezone="UTC",
        target_id=None,
        target_type=None,
    )


def test_no_action_spec_shape() -> None:
    spec = META_ACTIONS["no_action"]
    assert spec.name == "no_action"
    assert spec.target_type is None and spec.needs_target is False
    assert spec.logs is False
    assert spec.params == []


def test_no_action_describe_and_apply() -> None:
    spec = META_ACTIONS["no_action"]
    assert spec.describe({}) == "No action"
    assert spec.apply(_ctx(), {}) == "No action"


def test_no_action_dispatches_over_the_engine() -> None:
    reg = ActionRegistry(list(META_ACTIONS.values()))
    assert reg.dispatch("no_action", {}, _ctx()) == "No action"
    assert reg.describe("no_action", {}) == "No action"

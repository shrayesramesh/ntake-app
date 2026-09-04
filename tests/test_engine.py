"""Engine boundary + generic registry contract (reusable propose-confirm engine).

The engine (``app.routing``) is domain-agnostic: it knows how to register
actions, validate params, dispatch to a handler with an OPAQUE context it never
inspects, describe an action from its params, and run a bounded/graceful-degrade
propose. It must import NOTHING app-specific — no app.models, no sqlalchemy, no
fastapi — which is what makes it extractable into its own package later.

These tests use a fake handler + a fake opaque context (a plain dict), so they
exercise the engine with zero ORM / zero app types.
"""

from __future__ import annotations

import pytest

from app.routing.engine import (
    ActionError,
    ActionRegistry,
    ActionSpec,
    DataType,
    NullAssistant,
    Param,
    ProposedAction,
    propose_bounded,
)

# --- boundary: the engine imports nothing app-specific --------------------


def test_engine_does_not_import_app_specific_modules():
    """A fresh import of the engine must not transitively pull in app.models,
    sqlalchemy, or fastapi. This is what guarantees extractability."""
    import importlib
    import sys

    # Drop any already-imported engine submodules so we measure a clean import.
    for name in list(sys.modules):
        if name == "app.routing" or name.startswith("app.routing."):
            del sys.modules[name]

    before = set(sys.modules)
    importlib.import_module("app.routing.engine")
    newly = set(sys.modules) - before

    forbidden = {"app.models", "sqlalchemy", "fastapi"}
    leaked = {m for m in newly if m in forbidden or m.split(".")[0] in forbidden}
    assert not leaked, f"engine leaked app-specific imports: {leaked}"


# --- generic registry: register / validate / dispatch ---------------------


def _registry() -> ActionRegistry:
    def _apply_echo(context, params) -> str:
        # context is opaque to the engine; here it's just a dict the test injects.
        return f"echo {params['msg']} for {context['who']}"

    return ActionRegistry(
        [
            ActionSpec(
                name="echo",
                description="Echo a message.",
                params=[Param("msg", DataType.STRING, required=True)],
                apply=_apply_echo,
                describe=lambda p: f"Echo {p.get('msg', '?')}",
            ),
            ActionSpec(
                name="noop",
                target_type=None,
                logs=False,
                apply=lambda c, p: "ok",
                describe=lambda p: "Do nothing",
            ),
        ]
    )


def test_dispatch_validates_and_calls_handler_with_opaque_context():
    reg = _registry()
    out = reg.dispatch("echo", {"msg": "hi"}, context={"who": "tester"})
    assert out == "echo hi for tester"


def test_dispatch_unknown_action_raises():
    reg = _registry()
    with pytest.raises(ActionError):
        reg.dispatch("frobnicate", {}, context={})


def test_dispatch_missing_required_param_raises():
    reg = _registry()
    with pytest.raises(ActionError):
        reg.dispatch("echo", {}, context={"who": "x"})


# --- ActionSpec.execute: the spec owns validate + apply -------------------


def test_spec_execute_validates_then_applies():
    spec = ActionSpec(
        name="echo",
        params=[Param("msg", DataType.STRING, required=True)],
        apply=lambda ctx, p: f"echo {p['msg']} for {ctx['who']}",
    )
    assert spec.execute({"msg": "hi"}, {"who": "t"}) == "echo hi for t"


def test_spec_execute_raises_on_missing_required_param():
    spec = ActionSpec(
        name="echo",
        params=[Param("msg", DataType.STRING, required=True)],
        apply=lambda ctx, p: "unused",
    )
    with pytest.raises(ActionError):
        spec.execute({}, context={})


def test_describe_uses_the_spec_and_falls_back_to_name():
    reg = _registry()
    assert reg.describe("echo", {"msg": "yo"}) == "Echo yo"
    assert reg.describe("unknown", {}) == "unknown"  # display-only, never raises


def test_registry_names():
    reg = _registry()
    assert set(reg.names()) == {"echo", "noop"}


def test_registry_get_returns_spec_or_none():
    reg = _registry()
    assert reg.get("echo") is not None
    assert reg.get("nope") is None


# --- Param + ActionSpec: derived required, prompt_line, registry.all() -----


def test_required_is_derived_from_params():
    spec = ActionSpec(
        name="x",
        params=[
            Param("a", DataType.STRING, required=True),
            Param("b", DataType.STRING),  # optional
            Param("c", DataType.DATETIME, required=True),
        ],
    )
    assert spec.required == ["a", "c"]  # order preserved; optionals excluded


def test_registry_built_from_flat_list_keys_by_spec_name():
    reg = ActionRegistry(
        [
            ActionSpec(name="solo", apply=lambda c, p: "ok"),
            ActionSpec(name="duo", apply=lambda c, p: "ok"),
        ]
    )
    assert reg.get("solo") is not None and reg.get("duo") is not None
    assert set(reg.names()) == {"solo", "duo"}


def test_registry_all_returns_specs_in_registration_order():
    reg = _registry()
    names = [s.name for s in reg.all()]
    assert names == ["echo", "noop"]


def test_prompt_line_renders_name_description_and_params():
    spec = ActionSpec(
        name="set_due_date",
        description="Set a work item's due date.",
        params=[Param("due_at", DataType.DATETIME, required=True)],
    )
    line = spec.prompt_line
    assert line == (
        "- set_due_date: Set a work item's due date. — params: due_at: datetime"
    )


def test_prompt_line_marks_optional_params_with_question_mark():
    spec = ActionSpec(
        name="create_work_item",
        description="Create a work item.",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("description", DataType.STRING),
        ],
    )
    line = spec.prompt_line
    assert "title: string" in line
    assert "description: string?" in line  # optional marked


def test_prompt_line_no_params():
    spec = ActionSpec(name="no_action", description="Nothing to suggest.")
    assert spec.prompt_line == "- no_action: Nothing to suggest. — params: (no params)"


def test_prompt_line_renders_exclusive_params_clause():
    spec = ActionSpec(
        name="create_event",
        description="Create an event.",
        params=[
            Param("start_at", DataType.DATETIME),
            Param("end_at", DataType.DATETIME),
            Param("start_date", DataType.DATE),
            Param("end_date", DataType.DATE),
        ],
        exclusive_params=[["start_at", "end_at"], ["start_date", "end_date"]],
    )
    line = spec.prompt_line
    assert "(exactly one of: {start_at, end_at} OR {start_date, end_date})" in line


# --- ProposedAction is a plain domain-free record -------------------------


def test_proposed_action_is_domain_free():
    a = ProposedAction(name="echo", params={"msg": "hi"})
    assert a.name == "echo" and a.params == {"msg": "hi"}
    assert a.target_id is None and a.target_type is None
    assert a.proposal_id == "" and a.target_ref is None


# --- propose_bounded: timeout / graceful-degrade wrapper ------------------


def test_propose_bounded_returns_actions_from_a_client():
    class OneAction(NullAssistant):
        def propose(self, ctx):
            return [ProposedAction(name="echo", params={"msg": "hi"})]

    out = propose_bounded(OneAction(), ctx=object(), timeout=2.0)
    assert [a.name for a in out] == ["echo"]


def test_propose_bounded_degrades_to_empty_on_error():
    class Boom(NullAssistant):
        def propose(self, ctx):
            raise RuntimeError("model exploded")

    assert propose_bounded(Boom(), ctx=object(), timeout=2.0) == []


def test_propose_bounded_null_client_returns_empty():
    assert propose_bounded(NullAssistant(), ctx=object(), timeout=2.0) == []

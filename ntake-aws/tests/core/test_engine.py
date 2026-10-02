"""The generic engine contract: registry, ActionSpec, DataType, propose_bounded.

Infra-free by construction — a fake handler + a plain-dict opaque context, zero
DTOs. Re-expressed from ``main:tests/assistant/test_engine.py`` against
``core.engine.engine`` (the import-boundary half of that old file now lives in
``tests/test_boundary.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from core.engine.engine import (
    ActionContext,
    ActionError,
    ActionRegistry,
    ActionSpec,
    DataType,
    NullAssistant,
    Param,
    ProposedAction,
    propose_bounded,
    require_params,
)

# --- generic registry: register / validate / dispatch ---------------------


def _registry() -> ActionRegistry[Any]:
    def _apply_echo(context: dict, params: dict) -> str:
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


def test_dispatch_validates_and_calls_handler_with_opaque_context() -> None:
    reg = _registry()
    assert reg.dispatch("echo", {"msg": "hi"}, context={"who": "t"}) == "echo hi for t"


def test_dispatch_unknown_action_raises() -> None:
    with pytest.raises(ActionError):
        _registry().dispatch("frobnicate", {}, context={})


def test_dispatch_missing_required_param_raises() -> None:
    with pytest.raises(ActionError):
        _registry().dispatch("echo", {}, context={"who": "x"})


def test_describe_uses_the_spec_and_falls_back_to_name() -> None:
    reg = _registry()
    assert reg.describe("echo", {"msg": "yo"}) == "Echo yo"
    assert reg.describe("unknown", {}) == "unknown"  # display-only, never raises


def test_describe_falls_back_when_spec_has_no_describe() -> None:
    reg: ActionRegistry[Any] = ActionRegistry(
        [ActionSpec(name="bare", apply=lambda c, p: "ok")]
    )
    assert reg.describe("bare", {}) == "bare"


def test_registry_names_get_and_all_order() -> None:
    reg = _registry()
    assert set(reg.names()) == {"echo", "noop"}
    assert reg.get("echo") is not None
    assert reg.get("nope") is None
    assert [s.name for s in reg.all()] == ["echo", "noop"]


# --- ActionSpec.execute: the spec owns validate + apply -------------------


def test_spec_execute_validates_then_applies() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="echo",
        params=[Param("msg", DataType.STRING, required=True)],
        apply=lambda ctx, p: f"echo {p['msg']} for {ctx['who']}",
    )
    assert spec.execute({"msg": "hi"}, {"who": "t"}) == "echo hi for t"


def test_spec_execute_raises_on_missing_required_param() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="echo",
        params=[Param("msg", DataType.STRING, required=True)],
        apply=lambda ctx, p: "unused",
    )
    with pytest.raises(ActionError):
        spec.execute({}, context={})


def test_require_params_raises_on_empty_string() -> None:
    with pytest.raises(ActionError):
        require_params({"k": ""}, ["k"])
    require_params({"k": "v"}, ["k"])  # no raise


# --- accepts: non-raising drop-invalid validation -------------------------


def test_accepts_checks_required_params() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="echo", params=[Param("msg", DataType.STRING, required=True)]
    )
    assert spec.accepts({"msg": "hi"}) is True
    assert spec.accepts({}) is False
    assert spec.accepts({"msg": ""}) is False


def test_accepts_exclusive_groups_need_exactly_one_anchor() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="ev",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("timed_start", DataType.DATETIME),
            Param("timed_end", DataType.DATETIME),
            Param("date_start", DataType.DATE),
            Param("date_end", DataType.DATE),
        ],
        exclusive_params=[["timed_start", "timed_end"], ["date_start", "date_end"]],
    )
    assert spec.accepts({"title": "t", "timed_start": "x"}) is True
    assert spec.accepts({"title": "t", "date_start": "d"}) is True
    assert spec.accepts({"title": "t"}) is False
    assert spec.accepts({"title": "t", "timed_start": "x", "date_start": "d"}) is False
    assert spec.accepts({"timed_start": "x"}) is False  # required still enforced


def test_accepts_true_when_no_params_and_no_groups() -> None:
    assert ActionSpec(name="noop").accepts({}) is True


# --- Param / ActionSpec derived fields + prompt_line ----------------------


def test_required_is_derived_from_params() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="x",
        params=[
            Param("a", DataType.STRING, required=True),
            Param("b", DataType.STRING),
            Param("c", DataType.DATETIME, required=True),
        ],
    )
    assert spec.required == ["a", "c"]


def test_needs_target_is_derived_from_target_type() -> None:
    assert ActionSpec(name="x", target_type=None).needs_target is False
    assert ActionSpec(name="x", target_type="work_item").needs_target is True


def test_prompt_line_renders_name_description_and_params() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="schedule",
        description="Schedule an instant.",
        params=[Param("timestamp", DataType.DATETIME, required=True)],
    )
    assert spec.prompt_line == (
        "- schedule: Schedule an instant. — params: timestamp: datetime"
    )


def test_prompt_line_marks_optional_params_and_handles_none() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="create_work_item",
        description="Create a work item.",
        params=[
            Param("title", DataType.STRING, required=True),
            Param("description", DataType.STRING),
        ],
    )
    line = spec.prompt_line
    assert "title: string" in line and "description: string?" in line

    bare: ActionSpec[Any] = ActionSpec(
        name="no_action", description="Nothing to suggest."
    )
    assert bare.prompt_line == "- no_action: Nothing to suggest. — params: (no params)"


def test_prompt_line_renders_exclusive_params_clause() -> None:
    spec: ActionSpec[Any] = ActionSpec(
        name="create_event",
        description="Create an event.",
        params=[
            Param("timed_start", DataType.DATETIME),
            Param("timed_end", DataType.DATETIME),
            Param("date_start", DataType.DATE),
            Param("date_end", DataType.DATE),
        ],
        exclusive_params=[["timed_start", "timed_end"], ["date_start", "date_end"]],
    )
    assert (
        "(exactly one of: {timed_start, timed_end} OR {date_start, date_end})"
        in spec.prompt_line
    )


# --- DataType: both projections -------------------------------------------


def test_datatype_exposes_human_token_and_json_schema() -> None:
    assert DataType.STRING.human_token == "string"
    assert DataType.STRING.json_schema == {"type": "string"}
    assert DataType.ARRAY_STRING.human_token == "array<string>"
    assert DataType.ARRAY_STRING.json_schema == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert DataType.DATETIME.json_schema == {"type": "string", "format": "date-time"}


# --- render_card: optional pure renderer ----------------------------------


def test_render_card_default_none_and_pure_when_set() -> None:
    assert ActionSpec(name="x", description="X").render_card is None
    spec: ActionSpec[Any] = ActionSpec(
        name="assign",
        description="Assign it.",
        render_card=lambda params, resolved: [
            f"To: {resolved.get('member_names', {}).get(params.get('member_id'))}"
        ],
    )
    assert spec.render_card is not None
    assert spec.render_card({"member_id": 2}, {"member_names": {2: "Sam"}}) == [
        "To: Sam"
    ]


# --- ProposedAction is a plain, infra-free record -------------------------


def test_proposed_action_is_domain_free() -> None:
    a = ProposedAction(name="echo", params={"msg": "hi"})
    assert a.name == "echo" and a.params == {"msg": "hi"}
    assert a.target_id is None and a.target_type is None
    assert a.proposal_id == "" and a.target_ref is None


# --- propose_bounded: timeout / graceful-degrade wrapper ------------------


def test_propose_bounded_returns_actions_from_a_client() -> None:
    class OneAction(NullAssistant):
        def propose(self, ctx: ActionContext) -> list[ProposedAction]:
            return [ProposedAction(name="echo", params={"msg": "hi"})]

    out = propose_bounded(OneAction(), ctx=ActionContext(), timeout=2.0)
    assert [a.name for a in out] == ["echo"]


def test_propose_bounded_degrades_to_empty_on_error() -> None:
    class Boom(NullAssistant):
        def propose(self, ctx: ActionContext) -> list[ProposedAction]:
            raise RuntimeError("model exploded")

    assert propose_bounded(Boom(), ctx=ActionContext(), timeout=2.0) == []


def test_propose_bounded_null_client_returns_empty() -> None:
    assert propose_bounded(NullAssistant(), ctx=ActionContext(), timeout=2.0) == []

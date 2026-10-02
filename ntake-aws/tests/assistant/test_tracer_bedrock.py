"""Bedrock tracer tests (Session 1.5) — toolConfig + response-shape logic.

Covers the pure helpers that build the hand-written 2-tool ``toolConfig`` and
reduce a Converse response to the §3.5 findings (multi-``toolUse`` count, enum
adherence). The real ``Converse`` call is deployed-only; here we feed the
summarizer **scripted** Converse responses (via the harness ``propose_response``
helper) with one and with multiple ``toolUse`` blocks, proving the summarizer
reports the questions correctly whatever the real model turns out to do.
"""

from __future__ import annotations

from tests.harness.bedrock_double import propose_response
from tracer.bedrock_tracer import (
    WHITELIST_MEMBER_IDS,
    build_tool_config,
    parse_tool_uses,
    summarize,
)


def test_tool_config_has_two_tools_plus_no_action() -> None:
    cfg = build_tool_config(WHITELIST_MEMBER_IDS)
    names = [t["toolSpec"]["name"] for t in cfg["tools"]]
    assert names == ["flag_blocked", "set_due_date", "no_action"]


def test_tool_config_forces_a_tool_choice() -> None:
    cfg = build_tool_config(WHITELIST_MEMBER_IDS)
    assert cfg["toolChoice"] == {"any": {}}


def test_id_param_is_enum_over_whitelist() -> None:
    cfg = build_tool_config(["MEM#x", "MEM#y"])
    member_schema = cfg["tools"][0]["toolSpec"]["inputSchema"]["json"]["properties"][
        "member_id"
    ]
    assert member_schema == {"type": "string", "enum": ["MEM#x", "MEM#y"]}


def test_parse_extracts_tool_uses_in_order() -> None:
    resp = propose_response(
        [
            {"name": "flag_blocked", "input": {"member_id": "MEM#sam"}},
            {"name": "set_due_date", "input": {"member_id": "MEM#alex"}},
        ]
    )
    uses = parse_tool_uses(resp)
    assert [u["name"] for u in uses] == ["flag_blocked", "set_due_date"]


def test_summarize_single_tool_use() -> None:
    resp = propose_response(
        [{"name": "flag_blocked", "input": {"member_id": "MEM#sam", "reason": "x"}}]
    )
    out = summarize(resp, WHITELIST_MEMBER_IDS)
    assert out["tool_use_count"] == 1
    assert out["multiple_tool_uses_in_one_turn"] is False
    assert out["tools_chosen"] == ["flag_blocked"]
    assert out["enum_respected"] is True


def test_summarize_multiple_tool_uses_in_one_turn() -> None:
    due = {"member_id": "MEM#alex", "due_date": "x"}
    resp = propose_response(
        [
            {"name": "flag_blocked", "input": {"member_id": "MEM#sam", "reason": "x"}},
            {"name": "set_due_date", "input": due},
        ]
    )
    out = summarize(resp, WHITELIST_MEMBER_IDS)
    assert out["tool_use_count"] == 2
    assert out["multiple_tool_uses_in_one_turn"] is True


def test_summarize_flags_enum_violation() -> None:
    # If the model ever returns an id outside the whitelist, enum_respected is False.
    resp = propose_response(
        [{"name": "flag_blocked", "input": {"member_id": "MEM#intruder"}}]
    )
    out = summarize(resp, WHITELIST_MEMBER_IDS)
    assert out["chosen_member_ids"] == ["MEM#intruder"]
    assert out["enum_respected"] is False


def test_summarize_no_action_has_no_member_ids() -> None:
    resp = propose_response([{"name": "no_action", "input": {}}])
    out = summarize(resp, WHITELIST_MEMBER_IDS)
    assert out["tools_chosen"] == ["no_action"]
    assert out["chosen_member_ids"] == []
    assert out["enum_respected"] is True

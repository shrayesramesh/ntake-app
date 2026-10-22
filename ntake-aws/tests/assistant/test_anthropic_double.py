"""The scripted Anthropic double — real Messages shape, no network (AWS_LLD §3.4).

Pins the double to the **real** Anthropic Messages response shape verified by
``scripts/spike/link_probe.py``: a top-level ``content`` list; a tool call is
``{"type":"tool_use","id","name","input":{...}}``; ``stop_reason`` is
``"tool_use"`` / ``"end_turn"``. The double satisfies the ``AnthropicClient``
protocol and returns canned responses keyed by a substring of the user text, so
LINK/PROPOSE flows run deterministically with no key and no network.
"""

from __future__ import annotations

import pytest

from core.assistant.anthropic_client import AnthropicClient
from tests.harness.anthropic_double import (
    ScriptedAnthropicClient,
    link_response,
    propose_response,
)


def _user(text: str) -> list[dict]:
    """A Messages user turn carrying one text block."""
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


def test_link_response_is_a_forced_tool_use_block() -> None:
    resp = link_response({"work_item_ids": ["w1"], "member_ids": ["m2"]})
    assert resp["stop_reason"] == "tool_use"
    (block,) = resp["content"]
    assert block["type"] == "tool_use"
    assert block["name"] == "record_links"
    # defaults filled for the unspecified id lists
    assert block["input"] == {
        "work_item_ids": ["w1"],
        "event_ids": [],
        "member_ids": ["m2"],
    }


def test_propose_response_one_tool_use_block_per_call() -> None:
    resp = propose_response(
        [
            {"name": "flag_blocked", "input": {}},
            {"name": "set_due_date", "input": {"due": "2026-09-05"}},
        ]
    )
    assert resp["stop_reason"] == "tool_use"
    blocks = resp["content"]
    assert [b["type"] for b in blocks] == ["tool_use", "tool_use"]
    assert [b["name"] for b in blocks] == ["flag_blocked", "set_due_date"]
    assert blocks[1]["input"] == {"due": "2026-09-05"}
    # each block gets a stable id
    assert all(b.get("id") for b in blocks)


def test_scripted_client_satisfies_protocol() -> None:
    client = ScriptedAnthropicClient(default=propose_response([{"name": "no_action"}]))
    assert isinstance(client, AnthropicClient)


def test_scripted_client_keys_response_off_user_text() -> None:
    client = ScriptedAnthropicClient(
        responses={
            "plumber": link_response({"work_item_ids": ["w2"]}),
            "dentist": link_response({"event_ids": ["e3"]}),
        }
    )
    resp = client.create_message("sys", _user("the plumber is coming"))
    (block,) = resp["content"]
    assert block["input"]["work_item_ids"] == ["w2"]


def test_scripted_client_records_calls() -> None:
    client = ScriptedAnthropicClient(default=link_response({}))
    client.create_message(
        "sysprompt",
        _user("hi"),
        tools=[{"name": "record_links"}],
        tool_choice={"type": "tool", "name": "record_links"},
    )
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call.system == "sysprompt"
    assert call.tool_choice == {"type": "tool", "name": "record_links"}


def test_scripted_client_miss_without_default_raises() -> None:
    client = ScriptedAnthropicClient(responses={"groceries": link_response({})})
    with pytest.raises(KeyError, match="no canned response matched"):
        client.create_message("sys", _user("nope"))


def test_scripted_client_returns_deep_copies() -> None:
    canned = link_response({"work_item_ids": ["w1"]})
    client = ScriptedAnthropicClient(responses={"note": canned})
    r1 = client.create_message("s", _user("note"))
    r1["content"][0]["input"]["work_item_ids"].append("MUTATED")
    r2 = client.create_message("s", _user("note"))
    assert r2["content"][0]["input"]["work_item_ids"] == ["w1"]  # not poisoned

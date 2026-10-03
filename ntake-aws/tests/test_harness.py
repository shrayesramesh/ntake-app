"""Self-tests for the shared test harness (tests/harness/ + conftest fixtures).

The harness is the DRY backbone Sessions 2-9 import, so it is itself real
functionality worth testing. Covers: the scripted Bedrock Converse double
(LINK + PROPOSE shapes, substring keying, deep-copy isolation, call recording),
the parametrized ``repo`` fixture, the DynamoDB-Local probe, and the boundary
assertion helper.
"""

from __future__ import annotations

import pytest

from core.repository import Repository
from core.repository_memory import InMemoryRepository
from tests.harness.bedrock_double import (
    ScriptedBedrockClient,
    link_response,
    propose_response,
)
from tests.harness.boundary import assert_imports_none_of
from tests.harness.ddb_local import dynamodb_local_available

# --- scripted Bedrock double ----------------------------------------------


def _user(text: str) -> list[dict]:
    return [{"role": "user", "content": [{"text": text}]}]


def test_link_response_shape_defaults_and_merge() -> None:
    import json

    resp = link_response({"member_ids": ["MEM#1"]})
    block = resp["output"]["message"]["content"][0]
    payload = json.loads(block["text"])
    assert payload == {"work_item_ids": [], "event_ids": [], "member_ids": ["MEM#1"]}
    assert resp["stopReason"] == "end_turn"


def test_propose_response_one_block_per_tool_use() -> None:
    resp = propose_response(
        [
            {"name": "set_due_date", "input": {"local_due_at": "2025-01-02T09:00"}},
            {"name": "no_action", "input": {}},
        ]
    )
    content = resp["output"]["message"]["content"]
    assert resp["stopReason"] == "tool_use"
    assert [b["toolUse"]["name"] for b in content] == ["set_due_date", "no_action"]
    assert content[0]["toolUse"]["toolUseId"] == "tu-0"


def test_scripted_client_keys_off_user_substring() -> None:
    client = ScriptedBedrockClient(
        responses={
            "groceries": link_response({"work_item_ids": ["WI#1"]}),
            "dentist": link_response({"event_ids": ["EV#9"]}),
        }
    )
    import json

    out = client.converse("sys", _user("add milk to the groceries list"))
    payload = json.loads(out["output"]["message"]["content"][0]["text"])
    assert payload["work_item_ids"] == ["WI#1"]


def test_scripted_client_default_and_miss_raises() -> None:
    with_default = ScriptedBedrockClient(
        default=propose_response([{"name": "no_action"}])
    )
    assert with_default.converse("s", _user("anything"))["stopReason"] == "tool_use"

    no_default = ScriptedBedrockClient(responses={"groceries": link_response({})})
    with pytest.raises(KeyError):
        no_default.converse("s", _user("unmatched text"))


def test_scripted_client_records_calls_and_isolates_copies() -> None:
    canned = link_response({"work_item_ids": ["WI#1"]})
    client = ScriptedBedrockClient(responses={"note": canned})
    tool_config: dict = {"tools": []}
    first = client.converse("sys", _user("a note"), tool_config)
    # Mutating the returned dict must not poison the next call (deep copy).
    first["output"]["message"]["content"].clear()
    second = client.converse("sys", _user("a note"))
    assert second["output"]["message"]["content"]  # intact
    assert len(client.calls) == 2
    assert client.calls[0] == ("sys", _user("a note"), tool_config)


# --- repo fixture (parametrized over both backends) -----------------------


def test_repo_fixture_yields_a_backend(repo: object) -> None:
    # In Session 2 only the ``memory`` param runs (``dynamo`` is skipped); it
    # yields the real InMemoryRepository, which structurally satisfies the
    # Repository protocol — the parametrization is demonstrably live.
    assert isinstance(repo, InMemoryRepository)
    assert isinstance(repo, Repository)


# --- DynamoDB Local probe + boundary helper -------------------------------


def test_dynamodb_local_probe_returns_bool() -> None:
    assert isinstance(dynamodb_local_available(), bool)


def test_boundary_helper_passes_for_a_clean_target() -> None:
    # The harness's own boundary module imports no infra packages.
    assert_imports_none_of("tests.harness.boundary", {"boto3", "sqlalchemy", "fastapi"})

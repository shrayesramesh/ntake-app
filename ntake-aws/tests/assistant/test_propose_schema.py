"""PROPOSE schema translation — registry → Anthropic ``tools`` (AWS_LLD §3.3).

Piece 1 of the §3.6 split: the pure projection ``build_tools_schema``. One tool
per registered action; ``input_schema`` assembled from ``params`` (required
derived, exclusive groups → ``oneOf``); the per-request id-enum overlay on
``member_id``; and the empty-whitelist tool-omission rule (§3.2).
"""

from __future__ import annotations

from core.actions.registry import REGISTRY
from core.assistant.anthropic_propose import build_tools_schema
from core.engine.engine import ActionRegistry, ActionSpec, DataType, Param


def _by_name(tools: list[dict]) -> dict[str, dict]:
    return {t["name"]: t for t in tools}


# --- one tool per action, carrying name + description + input_schema --------


def test_projects_every_action_to_a_tool() -> None:
    # No id params in the whitelist -> member_id tools omitted; use a non-empty
    # whitelist so the full registry projects.
    tools = build_tools_schema(REGISTRY, {"member_id": ["m1"]})
    names = {t["name"] for t in tools}
    assert names == set(REGISTRY.names())
    for tool in tools:
        assert set(tool) == {"name", "description", "input_schema"}
        assert tool["description"]  # non-empty sentence from the spec
        assert tool["input_schema"]["type"] == "object"
        assert tool["input_schema"]["additionalProperties"] is False


def test_required_is_derived_from_params() -> None:
    tools = _by_name(build_tools_schema(REGISTRY, {"member_id": ["m1"]}))
    # create_timed_event requires title + both times.
    schema = tools["create_timed_event"]["input_schema"]
    assert set(schema["required"]) == {"title", "local_start_at", "local_end_at"}
    # a param-less action has no "required" key at all.
    assert "required" not in tools["no_action"]["input_schema"]


def test_param_fragments_come_from_the_datatype() -> None:
    tools = _by_name(build_tools_schema(REGISTRY, {"member_id": ["m1"]}))
    props = tools["create_timed_event"]["input_schema"]["properties"]
    assert props["title"] == {"type": "string"}
    # LOCAL_DATETIME carries its description fragment verbatim.
    assert props["local_start_at"] == DataType.LOCAL_DATETIME.json_schema
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}


# --- exclusive param groups -> oneOf ---------------------------------------


def test_exclusive_params_become_oneof() -> None:
    # The live registry has no exclusive-group action, so build a tiny registry.
    spec: ActionSpec = ActionSpec(
        name="toy",
        description="toy",
        params=[
            Param("a", DataType.STRING),
            Param("b", DataType.STRING),
        ],
        exclusive_params=[["a"], ["b"]],
    )
    tools = build_tools_schema(ActionRegistry([spec]), {})
    schema = tools[0]["input_schema"]
    assert schema["oneOf"] == [{"required": ["a"]}, {"required": ["b"]}]


# --- id-enum overlay on member_id ------------------------------------------


def test_member_id_is_constrained_to_the_whitelist_enum() -> None:
    tools = _by_name(build_tools_schema(REGISTRY, {"member_id": ["m1", "m2"]}))
    member_prop = tools["assign_work_item"]["input_schema"]["properties"]["member_id"]
    assert member_prop == {"type": "string", "enum": ["m1", "m2"]}


# --- empty-whitelist edge: omit id-bearing tools (§3.2) --------------------


def test_empty_member_whitelist_omits_the_member_tool_but_keeps_the_rest() -> None:
    tools = build_tools_schema(REGISTRY, {"member_id": []})
    names = {t["name"] for t in tools}
    # assign_work_item requires member_id, whose whitelist is empty -> omitted.
    assert "assign_work_item" not in names
    # no_action and no-target creates survive — a degraded LINK still lands.
    assert "no_action" in names
    assert "create_work_item" in names
    assert "create_timed_event" in names

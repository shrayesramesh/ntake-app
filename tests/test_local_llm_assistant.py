"""LocalLlmAssistant — the PROPOSE call (LLM call 2), step 4.

Stage-2 sibling of ``FakeAssistant``, but model-backed: it builds the propose
prompt (``build_propose_prompt``) + the constrained schema
(``build_tools_schema``), calls the injected ``LLM`` seam, then parses the reply,
validates each tool call against the registry, and attaches the server-known
target — returning ``[ProposedAction]``. Tested with a hand-built deep
``FocusedContext`` + a ``ScriptedLLM`` (no link/DB needed): the model output is
canned, so these pin parse + validate + attach, not model quality.

Attach rule (LLD OQ-4, v1): the model emits id-free ``{name, params}``; the
server stamps the target from the resolved ids in the context — type-based, ≤1
resolved entity per type. Actions that ``needs_target`` get the primary work-item
id, except the event-targeting actions which get the primary event id; creators /
no_action get no target.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.capture import FocusedContext, ProposedAction
from app.assistant.local_llm.assistant import LocalLlmAssistant
from app.assistant.local_llm.protocol import ScriptedLLM
from app.routing.engine import AssistantClient

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _ctx(
    text: str = "note",
    work_item_id: int | None = None,
    event_id: int | None = None,
    deep: str = "CONTEXT",
) -> FocusedContext:
    return FocusedContext(
        text=text,
        timezone="America/New_York",
        now=NOW,
        deep_context=deep,
        resolved_work_item_ids=[work_item_id] if work_item_id is not None else [],
        resolved_event_ids=[event_id] if event_id is not None else [],
    )


def _assistant(actions: list[dict]) -> LocalLlmAssistant:
    """A LocalLlmAssistant whose LLM returns the given canned actions envelope."""
    return LocalLlmAssistant(ScriptedLLM(default={"actions": actions}))


def test_is_an_assistant_client():
    assert isinstance(_assistant([]), AssistantClient)


def test_proposes_a_create_work_item_with_no_target():
    a = _assistant([{"name": "create_work_item", "params": {"title": "buy stamps"}}])
    out = a.propose(_ctx("buy stamps"))
    assert len(out) == 1
    p = out[0]
    assert isinstance(p, ProposedAction)
    assert p.name == "create_work_item"
    assert p.params == {"title": "buy stamps"}
    # A creator needs no target.
    assert p.target_id is None
    assert p.target_type is None


def test_attaches_work_item_target_for_a_targeting_action():
    a = _assistant(
        [{"name": "set_due_date", "params": {"due_at": "2026-09-05T19:00:00Z"}}]
    )
    out = a.propose(_ctx("due friday", work_item_id=7))
    assert out[0].target_type == "work_item"
    assert out[0].target_id == 7


def test_attaches_event_target_for_an_event_action():
    a = _assistant(
        [{"name": "reschedule_event", "params": {"start_at": "2026-09-05T19:00:00Z"}}]
    )
    out = a.propose(_ctx("move it", event_id=42))
    assert out[0].target_type == "event"
    assert out[0].target_id == 42


def test_create_event_is_a_creator_passing_event_params_through_no_target():
    # create_event does NOT operate on an existing entity — the event it creates
    # is fully specified by its params (title + a timing one-of), not a target.
    # So the assistant passes the params through and attaches NO target, even
    # when the context has a resolved work item (a creator never auto-attaches).
    a = _assistant(
        [
            {
                "name": "create_event",
                "params": {
                    "title": "Dentist",
                    "start_at": "2026-09-04T19:00:00Z",
                    "end_at": "2026-09-04T20:00:00Z",
                },
            }
        ]
    )
    out = a.propose(_ctx("dentist appointment friday", work_item_id=9))
    assert len(out) == 1
    p = out[0]
    assert p.name == "create_event"
    # The event timing params the model supplied flow through unchanged…
    assert p.params == {
        "title": "Dentist",
        "start_at": "2026-09-04T19:00:00Z",
        "end_at": "2026-09-04T20:00:00Z",
    }
    # …and no target is attached (creator), despite the resolved work item.
    assert p.target_id is None
    assert p.target_type is None


def test_create_event_timing_contract_is_expressed_in_the_tools_schema():
    # How the model is TOLD it must supply an event's timing when it picks
    # create_event: via the action's params one-of in the constrained schema
    # (not via target_type). Pin that linkage here.
    from app.assistant.actions import REGISTRY
    from app.assistant.local_llm.tools_schema import build_tools_schema

    schema = build_tools_schema(REGISTRY)
    create_event = next(
        b
        for b in schema["properties"]["actions"]["items"]["oneOf"]
        if b["properties"]["name"]["const"] == "create_event"
    )
    params = create_event["properties"]["params"]
    assert params["required"] == ["title"]
    assert params["oneOf"] == [
        {"required": ["title", "start_at", "end_at"]},
        {"required": ["title", "start_date", "end_date"]},
    ]


def test_builds_prompt_and_schema_and_sends_them_to_the_llm():
    llm = ScriptedLLM(default={"actions": []})
    LocalLlmAssistant(llm).propose(_ctx("the note text", deep="DEEP CONTEXT HERE"))
    # One call was made; assert the prompt carried the tools view + deep context +
    # note, and the schema is the constrained-output envelope.
    assert len(llm.calls) == 1
    system, user, schema = llm.calls[0]
    assert "AVAILABLE TOOLS:" in user
    assert "DEEP CONTEXT HERE" in user
    assert "the note text" in user
    assert "household assistant" in system.lower()
    # The schema is the real tools schema envelope.
    assert schema["properties"]["actions"]["type"] == "array"


def test_multiple_actions_are_all_returned_and_attached():
    a = _assistant(
        [
            {"name": "set_due_date", "params": {"due_at": "2026-09-05T19:00:00Z"}},
            {"name": "complete_work_item", "params": {}},
        ]
    )
    out = a.propose(_ctx("done, due friday", work_item_id=3))
    assert [p.name for p in out] == ["set_due_date", "complete_work_item"]
    assert all(p.target_type == "work_item" and p.target_id == 3 for p in out)


def test_no_actions_yields_empty_list():
    assert _assistant([]).propose(_ctx("nothing")) == []


# --- parse tolerance (the branches introduced here; step 6 hardens further) ---


def test_missing_or_non_list_actions_yields_empty():
    # Reply without an actions array, or with a non-list value, degrades to [].
    assert LocalLlmAssistant(ScriptedLLM(default={})).propose(_ctx("x")) == []
    assert (
        LocalLlmAssistant(ScriptedLLM(default={"actions": "nope"})).propose(_ctx("x"))
        == []
    )


def test_malformed_entries_are_dropped():
    # Non-dict entry, non-string name, and non-dict params are each dropped; the
    # one well-formed call survives.
    a = _assistant(
        [
            "not a dict",
            {"name": 123, "params": {}},
            {"name": "complete_work_item", "params": "not a dict"},
            {"name": "create_work_item", "params": {"title": "ok"}},
        ]
    )
    out = a.propose(_ctx("mix", work_item_id=1))
    assert [p.name for p in out] == ["create_work_item"]


def test_unknown_action_name_is_dropped():
    a = _assistant([{"name": "frobnicate", "params": {}}])
    assert a.propose(_ctx("x")) == []


def test_params_defaults_to_empty_dict_when_omitted():
    # A call omitting params entirely still parses (params -> {}).
    a = _assistant([{"name": "complete_work_item"}])
    out = a.propose(_ctx("done", work_item_id=5))
    assert out[0].name == "complete_work_item"
    assert out[0].params == {}

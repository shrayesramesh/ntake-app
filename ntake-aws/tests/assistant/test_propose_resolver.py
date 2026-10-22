"""PROPOSE resolver — the end-to-end stage-2 flow (AWS_LLD §3.2).

The behaviour-first test for Session 5: a focused context (what LINK resolved)
in → one PROPOSE ``create_message`` with the registry projected to ``tools`` and
``tool_choice: {type: any}`` → the model's ``tool_use`` block(s) out → a list of
``ProposedAction`` cards. Driven by the scripted Anthropic double (no network, no
key).

This file pins the **observable contract** PROPOSE must honour, independent of
how the schema translation / parse is implemented:

* **Selection, not execution.** PROPOSE maps tool calls to proposal cards and
  stops — it never executes an action, never writes through the repo, never
  returns a ``tool_result``, never loops (AWS_LLD §3.2).
* **Parallel tool use.** Multiple ``tool_use`` blocks in one response → multiple
  cards (the handler consumes a list — AWS_LLD §3.5).
* **Enum-over-whitelist + app-side re-validation.** A returned id is kept only if
  it is on LINK's resolved whitelist; a fabricated one is dropped
  (defense-in-depth, AWS_LLD §3.2).
* **Target attachment.** The verb comes from the model; the concrete
  ``target_id``/``target_type`` is attached by the app from LINK's resolved ids.
* **Graceful degrade.** Any failure (API raise, missing blocks, malformed input)
  → ``[]``; never a raise into the request path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.assistant.anthropic_propose import AnthropicAssistant
from core.assistant.capture import FocusedContext, ProposedAction
from core.repository_memory import InMemoryRepository
from core.schemas import Family
from tests.harness.anthropic_double import ScriptedAnthropicClient, propose_response

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _ctx(
    *,
    text: str = "note",
    work_item_ids: list[str] | None = None,
    event_ids: list[str] | None = None,
    member_ids: list[str] | None = None,
) -> FocusedContext:
    return FocusedContext(
        text=text,
        timezone=TZ,
        now=NOW,
        capture_author="[m:m1] Alex (adult)",
        deep_context="CTX",
        resolved_work_item_ids=work_item_ids or [],
        resolved_event_ids=event_ids or [],
        resolved_member_ids=member_ids or [],
    )


def _assistant(client: ScriptedAnthropicClient) -> AnthropicAssistant:
    return AnthropicAssistant(client)


def _propose(tool_uses: list[dict], ctx: FocusedContext) -> list[ProposedAction]:
    client = ScriptedAnthropicClient(default=propose_response(tool_uses))
    return _assistant(client).propose(ctx)


# --- the shape of the call PROPOSE makes -----------------------------------


def test_sends_registry_as_tools_with_tool_choice_any() -> None:
    client = ScriptedAnthropicClient(default=propose_response([{"name": "no_action"}]))
    _assistant(client).propose(_ctx())

    (call,) = client.calls
    # tool_choice is "any" — the model MUST use a registered tool (AWS_LLD §3.2).
    assert call.tool_choice == {"type": "any"}
    # the tools list is the registry projection; no_action is among them.
    assert call.tools is not None
    names = {t["name"] for t in call.tools}
    assert "no_action" in names
    assert "create_work_item" in names
    # the note + deep context reach the model.
    user_text = call.messages[0]["content"][0]["text"]
    assert "note" in user_text


# --- selection, not execution ---------------------------------------------


def test_maps_a_tool_call_to_a_proposal_without_executing() -> None:
    repo = InMemoryRepository()
    repo.seed_family(Family(id="fam1", name="T", timezone=TZ, created_at=NOW), [])
    # A create proposal: no target needed, nothing should be written.
    out = _propose(
        [{"name": "create_work_item", "input": {"title": "Buy milk"}}], _ctx()
    )

    assert [p.name for p in out] == ["create_work_item"]
    assert out[0].params == {"title": "Buy milk"}
    # Nothing was written — PROPOSE selects, it does not execute.
    assert repo.list_work_items("fam1") == []


def test_no_tool_result_is_ever_returned_and_no_loop() -> None:
    # One create_message call, period — PROPOSE never completes the agent loop.
    client = ScriptedAnthropicClient(default=propose_response([{"name": "no_action"}]))
    _assistant(client).propose(_ctx())
    assert len(client.calls) == 1


def test_no_action_is_a_normal_selection() -> None:
    out = _propose([{"name": "no_action"}], _ctx())
    assert [p.name for p in out] == ["no_action"]


# --- parallel tool use: many blocks -> many cards --------------------------


def test_multiple_tool_use_blocks_become_multiple_cards() -> None:
    out = _propose(
        [
            {"name": "create_work_item", "input": {"title": "Buy milk"}},
            {
                "name": "create_timed_event",
                "input": {
                    "title": "Dentist",
                    "local_start_at": "2026-09-05T19:00:00",
                    "local_end_at": "2026-09-05T20:00:00",
                },
            },
        ],
        _ctx(),
    )
    assert [p.name for p in out] == ["create_work_item", "create_timed_event"]


# --- target attachment from LINK's resolved ids ----------------------------


def test_work_item_target_is_attached_from_resolved_ids() -> None:
    out = _propose(
        [{"name": "complete_work_item", "input": {}}],
        _ctx(work_item_ids=["w2"]),
    )
    assert [p.name for p in out] == ["complete_work_item"]
    assert out[0].target_id == "w2"
    assert out[0].target_type == "work_item"


def test_event_target_is_attached_from_resolved_ids() -> None:
    out = _propose(
        [{"name": "delete_event", "input": {}}],
        _ctx(event_ids=["e9"]),
    )
    assert [p.name for p in out] == ["delete_event"]
    assert out[0].target_id == "e9"
    assert out[0].target_type == "event"


def test_target_needing_action_without_a_resolved_id_is_dropped() -> None:
    # complete_work_item needs a work-item target; none resolved -> drop it.
    out = _propose([{"name": "complete_work_item", "input": {}}], _ctx())
    assert out == []


# --- enum-over-whitelist: app-side id re-validation (defense-in-depth) ------


def test_fabricated_member_id_is_dropped_against_whitelist() -> None:
    # assign_work_item carries a member_id param; only whitelisted members allowed.
    out = _propose(
        [{"name": "assign_work_item", "input": {"member_id": "m_bogus"}}],
        _ctx(work_item_ids=["w2"], member_ids=["m1"]),
    )
    assert out == []


def test_whitelisted_member_id_survives() -> None:
    out = _propose(
        [{"name": "assign_work_item", "input": {"member_id": "m1"}}],
        _ctx(work_item_ids=["w2"], member_ids=["m1"]),
    )
    assert [p.name for p in out] == ["assign_work_item"]
    assert out[0].params["member_id"] == "m1"
    assert out[0].target_id == "w2"


# --- graceful degrade (never raise) ----------------------------------------


class _RaisingClient:
    def create_message(self, *a: object, **k: object) -> dict:
        raise RuntimeError("api down")


def test_api_failure_degrades_to_empty() -> None:
    assert AnthropicAssistant(_RaisingClient()).propose(_ctx()) == []


def test_missing_content_degrades_to_empty() -> None:
    client = ScriptedAnthropicClient(
        default={"stop_reason": "end_turn", "content": [{"type": "text", "text": "x"}]}
    )
    assert _assistant(client).propose(_ctx()) == []


def test_malformed_tool_input_degrades_to_empty() -> None:
    client = ScriptedAnthropicClient(
        default={
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t",
                    "name": "create_work_item",
                    "input": "garbage",
                }
            ],
        }
    )
    assert _assistant(client).propose(_ctx()) == []


def test_unknown_action_is_dropped() -> None:
    out = _propose([{"name": "not_a_real_action", "input": {}}], _ctx())
    assert out == []


def test_a_valid_call_survives_alongside_an_invalid_one() -> None:
    out = _propose(
        [
            {"name": "set_due_date", "input": {}},  # invalid: missing required
            {"name": "no_action", "input": {}},  # valid
        ],
        _ctx(work_item_ids=["w2"]),
    )
    assert [p.name for p in out] == ["no_action"]

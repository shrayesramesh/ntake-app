"""PROPOSE parsing / graceful-degrade hardening (BUG-001..008 port).

Behaviour-faithful port of the self-hosted app's hardening suite (reference:
``git show main:tests/assistant/test_local_llm_hardening.py``), re-expressed
against the Anthropic scripted double. The request-path contract (AWS_LLD §3.2):
a bad model or bad model output must **degrade to fewer/zero proposals, never
raise**.

Per Session-5 scope (owner-confirmed): the reference's *transport*-level drops
(HTTP 4xx/5xx, timeout, non-JSON → ``{}``) targeted the old ``LocalLlmClient``.
Here the graceful-degrade boundary lives in the resolver's blanket ``except`` (as
LINK does), and the real ``HttpAnthropicClient`` is Tier-2-only — so these pin the
**parse/validate** drops at the resolver level (the resolver-raise degrade is
covered in test_propose_resolver.py).
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.assistant.anthropic_propose import AnthropicAssistant
from core.assistant.capture import FocusedContext, ProposedAction
from tests.harness.anthropic_double import ScriptedAnthropicClient, propose_response

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _ctx(
    *, work_item_id: str | None = None, event_id: str | None = None
) -> FocusedContext:
    return FocusedContext(
        text="note",
        timezone=TZ,
        now=NOW,
        deep_context="CTX",
        resolved_work_item_ids=[work_item_id] if work_item_id is not None else [],
        resolved_event_ids=[event_id] if event_id is not None else [],
    )


def _propose(tool_uses: list[dict], ctx: FocusedContext) -> list[ProposedAction]:
    client = ScriptedAnthropicClient(default=propose_response(tool_uses))
    return AnthropicAssistant(client).propose(ctx)


# --- per-spec param-contract validation drops bad calls --------------------


def test_drops_call_missing_a_required_param() -> None:
    # set_due_date requires local_due_at; a call without it is dropped.
    assert (
        _propose([{"name": "set_due_date", "input": {}}], _ctx(work_item_id="w3")) == []
    )


def test_drops_call_with_empty_required_param() -> None:
    assert (
        _propose(
            [{"name": "set_due_date", "input": {"local_due_at": ""}}],
            _ctx(work_item_id="w3"),
        )
        == []
    )


def test_keeps_call_with_required_param_present() -> None:
    out = _propose(
        [{"name": "set_due_date", "input": {"local_due_at": "2026-09-05T19:00:00"}}],
        _ctx(work_item_id="w3"),
    )
    assert [p.name for p in out] == ["set_due_date"]


def test_drops_timed_action_missing_a_required_time() -> None:
    assert (
        _propose(
            [{"name": "create_timed_event", "input": {"title": "Dentist"}}], _ctx()
        )
        == []
    )


def test_keeps_explicit_timed_action_with_complete_pair() -> None:
    out = _propose(
        [
            {
                "name": "create_timed_event",
                "input": {
                    "title": "Dentist",
                    "local_start_at": "2026-09-05T19:00:00",
                    "local_end_at": "2026-09-05T20:00:00",
                },
            }
        ],
        _ctx(),
    )
    assert [p.name for p in out] == ["create_timed_event"]


def test_a_valid_call_survives_alongside_an_invalid_one() -> None:
    out = _propose(
        [
            {"name": "set_due_date", "input": {}},  # invalid: missing due_at
            {"name": "complete_work_item", "input": {}},  # valid: no params needed
        ],
        _ctx(work_item_id="w3"),
    )
    assert [p.name for p in out] == ["complete_work_item"]


# --- explicit local weekday/time validation (BUG-002) ----------------------


def _friday_ctx(text: str) -> FocusedContext:
    return FocusedContext(
        text=text,
        timezone=TZ,
        now=datetime(2026, 9, 4, 18, 25, tzinfo=UTC),
        deep_context="CTX",
    )


def test_keeps_event_matching_explicit_weekday_and_local_time() -> None:
    out = _propose(
        [
            {
                "name": "create_timed_event",
                "input": {
                    "title": "Soccer game",
                    "local_start_at": "2026-09-09T17:00:00",
                    "local_end_at": "2026-09-09T18:00:00",
                },
            }
        ],
        _friday_ctx("soccer game Wednesday 5-6 PM"),
    )
    assert [p.name for p in out] == ["create_timed_event"]


def test_drops_utc_timed_model_values_instead_of_exposing_them() -> None:
    # A Z-suffixed (UTC) value in a family-local slot is dropped, not surfaced.
    assert (
        _propose(
            [
                {
                    "name": "create_timed_event",
                    "input": {
                        "title": "Dentist",
                        "local_start_at": "2026-09-05T19:00:00Z",
                        "local_end_at": "2026-09-05T20:00:00Z",
                    },
                }
            ],
            _ctx(),
        )
        == []
    )


def test_drops_single_utc_suffixed_time() -> None:
    assert (
        _propose(
            [
                {
                    "name": "set_due_date",
                    "input": {"local_due_at": "2026-09-08T13:00:00Z"},
                }
            ],
            _ctx(work_item_id="w3"),
        )
        == []
    )


def test_drops_non_string_timed_value() -> None:
    # A non-string in a LOCAL_DATETIME slot is dropped, not coerced.
    assert (
        _propose(
            [{"name": "set_due_date", "input": {"local_due_at": 12345}}],
            _ctx(work_item_id="w3"),
        )
        == []
    )


# --- graceful degrade: malformed envelope never raises ---------------------


def test_non_dict_entries_in_content_are_ignored() -> None:
    client = ScriptedAnthropicClient(
        default={
            "stop_reason": "tool_use",
            "content": [
                "garbage",
                {"type": "tool_use", "id": "t", "name": "no_action", "input": {}},
            ],
        }
    )
    out = AnthropicAssistant(client).propose(_ctx())
    assert [p.name for p in out] == ["no_action"]


def test_empty_content_degrades_to_no_proposals() -> None:
    client = ScriptedAnthropicClient(default={"stop_reason": "end_turn", "content": []})
    assert AnthropicAssistant(client).propose(_ctx()) == []

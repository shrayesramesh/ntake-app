"""Step 6 — parsing / graceful-degrade hardening.

The request-path contract (LLD + NEXT_SESSION): a bad model, a bad transport, or
bad model output must **degrade to fewer/zero proposals, never raise**. The
engine's ``propose_bounded`` bounds the wall-clock and swallows a raise as a last
resort, but the client + parse layers must not raise on their own — these tests
pin that at each failure mode:

* **Transport (client):** HTTP 4xx/5xx, a connect/timeout error, and a non-JSON
  body all yield ``{}`` from ``complete`` (never an exception).
* **Parse/validate (assistant):** malformed envelopes and per-call violations
  (unknown action, missing required param, wrong exclusive-group) are dropped;
  a well-formed neighbour still survives.

(Some envelope-shape drops are already pinned in test_local_llm_assistant.py;
here we add the per-spec param-contract validation + the transport failures.)
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.assistant.capture import FocusedContext
from app.assistant.local_llm.assistant import LocalLlmAssistant
from app.assistant.local_llm.client import LocalLlmClient
from app.assistant.local_llm.protocol import ScriptedLLM

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


# --- client: the transport never raises -----------------------------------


def _client(handler) -> LocalLlmClient:
    return LocalLlmClient(
        base_url="http://localhost:8080",
        model="m",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )


def test_client_http_error_status_degrades_to_empty():
    # A 500 from the server must not raise out of complete().
    client = _client(lambda req: httpx.Response(500, text="boom"))
    assert client.complete(system="s", user="u", schema={}) == {}


def test_client_4xx_degrades_to_empty():
    client = _client(lambda req: httpx.Response(400, json={"error": "bad request"}))
    assert client.complete(system="s", user="u", schema={}) == {}


def test_client_transport_error_degrades_to_empty():
    # A connect/timeout-style transport failure must not raise either.
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert _client(boom).complete(system="s", user="u", schema={}) == {}


def test_client_timeout_degrades_to_empty():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    assert _client(slow).complete(system="s", user="u", schema={}) == {}


def test_client_non_json_body_degrades_to_empty():
    # A 200 whose *body* isn't JSON (not just the content field) → {}.
    client = _client(lambda req: httpx.Response(200, text="<html>nope</html>"))
    assert client.complete(system="s", user="u", schema={}) == {}


# --- assistant: per-spec param-contract validation drops bad calls ---------


def _ctx(
    work_item_id: int | None = None, event_id: int | None = None
) -> FocusedContext:
    return FocusedContext(
        text="note",
        timezone="America/New_York",
        now=NOW,
        deep_context="CTX",
        resolved_work_item_ids=[work_item_id] if work_item_id is not None else [],
        resolved_event_ids=[event_id] if event_id is not None else [],
    )


def _assistant(actions: list[dict]) -> LocalLlmAssistant:
    return LocalLlmAssistant(ScriptedLLM(default={"actions": actions}))


def test_drops_call_missing_a_required_param():
    # set_due_date requires due_at; a call without it is dropped, not attached.
    a = _assistant([{"name": "set_due_date", "params": {}}])
    assert a.propose(_ctx(work_item_id=3)) == []


def test_drops_call_with_empty_required_param():
    a = _assistant([{"name": "set_due_date", "params": {"due_at": ""}}])
    assert a.propose(_ctx(work_item_id=3)) == []


def test_keeps_call_with_required_param_present():
    a = _assistant(
        [{"name": "set_due_date", "params": {"due_at": "2026-09-05T19:00:00Z"}}]
    )
    out = a.propose(_ctx(work_item_id=3))
    assert [p.name for p in out] == ["set_due_date"]


def test_drops_call_supplying_no_exclusive_group():
    # create_event must supply exactly one timing group; title-only is incomplete.
    a = _assistant([{"name": "create_event", "params": {"title": "Dentist"}}])
    assert a.propose(_ctx()) == []


def test_drops_call_supplying_both_exclusive_groups():
    # Both a timed pair AND an all-day pair violates the exactly-one rule.
    a = _assistant(
        [
            {
                "name": "create_event",
                "params": {
                    "title": "Dentist",
                    "start_at": "2026-09-05T19:00:00Z",
                    "end_at": "2026-09-05T20:00:00Z",
                    "start_date": "2026-09-05",
                    "end_date": "2026-09-05",
                },
            }
        ]
    )
    assert a.propose(_ctx()) == []


def test_keeps_call_supplying_exactly_one_exclusive_group():
    a = _assistant(
        [
            {
                "name": "create_event",
                "params": {
                    "title": "Dentist",
                    "start_at": "2026-09-05T19:00:00Z",
                    "end_at": "2026-09-05T20:00:00Z",
                },
            }
        ]
    )
    out = a.propose(_ctx())
    assert [p.name for p in out] == ["create_event"]


def test_a_valid_call_survives_alongside_an_invalid_one():
    a = _assistant(
        [
            {"name": "set_due_date", "params": {}},  # invalid: missing due_at
            {"name": "complete_work_item", "params": {}},  # valid: no params needed
        ]
    )
    out = a.propose(_ctx(work_item_id=3))
    assert [p.name for p in out] == ["complete_work_item"]


# --- explicit local weekday/time validation (BUG-002) ----------------------


def _friday_ctx(text: str) -> FocusedContext:
    return FocusedContext(
        text=text,
        timezone="America/New_York",
        now=datetime(2026, 9, 4, 18, 25, tzinfo=UTC),
        deep_context="CTX",
    )


def test_drops_event_with_wrong_explicit_weekday_or_local_time():
    a = _assistant(
        [
            {
                "name": "create_event",
                "params": {
                    "title": "Soccer game",
                    "start_at": "2026-09-07T17:00:00Z",
                    "end_at": "2026-09-07T18:00:00Z",
                },
            }
        ]
    )

    assert a.propose(_friday_ctx("soccer game Wednesday 5-6 PM")) == []


def test_keeps_event_matching_explicit_weekday_and_local_time():
    a = _assistant(
        [
            {
                "name": "create_event",
                "params": {
                    "title": "Soccer game",
                    "start_at": "2026-09-09T21:00:00Z",
                    "end_at": "2026-09-09T22:00:00Z",
                },
            }
        ]
    )

    out = a.propose(_friday_ctx("soccer game Wednesday 5-6 PM"))

    assert [proposal.name for proposal in out] == ["create_event"]


def test_drops_event_with_wrong_explicit_single_clock_time():
    a = _assistant(
        [
            {
                "name": "create_event",
                "params": {
                    "title": "Sam meal prep",
                    "start_at": "2026-09-08T13:00:00Z",
                },
            }
        ]
    )

    assert a.propose(_friday_ctx("sam meal prep wed 1pm")) == []

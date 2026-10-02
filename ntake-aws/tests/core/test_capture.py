"""Capture pipeline value types (core/assistant/capture.py).

``CaptureRequest`` (stage-1 input) and ``FocusedContext`` (stage-2 input, the
engine's opaque read-only ctx). Session-1-live: imports only the engine contract
(``core.engine.engine``), no persistence. The DB-touching stage-1 resolver
(``core/assistant/base.py``) is parked for Session 2.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.assistant.capture import (
    CaptureRequest,
    FocusedContext,
    NullAssistant,
    ProposedAction,
)
from core.engine.engine import ActionContext

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


def test_capture_request_is_minimal() -> None:
    req = CaptureRequest(text="buy milk", timezone="America/New_York", now=NOW)
    assert req.text == "buy milk" and req.timezone == "America/New_York"


def test_focused_context_is_an_action_context() -> None:
    fc = FocusedContext(text="x", timezone="UTC", now=NOW)
    assert isinstance(fc, ActionContext)
    assert fc.deep_context == "" and fc.resolved_work_item_ids == []


def test_focused_context_primaries_default_to_none() -> None:
    fc = FocusedContext(text="x", timezone="UTC", now=NOW)
    assert fc.primary_work_item_id is None
    assert fc.primary_event_id is None
    assert fc.primary_member_id is None


def test_focused_context_primaries_return_first_resolved_id() -> None:
    fc = FocusedContext(
        text="x",
        timezone="UTC",
        now=NOW,
        resolved_work_item_ids=[7, 8],
        resolved_event_ids=[3],
        resolved_member_ids=[2, 5],
    )
    assert fc.primary_work_item_id == 7
    assert fc.primary_event_id == 3
    assert fc.primary_member_id == 2


def test_focused_context_render_describes_focus() -> None:
    fc = FocusedContext(
        text="pay the gas bill",
        timezone="UTC",
        now=NOW,
        resolved_work_item_ids=[7],
        resolved_event_ids=[3],
    )
    rendered = fc.render()
    assert "pay the gas bill" in rendered
    assert "#7" in rendered and "e3" in rendered


def test_focused_context_render_text_only_when_nothing_resolved() -> None:
    fc = FocusedContext(text="hello", timezone="UTC", now=NOW)
    assert fc.render() == "Understood: “hello”"


def test_null_assistant_proposes_nothing_and_reexports_proposed_action() -> None:
    fc = FocusedContext(text="x", timezone="UTC", now=NOW)
    assert NullAssistant().propose(fc) == []
    assert ProposedAction(name="noop", params={}).name == "noop"

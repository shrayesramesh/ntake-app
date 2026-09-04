"""The reshaped ``FocusedContext`` — the two-call target shape (WORKPLAN-A2).

``FocusedContext`` is the value object stage 1 (``focus()``) hands to stage 2
(``propose()``). Post-reshape it carries the resolved entity ids (from the LINK
call — fake or real) and the deep-context string (from ``deep_context``), NOT the
legacy ``calendar_window``/``work_item_id``. It stays a session-free
``ActionContext`` (read-only; the propose seam never touches the DB).

The ``primary_work_item_id`` / ``primary_event_id`` accessors give stage 2 a tiny,
readable way to attach a target from the resolved id lists (≤1 per type in v1).
``FocusedContext.render()`` prints what the assistant understood (text + resolved
ids); the
fake stamps it verbatim onto each proposal's ``llm_rationale``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.capture import FocusedContext
from app.routing.engine import ActionContext

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _ctx(
    text: str = "hello",
    *,
    wi_ids: list[int] | None = None,
    ev_ids: list[int] | None = None,
    deep_context: str = "",
) -> FocusedContext:
    return FocusedContext(
        text=text,
        timezone="America/New_York",
        now=NOW,
        resolved_work_item_ids=wi_ids or [],
        resolved_event_ids=ev_ids or [],
        deep_context=deep_context,
    )


def test_focused_context_is_an_action_context():
    assert isinstance(_ctx(), ActionContext)


def test_focused_context_carries_the_new_two_call_fields():
    ctx = _ctx("call plumber", wi_ids=[3], ev_ids=[8], deep_context="DEEP")
    assert ctx.text == "call plumber"
    assert ctx.timezone == "America/New_York"
    assert ctx.now == NOW
    assert ctx.resolved_work_item_ids == [3]
    assert ctx.resolved_event_ids == [8]
    assert ctx.deep_context == "DEEP"


def test_resolved_id_lists_default_to_empty():
    ctx = FocusedContext(text="x", timezone="UTC", now=NOW, deep_context="")
    assert ctx.resolved_work_item_ids == []
    assert ctx.resolved_event_ids == []


# --- primary_* accessors (target attachment, LLD OQ-4) --------------------


def test_primary_work_item_id_returns_first_resolved_or_none():
    assert _ctx(wi_ids=[5, 9]).primary_work_item_id == 5
    assert _ctx(wi_ids=[]).primary_work_item_id is None


def test_primary_event_id_returns_first_resolved_or_none():
    assert _ctx(ev_ids=[7, 2]).primary_event_id == 7
    assert _ctx(ev_ids=[]).primary_event_id is None


# --- FocusedContext.render() ----------------------------------------------


def test_render_includes_the_text():
    out = _ctx("buy milk").render()
    assert "buy milk" in out
    assert isinstance(out, str) and out


def test_render_mentions_resolved_ids_when_present():
    out = _ctx("the plumber item", wi_ids=[3], ev_ids=[8]).render()
    assert "3" in out  # resolved work item surfaced
    assert "8" in out  # resolved event surfaced


def test_render_handles_no_resolved_ids():
    out = _ctx("nothing linked").render()
    assert "nothing linked" in out

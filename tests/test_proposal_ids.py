"""Executable-only proposals + the proposal_id primitive.

Every proposal returned by /capture MUST be independently executable as-is (the
assistant is a "planner over a fixed set of actions"). A NEW-item capture must
NOT return an item-targeting action (set_due_date / complete_work_item) with
target_id=None — there is no item to target yet. New items are handled by
create_work_item; a brand-new item's due date is set later by capturing onto it
(correct-by-restate).

Each proposal carries a batch-local ``proposal_id`` (stable within one capture
response). ``target_ref`` is reserved for v2 dependency chaining and is None in v1.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.base import CaptureContext
from app.assistant.fake import FakeAssistant

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _ctx(text: str, target_id=None) -> CaptureContext:
    return CaptureContext(
        text=text, work_item_id=target_id, timezone="America/New_York", now=NOW
    )


def _needs_concrete_target(p) -> bool:
    """True when the proposal targets a WORK ITEM and therefore must carry a
    concrete target_id. A standalone event (target_type='event') is fully defined
    by its params and needs no work-item id."""
    return p.target_type == "work_item"


def test_new_item_capture_has_no_unexecutable_item_action():
    # 'monday' would previously add a set_due_date with target_id=None.
    props = FakeAssistant().propose(_ctx("soccer game on monday"))
    for p in props:
        if _needs_concrete_target(p):
            assert p.target_id is not None, f"{p.name} has no target on a new capture"
    # It proposes creating the work item (self-contained)...
    assert "create_work_item" in [p.name for p in props]
    # ...and NOT a bare set_due_date (no item to attach it to yet).
    assert "set_due_date" not in [p.name for p in props]


def test_new_event_capture_is_standalone_and_executable():
    # event word + weekday → a standalone create_event, fully specified.
    props = FakeAssistant().propose(_ctx("dentist appointment monday"))
    assert [p.name for p in props] == ["create_event"]
    ev = props[0]
    assert ev.target_type == "event"
    assert ev.target_id is None
    assert ev.params.get("start_at") and ev.params.get("end_at")


def test_new_project_word_is_ordinary_text_now():
    # 'project' dropped as a trigger (produced two unrelated rows) — it's now
    # ordinary text: a single, fully-defined create_work_item.
    props = FakeAssistant().propose(_ctx("project launch monday"))
    assert [p.name for p in props] == ["create_work_item"]
    for p in props:
        if _needs_concrete_target(p):
            assert p.target_id is not None


def test_existing_item_capture_still_targets_the_item():
    props = FakeAssistant().propose(_ctx("he is coming monday", target_id=7))
    due = next(p for p in props if p.name == "set_due_date")
    assert due.target_id == 7
    assert due.target_type == "work_item"


def test_proposals_expose_proposal_id_and_no_target_ref():
    for p in FakeAssistant().propose(_ctx("dentist appointment monday")):
        assert hasattr(p, "proposal_id")
        assert p.target_ref is None  # v1: no dangling dependency

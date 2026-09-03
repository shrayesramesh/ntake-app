"""Phase 4, task 3 — AssistantClient interface + FakeAssistant.

The FakeAssistant returns deterministic canned proposals derived from the input
text, so the entire propose->confirm flow is testable with no model. It must obey
the interface contract: never mutate, always return a list of ProposedAction
whose names are valid registry keys.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.actions import ACTIONS
from app.assistant.base import CaptureContext, ProposedAction
from app.assistant.fake import FakeAssistant

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _ctx(text: str, target_id: int | None = 7) -> CaptureContext:
    return CaptureContext(
        text=text,
        work_item_id=target_id,
        timezone="America/New_York",
        now=NOW,
    )


def test_proposals_use_valid_registry_names():
    fake = FakeAssistant()
    samples = ["he's coming friday at 3", "we finished it", "nothing here", "buy milk"]
    for text in samples:
        for p in fake.propose(_ctx(text)):
            assert isinstance(p, ProposedAction)
            assert p.name in ACTIONS


def test_friday_text_proposes_due_date():
    props = FakeAssistant().propose(_ctx("plumber coming friday"))
    names = [p.name for p in props]
    assert "set_due_date" in names
    due = next(p for p in props if p.name == "set_due_date")
    assert "due_at" in due.params  # a concrete datetime string
    assert due.target_id == 7


def test_done_text_proposes_complete():
    props = FakeAssistant().propose(_ctx("all done, finished the taxes"))
    assert "complete_work_item" in [p.name for p in props]


def test_event_text_proposes_create_event():
    props = FakeAssistant().propose(_ctx("dentist appointment thursday 9am"))
    assert "create_event" in [p.name for p in props]


def test_unmatched_text_proposes_no_action():
    props = FakeAssistant().propose(_ctx("hmm"))
    assert [p.name for p in props] == ["no_action"]


def test_propose_does_not_touch_the_db(session):
    """The assistant must be read-only; propose takes context, not a session."""
    from app.models import WorkItem, WorkItemUpdate

    before_items = session.query(WorkItem).count()
    before_updates = session.query(WorkItemUpdate).count()
    FakeAssistant().propose(_ctx("friday"))
    assert session.query(WorkItem).count() == before_items
    assert session.query(WorkItemUpdate).count() == before_updates


def test_proposals_carry_llm_rationale():
    # The assistant supplies its OWN narration (llm_rationale), not the ground-
    # truth action_summary (that's derived server-side from the registry).
    for p in FakeAssistant().propose(_ctx("plumber friday")):
        assert isinstance(p.llm_rationale, str)
    # A matched proposal has a non-empty rationale.
    due = next(
        p
        for p in FakeAssistant().propose(_ctx("plumber friday"))
        if p.name == "set_due_date"
    )
    assert due.llm_rationale

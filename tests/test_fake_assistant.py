"""Phase 4, task 3 — AssistantClient interface + FakeAssistant.

The FakeAssistant is a dumb-but-expressive test instrument: deterministic
keyword rules that can drive every v1 action and combination. These tests pin
the trigger vocabulary as its contract (see the fake's module docstring):

  New-item capture (no target):
    • event word (appointment/event/meeting/visit) + weekday → create_event ONLY
    • event word WITHOUT a weekday                            → work item only
    • anything else                                          → work item only
  Existing-item capture (real target):
    • weekday                    → set_due_date
    • + event word               → also a linked create_event
    • done word                  → complete_work_item
    • none of the above          → no_action

Every proposal must FULLY DEFINE its operation: a targeting action (needs_target)
carries a real target_id; a creating action fully specifies the new entity.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.actions import ACTIONS
from app.assistant.context import FocusedContext, ProposedAction
from app.assistant.fake import FakeAssistant

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _ctx(text: str, target_id: int | None = None) -> FocusedContext:
    return FocusedContext(
        text=text,
        timezone="America/New_York",
        now=NOW,
        resolved_work_item_ids=[target_id] if target_id is not None else [],
    )


def _names(props) -> list[str]:
    return [p.name for p in props]


# --- valid registry names + fully-defined operations ----------------------


def test_proposals_use_valid_registry_names():
    fake = FakeAssistant()
    samples = [
        "dentist appointment friday",
        "team meeting tuesday",
        "we finished it",
        "nothing here",
        "buy milk",
    ]
    for text in samples:
        for p in fake.propose(_ctx(text)):
            assert isinstance(p, ProposedAction)
            assert p.name in ACTIONS


def test_every_proposal_fully_defines_its_operation():
    """No proposal targets a nonexistent thing: a needs_target action always has
    a concrete target_id; a creating action carries its required params."""
    fake = FakeAssistant()
    for text in ["dentist appointment friday", "meeting monday", "buy milk", "hmm"]:
        for target in (None, 7):
            for p in fake.propose(_ctx(text, target_id=target)):
                spec = ACTIONS[p.name]
                # A work-item target must be concrete; a standalone event
                # (target_type='event') is fully defined by its params instead.
                if p.target_type == "work_item":
                    assert p.target_id is not None, (text, p.name)
                for key in spec.required:
                    assert p.params.get(key) not in (None, ""), (text, p.name, key)
                # v1 never leaves a dependency dangling.
                assert p.target_ref is None


# --- new-item capture vocabulary ------------------------------------------


def test_new_event_word_with_weekday_proposes_event_only():
    props = FakeAssistant().propose(_ctx("dentist appointment friday"))
    assert _names(props) == ["create_event"]
    ev = props[0]
    assert ev.target_type == "event"
    assert ev.target_id is None  # standalone but fully specified (has title+time)
    assert ev.params["start_at"] and ev.params["end_at"]


def test_new_event_word_without_weekday_is_work_item_only():
    # An event word with no weekday has no time to build an event → work item.
    props = FakeAssistant().propose(_ctx("team meeting"))
    assert _names(props) == ["create_work_item"]


def test_new_project_word_is_ordinary_text_now():
    # 'project' is no longer a special trigger (dropped: created two unrelated
    # rows). It is ordinary text -> a single create_work_item, no event.
    props = FakeAssistant().propose(_ctx("project kickoff monday"))
    assert _names(props) == ["create_work_item"]


def test_new_bland_text_is_work_item_only():
    assert _names(FakeAssistant().propose(_ctx("buy milk"))) == ["create_work_item"]


def test_new_capture_never_proposes_item_targeting_actions():
    # set_due_date / complete_work_item need an existing item; never on new items.
    for text in ["soccer game on monday", "all done", "meeting notes monday"]:
        names = _names(FakeAssistant().propose(_ctx(text)))
        assert "set_due_date" not in names
        assert "complete_work_item" not in names


# --- existing-item capture vocabulary -------------------------------------


def test_existing_weekday_proposes_due_date():
    props = FakeAssistant().propose(_ctx("he is coming friday", target_id=7))
    due = next(p for p in props if p.name == "set_due_date")
    assert due.target_id == 7 and due.target_type == "work_item"
    assert "due_at" in due.params


def test_existing_event_word_plus_weekday_also_links_event():
    props = FakeAssistant().propose(_ctx("dentist appointment friday", target_id=7))
    names = _names(props)
    assert "set_due_date" in names and "create_event" in names
    ev = next(p for p in props if p.name == "create_event")
    assert ev.target_id == 7 and ev.target_type == "work_item"  # linked + logged


def test_existing_done_word_proposes_complete():
    props = FakeAssistant().propose(_ctx("all done, finished the taxes", target_id=7))
    assert "complete_work_item" in _names(props)


def test_existing_untriggered_text_proposes_no_action():
    props = FakeAssistant().propose(_ctx("just a note", target_id=7))
    assert _names(props) == ["no_action"]


# --- contract: read-only + rationale --------------------------------------


def test_propose_does_not_touch_the_db(session):
    """The assistant must be read-only; propose takes context, not a session."""
    from app.models import WorkItem, WorkItemUpdate

    before_items = session.query(WorkItem).count()
    before_updates = session.query(WorkItemUpdate).count()
    FakeAssistant().propose(_ctx("dentist appointment friday"))
    assert session.query(WorkItem).count() == before_items
    assert session.query(WorkItemUpdate).count() == before_updates


def test_proposals_carry_llm_rationale():
    for p in FakeAssistant().propose(_ctx("dentist appointment friday")):
        assert isinstance(p.llm_rationale, str)
    ev = FakeAssistant().propose(_ctx("dentist appointment friday"))[0]
    assert ev.llm_rationale

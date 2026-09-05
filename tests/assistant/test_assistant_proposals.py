"""Pure API-presentation behavior for assistant proposals."""

from __future__ import annotations

from app.assistant.proposals import to_proposal_read
from app.routing.engine import ProposedAction


def test_to_proposal_read_enriches_assign_summary_with_member_name():
    """assign_work_item's summary shows the member NAME when a name map is given
    (the describe fn stays pure/id-based; the endpoint resolves the name)."""

    action = ProposedAction(
        name="assign_work_item", params={"member_id": 2}, target_type="work_item"
    )
    # Without a name map: raw registry summary (id only).
    plain = to_proposal_read(action, 1, None)
    assert "member 2" in plain.action_summary
    # With a name map: the member name is appended.
    enriched = to_proposal_read(action, 1, None, {2: "Sam"})
    assert "Sam" in enriched.action_summary


def test_to_proposal_read_no_member_name_map_is_safe():
    """A non-member action (or unresolvable id) is unaffected by the map."""

    action = ProposedAction(
        name="complete_work_item", params={}, target_type="work_item"
    )
    read = to_proposal_read(action, 1, None, {2: "Sam"})
    assert read.action_summary


def test_to_proposal_read_resolves_target_label_from_labels_map():
    """target_label is resolved from the per-type labels map using the action's
    target_type/target_id, and feeds render_card (e.g. 'Event: Dentist')."""

    action = ProposedAction(
        name="reschedule_timed_event",
        params={"start_at": "2026-09-10T14:00:00Z"},
        target_id=1,
        target_type="event",
    )
    read = to_proposal_read(
        action, 1, None, {}, {"event": {1: "Dentist"}, "work_item": {}}
    )
    assert read.target_label == "Dentist"
    assert any("Dentist" in ln for ln in read.detail_lines)


def testto_proposal_read_is_pure_and_derives_summary_and_id():

    a = ProposedAction(
        name="create_work_item",
        params={"title": "buy milk"},
        llm_rationale="looks like a task",
        target_type=None,
    )
    pr = to_proposal_read(a, index=1, target_label=None)
    # proposal_id assigned from the index; action_summary derived from registry.
    assert pr.proposal_id == "p1"
    assert "buy milk" in pr.action_summary
    assert pr.llm_rationale == "looks like a task"
    # Preserves an already-set proposal_id if the client provided one.
    a2 = ProposedAction(name="no_action", params={}, proposal_id="keep")
    assert to_proposal_read(a2, index=3, target_label=None).proposal_id == "keep"

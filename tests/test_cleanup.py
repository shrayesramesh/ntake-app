"""Cleanup-pass guards: single source of truth for board statuses (3+8) and the
pure proposal-mapping seam (5).
"""

from __future__ import annotations


def test_board_statuses_are_a_single_source_of_truth():
    # models defines the canonical ordered status codes; main + web derive from it
    # (no drift between the board projection, the fragment order, and the labels).
    from app.models import WORK_ITEM_STATUSES
    from app.web import COLUMN_LABELS, COLUMN_ORDER

    assert COLUMN_ORDER == list(WORK_ITEM_STATUSES)
    # Every column has a display label, and there are no stray labels.
    assert set(COLUMN_LABELS) == set(WORK_ITEM_STATUSES)


def test_main_board_columns_use_the_canonical_statuses():
    import app.main as main
    from app.models import WORK_ITEM_STATUSES

    assert main.BOARD_COLUMNS == list(WORK_ITEM_STATUSES)


# --- (5) pure proposal mapping --------------------------------------------


def test_to_proposal_read_is_pure_and_derives_summary_and_id():
    from app.main import _to_proposal_read
    from app.routing.engine import ProposedAction

    a = ProposedAction(
        name="create_work_item",
        params={"title": "buy milk"},
        llm_rationale="looks like a task",
        target_type=None,
    )
    pr = _to_proposal_read(a, index=1, target_label=None)
    # proposal_id assigned from the index; action_summary derived from registry.
    assert pr.proposal_id == "p1"
    assert "buy milk" in pr.action_summary
    assert pr.llm_rationale == "looks like a task"
    # Preserves an already-set proposal_id if the client provided one.
    a2 = ProposedAction(name="no_action", params={}, proposal_id="keep")
    assert _to_proposal_read(a2, index=3, target_label=None).proposal_id == "keep"

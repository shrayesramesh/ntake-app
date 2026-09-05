"""Cleanup-pass guards: single source of truth for board statuses (3+8) and the
pure proposal-mapping seam (5).
"""

from __future__ import annotations


def test_board_statuses_are_a_single_source_of_truth():
    # models defines the canonical ordered status codes; main + web derive from it
    # (no drift between the board projection, the fragment order, and the labels).
    from app.persistence.models import WORK_ITEM_STATUSES
    from app.web import COLUMN_LABELS, COLUMN_ORDER

    assert COLUMN_ORDER == list(WORK_ITEM_STATUSES)
    # Every column has a display label, and there are no stray labels.
    assert set(COLUMN_LABELS) == set(WORK_ITEM_STATUSES)


def test_main_board_columns_use_the_canonical_statuses():
    import app.main as main
    from app.persistence.models import WORK_ITEM_STATUSES

    assert main.BOARD_COLUMNS == list(WORK_ITEM_STATUSES)


# --- (5) pure proposal mapping --------------------------------------------

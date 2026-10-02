"""Placeholder so ``make test-data`` collects a (skipped) item until Session 2.

Session 2 fills this with the ``Repository`` protocol + ``InMemoryRepository``
flow tests (create work item → append update → read aggregate; put event → list
calendar; board grouping/ordering), written against the ``repo`` fixture so they
later run unchanged on ``DynamoRepository`` (Session 3). See AWS_LLD §2/§8.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Data layer arrives in Session 2 (AWS_PLAN Phase 2).")
def test_repository_contract_placeholder() -> None:  # pragma: no cover
    raise AssertionError("not implemented until Session 2")

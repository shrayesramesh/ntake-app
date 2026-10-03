"""Tier-2: the strongly-consistent shared flow bodies, now against real DynamoDB.

This module re-exports the subset of ``tests/data/test_repository_flows.py``
bodies that read **only strongly-consistent base-table items** (``GetItem`` /
base ``Query`` on PK/SK). Under this package's ``conftest.repo`` fixture those
run unchanged against the deployed ``ntake-dev`` table — the one-body-two-tiers
contract, with zero duplicated logic, for every behavior whose Tier-2 read is
immediately consistent.

**Deliberately excluded here:** the flow bodies that read a **GSI**
(``list_board`` / ``list_calendar`` / ``list_done_work_items``). DynamoDB GSIs
are eventually consistent, so those behaviors are covered **natively** in
``test_dynamo_access_patterns.py`` with the ``poll_until`` helper, which asserts
toward the exact expected result (correct for both "appears" and "drops out") —
rather than forcing a synchronous-in-memory body onto an async index.

``# noqa: F401`` — the imports' purpose IS re-collection under this package's
conftest; "unused" only to a linter, not to pytest.
"""

from __future__ import annotations

from tests.data.test_repository_flows import (  # noqa: F401
    test_connection_lifecycle,
    test_create_append_update_read_back_aggregate,
    test_create_event_from_update_writes_event_and_logs,
    test_get_work_item_miss_returns_none,
    test_members_and_family_reads,
    test_repo_satisfies_the_protocol,
    test_update_work_item_applies_changes,
)

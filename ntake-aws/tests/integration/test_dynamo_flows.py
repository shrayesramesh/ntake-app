"""Tier-2: the SAME flow tests, now against real DynamoDB (AWS_LLD §8).

This module re-exports every flow-test function from
``tests/data/test_repository_flows.py`` into the ``tests/integration`` package.
pytest collects them here too, where this package's ``conftest.repo`` fixture
binds the ``repo`` parameter to a real ``DynamoRepository`` (not the in-memory
double). So the identical assertions that pass at Tier 1 (``make check``) must
also hold against the deployed ``ntake-dev`` table at Tier 2
(``make integration``) — the one-body-two-tiers contract, with zero duplicated
test logic.

``# noqa: F401`` — the star-import's purpose IS the re-collection; the names are
"unused" only to a linter, not to pytest.
"""

from __future__ import annotations

from tests.data.test_repository_flows import *  # noqa: F401,F403

"""Tier-2 integration conftest — the real-DynamoDB fixtures (AWS_LLD §8).

These fixtures run **only** under ``make integration`` against the real
``ntake-dev`` table (not DynamoDB Local, which is dropped). ``make check`` /
``make test`` ignore this directory entirely (``--ignore=tests/integration``), so
Tier 1 never needs AWS.

The ``repo`` fixture here **overrides** the in-memory one from the top-level
``tests/conftest.py`` with a :class:`adapters.dynamo_repository.DynamoRepository`
pointed at the deployed table — so the identical flow-test bodies in
``tests/data/test_repository_flows.py`` re-run against real DynamoDB with no
change (the DRY backbone: one body, two tiers). Per-test isolation comes for free
because every ``make_family()`` mints a unique family id → a fresh partition, so
tests never collide and no table teardown is needed between them.

Configuration (env):
* ``NTAKE_TABLE_NAME`` — the table (default ``ntake-dev``).
* ``NTAKE_REGION`` / ``AWS_REGION`` — the region (default ``us-east-1``).
* ``NTAKE_DDB_ENDPOINT`` — optional endpoint override (unused against real AWS;
  kept because ``DynamoRepository`` is endpoint-configurable by design).
"""

from __future__ import annotations

import os

import pytest

from adapters.dynamo_repository import DynamoRepository


def _table_name() -> str:
    return os.environ.get("NTAKE_TABLE_NAME", "ntake-dev")


def _region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture
def dynamo_repo() -> DynamoRepository:
    """A ``DynamoRepository`` bound to the real dev table.

    Credential/account/table reachability is the shell self-check's job
    (``scripts/integration.sh`` stops before pytest if creds are missing/wrong
    account), so this fixture just constructs the client; a genuine access error
    surfaces as a test error, not a silent skip.
    """
    return DynamoRepository(
        _table_name(),
        region_name=_region(),
        endpoint_url=os.environ.get("NTAKE_DDB_ENDPOINT"),
    )


@pytest.fixture
def repo(dynamo_repo: DynamoRepository) -> DynamoRepository:
    """Override the Tier-1 in-memory ``repo`` so the shared flow tests run against
    real DynamoDB at Tier 2."""
    return dynamo_repo

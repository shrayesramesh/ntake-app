"""Tier-2 integration conftest — the real-DynamoDB fixtures (AWS_LLD §8).

These fixtures run **only** under ``make integration`` against the real
``ntake-dev`` table (not DynamoDB Local, which is dropped). ``make check`` /
``make test`` ignore this directory entirely (``--ignore=tests/integration``), so
Tier 1 never needs AWS.

Two consumers:

* **``repo``** — a :class:`adapters.dynamo_repository.DynamoRepository` on the
  real table, used by ``test_dynamo_flows.py`` to re-run the subset of shared
  flow bodies that touch only **strongly-consistent base-table reads**
  (``GetItem``/base ``Query`` on PK/SK). Those are identical across tiers.
* **``poll_until``** — a retry helper for the GSI-backed access-pattern tests
  (``test_dynamo_access_patterns.py``). DynamoDB **global secondary indexes are
  eventually consistent** (you cannot ``ConsistentRead`` a GSI), so a board /
  calendar / done-list Query issued immediately after a write may briefly lag.
  The adapter writes the correct keys synchronously; ``poll_until`` just absorbs
  propagation lag by retrying until the read **equals the known expected result**
  — which handles both "appears" (positive) and "drops out" (negative) correctly,
  unlike a blanket non-empty retry.

Per-test isolation is free: every ``make_family()`` mints a unique family id → a
fresh partition, so tests never collide and no table teardown is needed.

Config (env): ``NTAKE_TABLE_NAME`` (default ``ntake-dev``), ``NTAKE_REGION`` /
``AWS_REGION`` (default ``us-east-1``), ``NTAKE_DDB_ENDPOINT`` (optional).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

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
    """Override the Tier-1 in-memory ``repo`` so the shared **strongly-consistent**
    flow bodies run against real DynamoDB at Tier 2 (base-table reads only — the
    GSI-backed behaviors are covered natively in test_dynamo_access_patterns.py
    with ``poll_until``)."""
    return dynamo_repo


@pytest.fixture
def poll_until() -> Callable[..., Any]:
    """Retry a GSI read until it ``== expected`` (or a short budget elapses).

    Signature: ``poll_until(read, expected, *, key=..., timeout=10.0,
    interval=0.25)``. ``read`` is a zero-arg callable doing the GSI Query;
    ``key`` optionally projects the raw read to the comparable value (e.g. the
    list of titles). Returns the last read so the test can assert on it (giving a
    readable diff if it never converged). Correct for BOTH positive assertions
    (an item should appear) and negative ones (it should drop out), because it
    polls toward the *exact* expected value, not merely "non-empty".
    """

    def _poll(
        read: Callable[[], Any],
        expected: Any,
        *,
        key: Callable[[Any], Any] | None = None,
        timeout: float = 10.0,
        interval: float = 0.25,
    ) -> Any:
        project = key or (lambda x: x)
        deadline = time.monotonic() + timeout
        result = read()
        while project(result) != expected and time.monotonic() < deadline:
            time.sleep(interval)
            result = read()
        return result

    return _poll

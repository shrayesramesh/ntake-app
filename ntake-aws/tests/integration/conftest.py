"""Tier-2 integration conftest — the real-DynamoDB fixtures (AWS_LLD §8).

These fixtures run **only** under ``make integration`` against the real
``ntake-dev`` table (not DynamoDB Local, which is dropped). ``make check`` /
``make test`` ignore this directory entirely (``--ignore=tests/integration``), so
Tier 1 never needs AWS.

Fixtures:

* **``repo`` / ``dynamo_repo``** — a ``DynamoRepository`` (see
  :mod:`adapters.dynamo_repository`) on the real table. ``test_dynamo_flows.py``
  uses ``repo`` to re-run the subset of shared flow bodies that touch only
  **strongly-consistent base-table reads** (``GetItem`` / base ``Query`` on
  PK/SK), identical across tiers.
* **``poll_until``** — retry a GSI read until it ``== expected`` (GSIs are
  eventually consistent; you cannot ``ConsistentRead`` one), correct for both
  "appears" and "drops out".

**Identifiable ids + cleanup.** A session-scoped autouse fixture stamps every
test-minted id with the ``itest-`` prefix (via ``factories.set_id_prefix``), so
all rows this suite writes are recognizable as integration-test data
(``FAM#itest-<ulid>``) and visually obvious in the table. It then **sweeps every
``FAM#itest-`` partition before AND after the session**: the pre-sweep clears
rows leaked by a previously-crashed run; the post-sweep removes this run's data.
Prefix-based cleanup is more robust than per-test bookkeeping — it is correct
even across crashes and independent of how each test created its families.
Sweeps are best-effort (dev is ``DESTROY``-able; a stray row is harmless and must
never fail the suite).

Config (env): ``NTAKE_TABLE_NAME`` (default ``ntake-dev``), ``NTAKE_REGION`` /
``AWS_REGION`` (default ``us-east-1``), ``NTAKE_DDB_ENDPOINT`` (optional).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

import tests.harness.factories as factories
from adapters.dynamo_repository import DynamoRepository

# The identifiable prefix for every id this suite mints (see module docstring).
_TEST_ID_PREFIX = "itest-"
_FAMILY_PK_PREFIX = f"FAM#{_TEST_ID_PREFIX}"


def _table_name() -> str:
    return os.environ.get("NTAKE_TABLE_NAME", "ntake-dev")


def _region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


def _sweep_test_rows(repo: DynamoRepository) -> None:
    """Delete every item whose ``PK`` begins with ``FAM#itest-`` (best-effort).

    A ``Scan`` with a ``begins_with(PK, …)`` filter — fine at test scale and
    independent of the GSIs. Items are deleted by their real ``PK``/``SK`` via a
    ``batch_writer``; a family partition's base rows + GSI keys go together.
    """
    from boto3.dynamodb.conditions import Attr

    table = repo._table
    try:
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": Attr("PK").begins_with(_FAMILY_PK_PREFIX)
        }
        to_delete: list[dict[str, str]] = []
        while True:
            resp = table.scan(**scan_kwargs)
            to_delete.extend(
                {"PK": str(i["PK"]), "SK": str(i["SK"])} for i in resp.get("Items", [])
            )
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            scan_kwargs["ExclusiveStartKey"] = lek
        if to_delete:
            with table.batch_writer() as batch:
                for key in to_delete:
                    batch.delete_item(Key=key)
    except Exception:  # noqa: BLE001 — best-effort cleanup, never fail the suite
        pass


@pytest.fixture(scope="session", autouse=True)
def _identifiable_test_data() -> Iterator[None]:
    """Stamp test ids with ``itest-`` and sweep those rows before + after the run."""
    factories.set_id_prefix(_TEST_ID_PREFIX)
    sweeper = DynamoRepository(
        _table_name(),
        region_name=_region(),
        endpoint_url=os.environ.get("NTAKE_DDB_ENDPOINT"),
    )
    _sweep_test_rows(sweeper)  # clear anything leaked by a prior crashed run
    try:
        yield
    finally:
        _sweep_test_rows(sweeper)  # clear this run's data
        factories.set_id_prefix("")


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
    interval=0.25)``. ``read`` is a zero-arg callable doing the GSI Query; ``key``
    optionally projects the raw read to the comparable value (e.g. list of
    titles). Returns the last read so a never-converged assertion shows a readable
    diff. Correct for BOTH positive (should appear) and negative (should drop out)
    assertions, because it polls toward the *exact* expected value.
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

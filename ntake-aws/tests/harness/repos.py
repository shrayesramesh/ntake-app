"""Repository factories the ``repo`` fixture parametrizes over (AWS_LLD §2/§8).

The DRY backbone's centrepiece: **one test body, two backends**. A test that
accepts the ``repo`` fixture runs once against the in-memory implementation
(fast, no network) and once against the DynamoDB-Local-backed repo (real Dynamo
semantics) — and the second is **skipped-if-absent** when DynamoDB Local isn't
up and **not-implemented** until Session 3.

Session 2 landed the real :class:`core.repository_memory.InMemoryRepository`
behind the ``"memory"`` key (replacing the Session-1 ``PlaceholderRepository``);
Session 3 fills in the ``"dynamo"`` factory. Tests written against the ``repo``
fixture keep working across that swap because they depend on the fixture, not on
a concrete class.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from core.repository_memory import InMemoryRepository
from tests.harness.ddb_local import requires_dynamodb_local


def _make_memory() -> InMemoryRepository:
    return InMemoryRepository()


def _make_dynamo() -> Any:
    # Session 3 wires DynamoRepository against DynamoDB Local here. Until then the
    # param is skipped (see REPO_PARAMS), so this is never called in Session 2.
    raise NotImplementedError(
        "DynamoRepository factory arrives in Session 3 (AWS_LLD §2.2)."
    )


# The factory registry. The fixture (tests/conftest.py) parametrizes over these.
REPO_FACTORIES: dict[str, Callable[[], Any]] = {
    "memory": _make_memory,
    "dynamo": _make_dynamo,
}

# Parametrization params: the in-memory backend always runs; the dynamo backend
# is skipped-if-absent (and additionally not-yet-implemented in Session 2, so it
# carries a skip until Session 3 lands the factory).
REPO_PARAMS = [
    pytest.param("memory", id="memory"),
    pytest.param(
        "dynamo",
        id="dynamo",
        marks=[
            requires_dynamodb_local,
            pytest.mark.skip(
                reason="DynamoRepository factory not implemented until Session 3"
            ),
        ],
    ),
]

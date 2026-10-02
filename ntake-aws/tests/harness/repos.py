"""Repository factories the ``repo`` fixture parametrizes over (AWS_LLD §2/§8).

The DRY backbone's centrepiece: **one test body, two backends**. A test that
accepts the ``repo`` fixture runs once against the in-memory fake (fast, no
network) and once against the DynamoDB-Local-backed repo (real Dynamo semantics)
— and the second is **skipped-if-absent** when DynamoDB Local isn't up.

Session 1 status (flagged): the real ``Repository`` protocol and its two
implementations are **Session 2-3** work (AWS_LLD §2). To stand the harness up
*now* without pre-building that contract, this module ships a tiny
:class:`PlaceholderRepository` so the parametrization is real and self-tested;
Session 2 replaces it with the actual ``InMemoryRepository`` (same factory key
``"memory"``) and Session 3 fills in the ``"dynamo"`` factory. Tests written
against the ``repo`` fixture keep working across that swap because they depend on
the fixture, not on this placeholder.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.harness.ddb_local import requires_dynamodb_local


class PlaceholderRepository:
    """Session-1 stand-in for the real ``Repository`` (replaced in Session 2).

    Carries just enough behavior to make the parametrized fixture exercisable:
    it reports its backend name. It deliberately implements **none** of the real
    repository method set (``get_work_item`` etc. — AWS_LLD §2.1) so no test
    accidentally couples to a throwaway; those arrive with the real impl.
    """

    backend = "memory"

    def ping(self) -> str:
        """Return the backend name — a trivial liveness check for the harness."""
        return self.backend


def _make_memory() -> PlaceholderRepository:
    return PlaceholderRepository()


def _make_dynamo() -> Any:
    # Session 3 wires DynamoRepository against DynamoDB Local here. Until then the
    # param is skipped (see REPO_PARAMS), so this is never called in Session 1.
    raise NotImplementedError(
        "DynamoRepository factory arrives in Session 3 (AWS_LLD §2.2)."
    )


# The factory registry. The fixture (tests/conftest.py) parametrizes over these.
REPO_FACTORIES: dict[str, Callable[[], Any]] = {
    "memory": _make_memory,
    "dynamo": _make_dynamo,
}

# Parametrization params: the in-memory backend always runs; the dynamo backend
# is skipped-if-absent (and additionally not-yet-implemented in Session 1, so it
# carries an xfail-free skip until Session 3 lands the factory).
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

"""The repository factory the ``repo`` fixture builds (AWS_LLD §2/§8).

Under the two-tier model (2026-10-02), **Tier 1 is in-memory only** — the fast,
networkless gate. The ``repo`` fixture is therefore no longer parametrized over
two backends: it yields a fresh :class:`core.repository_memory.InMemoryRepository`.

Tier 2 (``make integration``) does **not** go through this fixture: it points a
:class:`adapters.dynamo_repository.DynamoRepository` at the **real** ``ntake-dev``
table (not DynamoDB Local, which is dropped). The same flow-test bodies run both
tiers because they depend on the ``Repository`` protocol, not on how the instance
is built — Tier 2 injects the Dynamo repo via its own conftest (``tests/integration``).
"""

from __future__ import annotations

from collections.abc import Callable

from core.repository_memory import InMemoryRepository


def _make_memory() -> InMemoryRepository:
    return InMemoryRepository()


# The single Tier-1 factory. The fixture (tests/conftest.py) builds this.
REPO_FACTORIES: dict[str, Callable[[], InMemoryRepository]] = {
    "memory": _make_memory,
}

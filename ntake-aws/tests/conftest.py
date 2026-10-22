"""Shared pytest fixtures — the harness entry point (AWS_LLD §8).

Importing works because ``tests/`` is a package and ``core/`` is a sibling
top-level package under ``ntake-aws/``: pytest puts the first parent without an
``__init__.py`` (the ``ntake-aws/`` package root) on ``sys.path``, so both
``import core...`` and ``import tests.harness...`` resolve with no path hacking.

Fixtures provided to every session's tests:

* ``repo`` — a fresh ``InMemoryRepository`` (Tier 1 — the fast, networkless
  gate). Tier 2 (``make integration``) uses a real ``DynamoRepository`` via its
  own conftest, not this fixture.
* ``scripted_anthropic`` — a factory for the deterministic Anthropic Messages
  double (canned LINK forced-tool JSON + PROPOSE ``tool_use`` blocks).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from core.repository_memory import InMemoryRepository
from tests.harness.anthropic_double import ScriptedAnthropicClient
from tests.harness.repos import REPO_FACTORIES


@pytest.fixture
def repo() -> InMemoryRepository:
    """A fresh in-memory repository (Tier 1 — the fast, networkless gate).

    Under the two-tier model, Tier 1 is in-memory only; Tier 2
    (``make integration``) points a ``DynamoRepository`` at the real dev table
    via its own conftest, not through this fixture. The flow tests depend on the
    ``Repository`` protocol, so one body serves both tiers.
    """
    return REPO_FACTORIES["memory"]()


@pytest.fixture
def scripted_anthropic() -> Callable[..., ScriptedAnthropicClient]:
    """Factory for a :class:`ScriptedAnthropicClient` (canned LINK/PROPOSE responses).

    The real seam's double (Anthropic Messages shape). Returned as a factory so a
    test seeds its own canned ``responses`` / ``default`` inline:

        client = scripted_anthropic(responses={"plumber": link_response(...)})
    """

    def _make(
        responses: dict[str, dict[str, Any]] | None = None,
        *,
        default: dict[str, Any] | None = None,
    ) -> ScriptedAnthropicClient:
        return ScriptedAnthropicClient(responses=responses, default=default)

    return _make

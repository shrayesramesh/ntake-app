"""Shared pytest fixtures — the harness entry point (AWS_LLD §8).

Importing works because ``tests/`` is a package and ``core/`` is a sibling
top-level package under ``ntake-aws/``: pytest puts the first parent without an
``__init__.py`` (the ``ntake-aws/`` package root) on ``sys.path``, so both
``import core...`` and ``import tests.harness...`` resolve with no path hacking.

Fixtures provided to every session's tests:

* ``repo`` — **parametrized over both backends** (in-memory now, DynamoDB Local
  later; the dynamo param is skipped-if-absent / not-yet-implemented). One test
  body, two backends — the DRY backbone.
* ``scripted_bedrock`` — a factory for the deterministic Bedrock Converse double
  (canned LINK JSON + ``toolUse`` blocks).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.harness.bedrock_double import ScriptedBedrockClient
from tests.harness.repos import REPO_FACTORIES, REPO_PARAMS


@pytest.fixture(params=REPO_PARAMS)
def repo(request: pytest.FixtureRequest) -> Any:
    """A repository instance, once per backend (``memory`` + ``dynamo``).

    Session 1 yields the ``PlaceholderRepository`` for ``memory`` and skips
    ``dynamo``; Session 2-3 swap in the real impls behind the same fixture, so
    tests written against ``repo`` need no change.
    """
    backend: str = request.param
    return REPO_FACTORIES[backend]()


@pytest.fixture
def scripted_bedrock() -> Callable[..., ScriptedBedrockClient]:
    """Factory for a :class:`ScriptedBedrockClient` (canned LINK/PROPOSE responses).

    Returned as a factory (not a bare instance) so a test seeds its own canned
    ``responses`` / ``default`` inline:

        client = scripted_bedrock(responses={"groceries": link_response(...)})
    """

    def _make(
        responses: dict[str, dict[str, Any]] | None = None,
        *,
        default: dict[str, Any] | None = None,
    ) -> ScriptedBedrockClient:
        return ScriptedBedrockClient(responses=responses, default=default)

    return _make

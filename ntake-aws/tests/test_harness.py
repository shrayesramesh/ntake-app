"""Self-tests for the shared test harness (tests/harness/ + conftest fixtures).

The harness is the DRY backbone Sessions 2-9 import, so it is itself real
functionality worth testing. Covers the in-memory ``repo`` fixture and the
boundary assertion helper. (The scripted Anthropic Messages double — the seam's
deterministic LINK/PROPOSE double — has its own dedicated suite in
``tests/assistant/test_anthropic_double.py``.)
"""

from __future__ import annotations

from core.repository import Repository
from core.repository_memory import InMemoryRepository
from tests.harness.boundary import assert_imports_none_of

# --- repo fixture (in-memory, Tier 1) -------------------------------------


def test_repo_fixture_yields_a_backend(repo: object) -> None:
    # Tier 1 is in-memory only: the fixture yields the real InMemoryRepository,
    # which structurally satisfies the Repository protocol.
    assert isinstance(repo, InMemoryRepository)
    assert isinstance(repo, Repository)


# --- boundary helper ------------------------------------------------------


def test_boundary_helper_passes_for_a_clean_target() -> None:
    # The harness's own boundary module imports no infra packages.
    assert_imports_none_of("tests.harness.boundary", {"boto3", "sqlalchemy", "fastapi"})

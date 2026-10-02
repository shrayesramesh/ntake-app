"""Engine import boundary — the AWS analog of the old sqlalchemy-boundary test.

The engine (:mod:`core.engine.engine`) is the infra-agnostic heart of the app:
it registers actions, validates params, dispatches to a handler over an OPAQUE
context it never inspects, describes an action, and runs a bounded/graceful-
degrade propose. It must import NOTHING infra-specific — no ``boto3``, no
``sqlalchemy``, no HTTP framework (``fastapi``), and nothing from the deleted
self-hosted ``app`` package (``app.persistence.models`` et al.). That boundary is
what keeps the core a pure, reusable centre the ``adapters`` layer depends on,
never the reverse (AWS_HLD §5, AWS_LLD §8).

Real functionality, written test-first: this is the guard, not scaffolding. The
assertion tooling lives in ``tests/harness/boundary.py`` so later sessions reuse
it for other boundaries (e.g. the single ``publish_change`` call site).
"""

from __future__ import annotations

from tests.harness.boundary import (
    assert_imports_none_of,
    imported_modules_on_fresh_import,
)

# What the engine must never pull in, transitively, on a fresh import. ``boto3``
# is the new entry vs. the old test; ``app`` catches any lingering reference to
# the deleted self-hosted runtime (persistence models, FastAPI wiring, etc.).
FORBIDDEN = {"boto3", "botocore", "sqlalchemy", "fastapi", "app"}


def test_engine_imports_nothing_infra_specific() -> None:
    assert_imports_none_of("core.engine.engine", FORBIDDEN)


def test_engine_does_not_import_the_parked_action_handlers() -> None:
    """The parked, persistence-coupled action modules (Session 2) must not be
    reachable from the engine — importing the engine must not drag them in."""
    newly = imported_modules_on_fresh_import("core.engine.engine")
    parked = {
        "core.actions.context",
        "core.actions.shared",
        "core.actions.registry",
        "core.actions.work_items",
        "core.actions.events",
        "core.assistant.base",
    }
    leaked = newly & parked
    assert not leaked, f"engine reached parked persistence-coupled modules: {leaked}"

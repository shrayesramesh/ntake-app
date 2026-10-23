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


def test_action_handlers_import_no_boto3_or_persistence() -> None:
    """The ported action handlers (Session 3) depend only on the ``Repository``
    *seam*, never ``boto3`` or any infra. Importing the registry (their entry
    point) must drag in none of the forbidden packages — the ``DynamoRepository``
    adapter is the only place ``boto3`` lives, and the handlers never import it.
    """
    assert_imports_none_of("core.actions.registry", FORBIDDEN)


def test_identity_and_live_sync_import_nothing_infra_specific() -> None:
    """The Session-6 core seams stay pure: the identity logic
    (``core.identity``), the token-store seam (``core.token_store``), and the
    live-sync publish (``core.live_sync``) depend only on their protocols +
    stdlib — never ``boto3``/``fastapi``/the deleted ``app``. ``boto3`` lives only
    in the ``adapters``/``handlers`` edge (the ``DynamoTokenStore`` /
    ``connection_poster``), never in ``core``.
    """
    assert_imports_none_of("core.identity", FORBIDDEN)
    assert_imports_none_of("core.token_store", FORBIDDEN)
    assert_imports_none_of("core.token_store_memory", FORBIDDEN)
    assert_imports_none_of("core.live_sync", FORBIDDEN)


def test_engine_does_not_import_the_action_handlers() -> None:
    """The engine stays persistence-ignorant: importing it must not drag in the
    action handler modules (they depend on it, never the reverse)."""
    newly = imported_modules_on_fresh_import("core.engine.engine")
    handlers = {
        "core.actions.context",
        "core.actions.shared",
        "core.actions.registry",
        "core.actions.work_items",
        "core.actions.events",
        "core.assistant.base",
    }
    leaked = newly & handlers
    assert not leaked, f"engine reached the action handler modules: {leaked}"

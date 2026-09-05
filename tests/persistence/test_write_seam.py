"""Checkpoint 1d — the write seam: committing a change publishes a change event.

The emitter itself is unit-tested in test_event_emitter.py. Here we test the
*seam*: per DESIGN §4.3, "on any write, the backend publishes a change event."
We prove that property structurally — an ``after_commit`` hook fires for
inserts, updates, and deletes — without any HTTP layer, so every future write
path (assistant confirm, checklist tick, archive, .ics import) inherits it for
free.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.event_emitter import InProcessEmitter
from app.persistence.database import (
    init_schema,
    make_session_factory,
    register_change_events,
)
from app.persistence.models import Event, Family


@pytest.fixture()
def seam_session():
    """An isolated in-memory session with NO pre-bound emitter.

    Distinct from the conftest ``session`` fixture (which binds the app emitter)
    so these seam unit-tests attach exactly one emitter of their own — the seam's
    per-session pending buffer is single-emitter by design.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_schema(engine)
    db = make_session_factory(engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def captured(seam_session):
    """Attach a fresh emitter+listener to the isolated seam session.

    Returns the list that accumulates ``(entity, id, op)`` tuples emitted on
    commit.
    """
    emitter = InProcessEmitter()
    received: list[tuple[str, int, str]] = []

    async def listener(entity: str, id: int, op: str) -> None:
        received.append((entity, id, op))

    emitter.add_listener(listener)
    register_change_events(seam_session, emitter)
    return received


def _seed_family(session) -> Family:
    fam = Family(name="Fam", timezone="America/New_York")
    session.add(fam)
    session.commit()
    return fam


def test_insert_emits_create(seam_session, captured):
    fam = _seed_family(seam_session)  # families row is itself a create
    assert ("families", fam.id, "create") in captured


def test_update_emits_update(seam_session, captured):
    fam = _seed_family(seam_session)
    captured.clear()

    fam.name = "Renamed"
    seam_session.commit()

    assert captured == [("families", fam.id, "update")]


def test_delete_emits_delete(seam_session, captured):
    fam = _seed_family(seam_session)
    now = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    ev = Event(
        family_id=fam.id,
        title="dentist",
        start_at=now,
        end_at=now,
        created_at=now,
        updated_at=now,
    )
    seam_session.add(ev)
    seam_session.commit()
    captured.clear()

    seam_session.delete(ev)
    seam_session.commit()

    assert captured == [("events", ev.id, "delete")]


def test_no_commit_no_emit(seam_session, captured):
    """A flush without commit must not publish (avoids announcing rolled-back
    changes — the dual-write hazard)."""
    fam = Family(name="Uncommitted", timezone="UTC")
    seam_session.add(fam)
    seam_session.flush()  # assigns PK but does not commit
    seam_session.rollback()

    assert captured == []

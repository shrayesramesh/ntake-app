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

from app.db import register_change_events
from app.event_emitter import InProcessEmitter
from app.models import Event, Family


@pytest.fixture()
def captured(session):
    """Attach a fresh emitter+listener to the test session's engine.

    Returns the list that accumulates ``(entity, id, op)`` tuples emitted on
    commit. Uses the per-test in-memory engine from the ``session`` fixture.
    """
    emitter = InProcessEmitter()
    received: list[tuple[str, int, str]] = []

    async def listener(entity: str, id: int, op: str) -> None:
        received.append((entity, id, op))

    emitter.add_listener(listener)
    register_change_events(session, emitter)
    return received


def _seed_family(session) -> Family:
    fam = Family(name="Fam", timezone="America/New_York")
    session.add(fam)
    session.commit()
    return fam


def test_insert_emits_create(session, captured):
    fam = _seed_family(session)  # families row is itself a create
    assert ("families", fam.id, "create") in captured


def test_update_emits_update(session, captured):
    fam = _seed_family(session)
    captured.clear()

    fam.name = "Renamed"
    session.commit()

    assert captured == [("families", fam.id, "update")]


def test_delete_emits_delete(session, captured):
    fam = _seed_family(session)
    now = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    ev = Event(
        family_id=fam.id,
        title="dentist",
        start_at=now,
        end_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(ev)
    session.commit()
    captured.clear()

    session.delete(ev)
    session.commit()

    assert captured == [("events", ev.id, "delete")]


def test_no_commit_no_emit(session, captured):
    """A flush without commit must not publish (avoids announcing rolled-back
    changes — the dual-write hazard)."""
    fam = Family(name="Uncommitted", timezone="UTC")
    session.add(fam)
    session.flush()  # assigns PK but does not commit
    session.rollback()

    assert captured == []

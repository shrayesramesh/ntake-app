"""Explicit timed/all-day assistant event action variants."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.assistant.actions import ACTIONS, ActionError, apply_action
from app.models import Event


def test_registry_uses_explicit_event_timing_variants():
    assert {"create_event", "reschedule_event"}.isdisjoint(ACTIONS)
    assert {
        "create_timed_event",
        "create_all_day_event",
        "reschedule_timed_event",
        "reschedule_all_day_event",
    }.issubset(ACTIONS)
    assert all(not spec.exclusive_params for spec in ACTIONS.values())


def test_create_timed_event_requires_complete_timed_pair(session, fam_member):
    _fam, member = fam_member

    with pytest.raises(ActionError):
        apply_action(
            session,
            member,
            "create_timed_event",
            None,
            {"title": "Dentist", "start_at": "2026-09-05T19:00:00Z"},
            target_type="event",
        )


def test_create_all_day_event_defaults_end_date(session, fam_member):
    family, member = fam_member
    apply_action(
        session,
        member,
        "create_all_day_event",
        None,
        {"title": "School holiday", "start_date": "2026-09-12"},
        target_type="event",
    )

    session.expire_all()
    event = session.query(Event).one()
    assert event.family_id == family.id
    assert event.all_day is True
    assert event.start_date == event.end_date == date(2026, 9, 12)
    assert event.start_at is None and event.end_at is None


def test_reschedule_timed_event_requires_complete_timed_pair(session, fam_member):
    family, member = fam_member
    event = Event(
        family_id=family.id,
        title="Dentist",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    session.add(event)
    session.commit()

    with pytest.raises(ActionError):
        apply_action(
            session,
            member,
            "reschedule_timed_event",
            event.id,
            {"start_at": "2026-09-08T19:00:00Z"},
            target_type="event",
        )


def test_reschedule_all_day_event_defaults_end_date(session, fam_member):
    family, member = fam_member
    event = Event(
        family_id=family.id,
        title="School holiday",
        all_day=True,
        start_date=date(2026, 9, 5),
        end_date=date(2026, 9, 5),
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    session.add(event)
    session.commit()

    apply_action(
        session,
        member,
        "reschedule_all_day_event",
        event.id,
        {"start_date": "2026-09-10"},
        target_type="event",
    )

    session.expire_all()
    updated = session.get(Event, event.id)
    assert updated.all_day is True
    assert updated.start_date == updated.end_date == date(2026, 9, 10)

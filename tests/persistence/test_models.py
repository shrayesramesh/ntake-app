"""Checkpoint 1b — DB write/read round-trip for Family and Event."""

from datetime import UTC, datetime

from app.persistence.models import Event, Family


def test_family_and_event_roundtrip(session):
    fam = Family(name="Test Family", timezone="America/New_York")
    session.add(fam)
    session.commit()

    now = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    end = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)
    ev = Event(
        family_id=fam.id,
        title="dentist",
        start_at=now,
        end_at=end,
        created_at=now,
        updated_at=now,
    )
    session.add(ev)
    session.commit()

    fetched = session.get(Event, ev.id)
    assert fetched is not None
    assert fetched.title == "dentist"
    assert fetched.family_id == fam.id
    # default applied
    assert fetched.all_day is False
    # no todo-driven origin for a directly-created event
    assert fetched.source_update_id is None


def test_all_day_event_uses_dates(session):
    fam = Family(name="Fam", timezone="America/New_York")
    session.add(fam)
    session.commit()

    from datetime import date

    now = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    ev = Event(
        family_id=fam.id,
        title="Birthday",
        all_day=True,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        created_at=now,
        updated_at=now,
    )
    session.add(ev)
    session.commit()

    fetched = session.get(Event, ev.id)
    assert fetched.all_day is True
    assert fetched.start_date == date(2026, 9, 1)
    assert fetched.start_at is None  # all-day events don't use the UTC instant

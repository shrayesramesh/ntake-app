"""Checkpoint 1c — GET /events read path."""

from datetime import UTC, datetime

from app.models import Event, Family


def test_events_empty(client):
    r = client.get("/events")
    assert r.status_code == 200
    assert r.json() == []


def test_events_returns_seeded_event(client, session):
    fam = Family(name="Fam", timezone="America/New_York")
    session.add(fam)
    session.commit()

    now = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    session.add(
        Event(
            family_id=fam.id,
            title="dentist",
            start_at=now,
            end_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    r = client.get("/events")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["title"] == "dentist"
    assert data[0]["family_id"] == fam.id
    assert data[0]["all_day"] is False

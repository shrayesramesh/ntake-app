"""Checkpoint 1c — GET /events read path (now auth-protected, ACCESS-2)."""

from datetime import UTC, datetime

from app.models import Event, Family, Member


def test_events_empty(client, auth_headers):
    r = client.get("/events", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_events_returns_seeded_event(client, session, auth_headers):
    member = session.query(Member).filter_by(display_name="Tester").one()
    family = session.get(Family, member.family_id)
    assert family is not None

    now = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    session.add(
        Event(
            family_id=family.id,
            title="dentist",
            start_at=now,
            end_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    r = client.get("/events", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["title"] == "dentist"
    assert data[0]["family_id"] == family.id
    assert data[0]["all_day"] is False


def test_events_excludes_foreign_family_events(client, session, auth_headers):
    """Calendar event fetches are family-scoped; another household's events never
    reach the authenticated browser client."""
    other = Family(name="Other", timezone="America/New_York")
    session.add(other)
    session.commit()
    now = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    session.add(
        Event(
            family_id=other.id,
            title="private foreign event",
            start_at=now,
            end_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    data = client.get("/events", headers=auth_headers).json()
    assert all(event["title"] != "private foreign event" for event in data)

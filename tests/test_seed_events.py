"""Task 9 — event seeding: a way to create events WITHOUT the assistant.

Covers the ``seed_event`` helper (timed + all-day), the ``event_factory`` /
``seeded_events`` pytest fixtures, and the ``seed-events`` manage CLI subcommand
(the host-smoke / manual-testing seed path). Direct human event CRUD in the UI is
NOT part of this — events arrive via the assistant or via this seed path.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.manage import seed_event
from app.models import Event, Family


def _family(session, tz="America/New_York") -> Family:
    fam = Family(name="Fam", timezone=tz)
    session.add(fam)
    session.commit()
    return fam


# --- seed_event helper ----------------------------------------------------


def test_seed_event_timed_sets_utc_datetimes(session):
    fam = _family(session)
    start = datetime(2026, 9, 4, 19, 0, tzinfo=UTC)
    end = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)

    ev = seed_event(session, fam.id, title="Plumber visit", start_at=start, end_at=end)

    assert ev.id is not None
    assert ev.family_id == fam.id
    assert ev.title == "Plumber visit"
    assert ev.all_day is False
    # SQLite stores naive datetimes; the app stores UTC, so the round-tripped
    # value equals the wall-clock UTC time without tzinfo (matches how the rest
    # of the codebase treats stored timestamps).
    assert ev.start_at == start.replace(tzinfo=None)
    assert ev.end_at == end.replace(tzinfo=None)
    assert ev.start_date is None and ev.end_date is None
    assert ev.created_at is not None and ev.updated_at is not None


def test_seed_event_all_day_sets_dates(session):
    fam = _family(session)
    day = date(2026, 12, 25)

    ev = seed_event(session, fam.id, title="Holiday", all_day=True, start_date=day)

    assert ev.all_day is True
    assert ev.start_date == day
    # end_date defaults to start_date for a single all-day event.
    assert ev.end_date == day
    assert ev.start_at is None and ev.end_at is None


def test_seed_event_all_day_explicit_end_date(session):
    fam = _family(session)
    start = date(2026, 12, 24)
    end = date(2026, 12, 26)

    ev = seed_event(
        session, fam.id, title="Trip", all_day=True, start_date=start, end_date=end
    )

    assert ev.start_date == start
    assert ev.end_date == end


def test_seed_event_timed_defaults_end_to_start(session):
    fam = _family(session)
    start = datetime(2026, 9, 4, 19, 0, tzinfo=UTC)

    ev = seed_event(session, fam.id, title="Point in time", start_at=start)

    assert ev.end_at == start.replace(tzinfo=None)


def test_seed_event_persists_and_is_committed(session):
    fam = _family(session)
    seed_event(
        session,
        fam.id,
        title="dentist",
        start_at=datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
    )
    # A fresh query sees it (helper commits, matching the token helpers).
    assert session.query(Event).filter_by(title="dentist").one() is not None


def test_seed_event_optional_fields(session):
    fam = _family(session)
    ev = seed_event(
        session,
        fam.id,
        title="Recital",
        start_at=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
        description="School recital",
        location="Auditorium",
    )
    assert ev.description == "School recital"
    assert ev.location == "Auditorium"


def test_seed_event_requires_timing(session):
    fam = _family(session)
    # No timing supplied at all -> a clear error, not a half-built row.
    with pytest.raises(ValueError):
        seed_event(session, fam.id, title="No timing")


def test_seed_event_all_day_requires_start_date(session):
    fam = _family(session)
    with pytest.raises(ValueError):
        seed_event(session, fam.id, title="All day no date", all_day=True)


def test_seeded_event_shows_in_events_api(client, session, auth_headers):
    # auth_headers created a family named "TestFam"; seed against it.
    fam = session.query(Family).filter_by(name="TestFam").one()
    seed_event(
        session,
        fam.id,
        title="soccer",
        start_at=datetime(2026, 9, 5, 14, 0, tzinfo=UTC),
    )

    r = client.get("/events", headers=auth_headers)
    assert r.status_code == 200
    titles = [e["title"] for e in r.json()]
    assert "soccer" in titles


# --- fixtures -------------------------------------------------------------


def test_event_factory_fixture(event_factory, session):
    fam = _family(session)
    ev = event_factory(fam.id, title="from-factory")
    assert ev.id is not None
    assert ev.title == "from-factory"


def test_seeded_events_fixture_creates_timed_and_all_day(seeded_events):
    # The fixture seeds a family + at least one timed and one all-day event.
    kinds = {ev.all_day for ev in seeded_events}
    assert kinds == {True, False}


# --- CLI (main) seed-events dispatch --------------------------------------


@pytest.fixture()
def cli_db(tmp_path, monkeypatch):
    """Point app.manage.main at a fresh temp DB with a seeded family."""
    import app.db as db
    from app.db import build_engine, init_schema, make_session_factory

    engine = build_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    init_schema(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", factory)

    s = factory()
    s.add(Family(name="Fam", timezone="America/New_York"))
    s.commit()
    s.close()
    return factory


def test_main_seed_events_creates_events(cli_db, capsys):
    from app.manage import main

    rc = main(["seed-events"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Seeded" in out

    session = cli_db()
    events = session.query(Event).all()
    # Seeds at least one timed + one all-day event for manual/calendar testing.
    assert len(events) >= 2
    assert {ev.all_day for ev in events} == {True, False}


def test_main_seed_events_no_family_errors(tmp_path, monkeypatch, capsys):
    import app.db as db
    from app.db import build_engine, init_schema, make_session_factory
    from app.manage import main

    engine = build_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    init_schema(engine)
    factory = make_session_factory(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", factory)

    rc = main(["seed-events"])
    assert rc == 1
    assert "family" in capsys.readouterr().err.lower()

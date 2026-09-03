"""Pytest fixtures: isolated in-memory SQLite DB + FastAPI client.

Each test gets a fresh in-memory database, so tests don't share state or touch
the real calendar.db file.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.db import (
    get_session,
    init_schema,
    make_session_factory,
    register_change_events,
)
from app.main import app, app_emitter


@pytest.fixture()
def session():
    """A fresh in-memory SQLite session per test.

    StaticPool + a single shared connection keeps the in-memory DB alive across
    the session's operations within one test. Schema + factory come from the
    shared db helpers so tests exercise the same construction path as the app;
    PRAGMA foreign_keys=ON matches the app engine so FK actions are enforced. The
    change-event seam is bound to this factory + the app emitter so tests also
    exercise the write->emit path (matching the app, where it's bound to
    SessionLocal).
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    init_schema(engine)
    factory = make_session_factory(engine)
    register_change_events(factory, app_emitter)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def client(session):
    """TestClient with the get_session dependency overridden to the test DB."""

    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(session, monkeypatch):
    """Enroll a member + active device token; return an Authorization header.

    Sets NTAKE_TOKEN_SECRET and stores the token's hash under that secret, so the
    auth dependency resolves the returned bearer token to the enrolled member.
    Use on tests that hit auth-protected endpoints.
    """
    from datetime import UTC, datetime

    from app.models import DeviceToken, Family, Member
    from app.tokens import generate_token, hash_token

    secret = "test-token-secret"
    monkeypatch.setenv("NTAKE_TOKEN_SECRET", secret)

    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    fam = Family(name="TestFam", timezone="America/New_York")
    session.add(fam)
    session.commit()
    member = Member(
        family_id=fam.id, display_name="Tester", role="adult", created_at=now
    )
    session.add(member)
    session.commit()

    token = generate_token()
    session.add(
        DeviceToken(
            member_id=member.id,
            token_hash=hash_token(token, secret=secret),
            label="test-device",
            created_at=now,
        )
    )
    session.commit()

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def event_factory(session):
    """Factory to seed events into the test DB (thin wrapper over seed_event).

    Returns a callable ``make(family_id, **kwargs)`` so a test can create as many
    events as it needs; each is committed and returned. Defaults to a timed event
    with a fixed UTC start so callers only pass what they care about.
    """
    from datetime import UTC, datetime

    from app.manage import seed_event

    default_start = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)

    def make(family_id, *, title="Test event", **kwargs):
        if not kwargs.get("all_day") and "start_at" not in kwargs:
            kwargs["start_at"] = default_start
        return seed_event(session, family_id, title=title, **kwargs)

    return make


@pytest.fixture()
def seeded_events(session, event_factory):
    """A family plus one timed and one all-day event; returns the two events.

    For tests/manual-parity that need a populated calendar (task 9). Kept minimal:
    exactly one of each timing kind so ``{ev.all_day}`` is ``{True, False}``.
    """
    from datetime import UTC, date, datetime

    from app.models import Family

    fam = Family(name="SeededFam", timezone="America/New_York")
    session.add(fam)
    session.commit()

    timed = event_factory(
        fam.id, title="Seeded timed", start_at=datetime(2026, 9, 4, 19, 0, tzinfo=UTC)
    )
    all_day = event_factory(
        fam.id, title="Seeded all-day", all_day=True, start_date=date(2026, 9, 5)
    )
    return [timed, all_day]

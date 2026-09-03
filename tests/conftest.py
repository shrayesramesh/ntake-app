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

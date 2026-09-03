"""Pytest fixtures: isolated in-memory SQLite DB + FastAPI client.

Each test gets a fresh in-memory database, so tests don't share state or touch
the real calendar.db file.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.db import get_session, init_schema, make_session_factory
from app.main import app


@pytest.fixture()
def session():
    """A fresh in-memory SQLite session per test.

    StaticPool + a single shared connection keeps the in-memory DB alive across
    the session's operations within one test. Schema + factory come from the
    shared db helpers so tests exercise the same construction path as the app.
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
def client(session):
    """TestClient with the get_session dependency overridden to the test DB."""

    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

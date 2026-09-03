"""App startup creates the schema (regression for the LAN-smoke 500).

A real server run must have its tables without any manual ``create_all``. This
boots the app via its lifespan against a *fresh* temp-file DB and asserts the
events read path works — the exact path that 500'd with ``no such table:
events`` before startup schema-init existed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.db import build_engine, init_schema


def test_init_schema_creates_all_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    engine = create_engine(url)
    assert inspect(engine).get_table_names() == []

    init_schema(engine)

    tables = set(inspect(engine).get_table_names())
    assert {"families", "events"} <= tables


def test_build_engine_returns_usable_engine(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'x.db'}")
    init_schema(engine)
    assert "events" in inspect(engine).get_table_names()


def test_app_lifespan_initializes_schema_so_events_works(tmp_path, monkeypatch):
    """Booting the app on a fresh DB yields a working /events with no manual DDL.

    The app's engine is created at import from CALENDAR_DB_URL. We rebind it to a
    fresh temp file and run the app through its lifespan (TestClient context
    manager triggers startup), then hit /events.
    """
    import app.db as db
    import app.main as main

    fresh = build_engine(f"sqlite:///{tmp_path / 'boot.db'}")
    monkeypatch.setattr(db, "engine", fresh)

    with TestClient(main.app) as client:  # enters lifespan → init_schema(engine)
        r = client.get("/events")
        assert r.status_code == 200
        assert r.json() == []

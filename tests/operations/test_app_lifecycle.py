"""App lifecycle — the health endpoint and startup schema init.

Consolidates the two boot-time checkpoint files:

* **Health (1a)** — ``GET /health`` returns ok + a version.
* **Startup schema** — a real server run creates its tables via the app lifespan
  with no manual ``create_all`` (regression for the LAN-smoke 500 that was
  ``no such table: events`` before startup schema-init existed).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.persistence.database import build_engine, init_schema

# --- health endpoint (1a) -------------------------------------------------


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# --- startup schema init --------------------------------------------------


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

    The app engine is created at import from CALENDAR_DB_URL. We rebind it (and
    SessionLocal) to a fresh temp file, run the app through its lifespan
    (TestClient context manager triggers startup → init_schema), enroll a token
    in that same DB, and hit the now auth-protected /events.
    """
    from datetime import UTC, datetime

    import app.main as main
    import app.persistence.database as db
    from app.identity.tokens import generate_token, hash_token
    from app.persistence.database import make_session_factory
    from app.persistence.models import DeviceToken, Family, Member

    secret = "test-token-secret"
    monkeypatch.setenv("NTAKE_TOKEN_SECRET", secret)

    fresh = build_engine(f"sqlite:///{tmp_path / 'boot.db'}")
    monkeypatch.setattr(db, "engine", fresh)
    monkeypatch.setattr(db, "SessionLocal", make_session_factory(fresh))

    with TestClient(main.app) as client:  # enters lifespan → init_schema(engine)
        # Enroll a device token in the freshly-created schema.
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        s = db.SessionLocal()
        fam = Family(name="Fam", timezone="America/New_York")
        s.add(fam)
        s.commit()
        m = Member(family_id=fam.id, display_name="A", role="adult", created_at=now)
        s.add(m)
        s.commit()
        token = generate_token()
        s.add(
            DeviceToken(
                member_id=m.id,
                token_hash=hash_token(token, secret=secret),
                label="d",
                created_at=now,
            )
        )
        s.commit()
        s.close()

        r = client.get("/events", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == []


# --- startup warm-ping hook (task 7 step 10) ------------------------------


def test_warm_hook_noop_for_fake_backend(monkeypatch):
    """Default (fake) config: the startup warm hook does nothing (no thread)."""
    import app.assistant.local_llm.infra as infra
    import app.main as main

    called = []
    monkeypatch.setattr(infra, "warm", lambda base_url, model: called.append(1))
    main._warm_local_model_in_background()  # default config is fake
    assert called == []


def test_warm_hook_warms_for_local_backend(monkeypatch):
    """local config: the hook warms the model in a background thread."""
    import threading

    import app.assistant.factory as factory
    import app.assistant.local_llm.infra as infra
    import app.main as main

    monkeypatch.setattr(
        factory,
        "default_assistant_config",
        lambda: factory.AssistantConfig(
            kind="local", model="llama3.1:8b", base_url="http://localhost:8080"
        ),
    )
    done = threading.Event()
    seen: dict = {}

    def _warm(base_url, model):
        seen["base_url"] = base_url
        seen["model"] = model
        done.set()
        return True

    monkeypatch.setattr(infra, "warm", _warm)

    main._warm_local_model_in_background()
    assert done.wait(timeout=2.0), "warm was not called in the background"
    assert seen == {"base_url": "http://localhost:8080", "model": "llama3.1:8b"}

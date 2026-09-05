"""Pytest fixtures: isolated in-memory SQLite DB + FastAPI client.

Each test gets a fresh in-memory database, so tests don't share state or touch
the real calendar.db file.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.main import app, app_emitter
from app.persistence.database import (
    get_session,
    init_schema,
    make_session_factory,
    register_change_events,
)


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

    from app.identity.tokens import generate_token, hash_token
    from app.persistence.models import DeviceToken, Family, Member

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
def family_factory(session):
    """Factory: ``make(name="Fam", tz="America/New_York") -> Family`` (committed).

    Removes the copied 3-line family-seeding boilerplate scattered across tests.
    """
    from app.persistence.models import Family

    def make(name: str = "Fam", tz: str = "America/New_York"):
        fam = Family(name=name, timezone=tz)
        session.add(fam)
        session.commit()
        return fam

    return make


@pytest.fixture()
def member_factory(session):
    """Factory: ``make(family_id, name="A", role="adult") -> Member`` (committed)."""
    from datetime import UTC, datetime

    from app.persistence.models import Member

    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    def make(family_id: int, *, name: str = "A", role: str = "adult", **kwargs):
        m = Member(
            family_id=family_id,
            display_name=name,
            role=role,
            created_at=now,
            **kwargs,
        )
        session.add(m)
        session.commit()
        return m

    return make


@pytest.fixture()
def work_item_factory(session):
    """Factory: ``make(family_id, title="call plumber", **kw) -> WorkItem``.

    Committed; extra columns (status, assigned_to, archived_at, …) pass through.
    """
    from datetime import UTC, datetime

    from app.persistence.models import WorkItem

    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    def make(family_id: int, *, title: str = "call plumber", **kwargs):
        wi = WorkItem(
            family_id=family_id,
            title=title,
            created_at=now,
            updated_at=now,
            **kwargs,
        )
        session.add(wi)
        session.commit()
        return wi

    return make


@pytest.fixture()
def fam_member(family_factory, member_factory):
    """A committed (family, member) pair — the common per-test seed. Replaces the
    ``_fam_member`` helper copied across the assistant tests."""
    fam = family_factory()
    m = member_factory(fam.id)
    return fam, m


@pytest.fixture()
def fam_member_item(fam_member, work_item_factory):
    """A committed (family, member, work_item) triple. Replaces the copied
    ``_fam_member_item`` helper."""
    fam, m = fam_member
    wi = work_item_factory(fam.id)
    return fam, m, wi


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

    from app.persistence.models import Family

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


@pytest.fixture()
def populated_family(session, event_factory):
    """A realistically-seeded family for world-view / assistant tests.

    Seeds real rows so downstream tests build the world view from *actual seeded
    content* via ``build_world_view`` — not a hand-mocked string that could drift
    from what the queries yield. Covers the cases the world view cares about:
    two members (adult + child), work items spanning statuses **including one
    ``done`` and one ``archived``** (to exercise done-included / archived-excluded),
    and events **inside and outside** the default 7-day window plus an all-day one.

    Returns a small bundle (``.now`` is the reference clock the window is relative
    to; ids let a test assert against known targets, e.g. that the world view can
    target work item ``w<items['doing']>``):

        {family, now, tz, members: {name: id}, items: {key: id}, events: {key: id}}
    """
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from app.persistence.models import Family, Member, WorkItem

    # Reference "now": Thu 2026-09-03 12:00 UTC = 08:00 America/New_York.
    now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    tz = "America/New_York"

    fam = Family(name="PopulatedFam", timezone=tz)
    session.add(fam)
    session.commit()

    members: dict[str, int] = {}
    for name, role in (("Alex", "adult"), ("Sam", "child")):
        m = Member(family_id=fam.id, display_name=name, role=role, created_at=now)
        session.add(m)
        session.commit()
        members[name] = m.id

    items: dict[str, int] = {}
    specs = [
        ("todo", {"title": "buy stamps", "status": "todo"}),
        ("doing", {"title": "call plumber", "status": "doing"}),
        ("done", {"title": "file taxes", "status": "done", "completed_at": now}),
        (
            "archived",
            {"title": "old chore", "status": "done", "archived_at": now},
        ),
    ]
    for key, kw in specs:
        wi = WorkItem(family_id=fam.id, created_at=now, updated_at=now, **kw)
        session.add(wi)
        session.commit()
        items[key] = wi.id

    events: dict[str, int] = {}
    # in-window (2 days ago), out-of-window (30 days ago), future, and all-day.
    # participants exercises both shapes: a linked member and a free-text name.
    events["recent"] = event_factory(
        fam.id,
        title="Soccer",
        start_at=datetime(2026, 9, 1, 19, 0, tzinfo=UTC),
        participants=[{"member_id": members["Sam"]}, {"name": "Coach Lee"}],
    ).id
    events["old"] = event_factory(
        fam.id, title="Old picnic", start_at=datetime(2026, 8, 4, 19, 0, tzinfo=UTC)
    ).id
    events["future"] = event_factory(
        fam.id, title="Dentist", start_at=datetime(2026, 12, 1, 19, 0, tzinfo=UTC)
    ).id
    events["all_day"] = event_factory(
        fam.id, title="Holiday", all_day=True, start_date=date(2026, 9, 5)
    ).id

    return SimpleNamespace(
        family=fam, now=now, tz=tz, members=members, items=items, events=events
    )

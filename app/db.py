"""Database setup + the live-sync write seam.

SQLite to start (DESIGN §1 / research/04-data-layer.md). The database URL is
configurable via the CALENDAR_DB_URL env var so tests can use a separate/
in-memory database without touching the real file.

**Live-sync seam (DESIGN §4.3, checkpoint 1d).** ``register_change_events``
binds an :class:`~app.event_emitter.EventEmitter` to a Session (or its engine)
so that *every successful commit* publishes ``{entity, id, op}`` change events —
one per inserted/updated/deleted row. This is deliberately an ``after_commit``
hook rather than an explicit call at each write site: the front-end (via the SSE
endpoint, 1e) is the sole consumer and it needs a *completeness* guarantee — no
committed change may go unannounced, or a device silently shows stale state.
Binding to commit makes "persist ⟹ publish" hold by construction for every write
path, including ones not yet written (assistant confirm, checklist tick, archive,
.ics import). The single registration point here keeps that magic legible.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.event_emitter import EventEmitter

# Default to a local SQLite file; override in tests via CALENDAR_DB_URL.
DB_URL = os.environ.get("CALENDAR_DB_URL", "sqlite:///./calendar.db")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def build_engine(url: str = DB_URL) -> Engine:
    """Create an Engine with the project's standard SQLite settings.

    Single place engines are constructed, so the app and tests share one code
    path. ``check_same_thread=False`` is the standard SQLite+SQLAlchemy setting
    for use across FastAPI request threads.
    """
    return create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )


def make_session_factory(bind: Engine) -> sessionmaker[Session]:
    """The project's standard session factory for a given engine."""
    return sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)


def init_schema(bind: Engine) -> None:
    """Create all tables on ``bind``.

    Imported here (not at module top) so importing db.py doesn't require models,
    but calling init_schema registers every mapped table on Base.metadata first.
    This is the single schema-creation entry point for app startup and tests
    (Alembic migration wiring is a deferred PLAN item — see PLAN.md 1b).
    """
    import app.models  # noqa: F401  (register mappers on Base.metadata)

    Base.metadata.create_all(bind)


# Module-level engine + factory the app uses (built via the shared helpers).
engine = build_engine()
SessionLocal = make_session_factory(engine)


def get_session():
    """FastAPI dependency: yield a session and always close it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --- Live-sync write seam (checkpoint 1d) --------------------------------

# Change events pending for the current transaction, keyed by Session. Populated
# at flush time (when new/dirty/deleted are still readable) and drained on
# commit. Keyed per-session so concurrent sessions don't cross-contaminate.
_pending: dict[Session, list[tuple[str, int, str]]] = {}


def _entity_of(obj: object) -> str | None:
    """The table name for an ORM instance, or None if it isn't mapped."""
    return getattr(obj, "__tablename__", None)


def _dispatch(emitter: EventEmitter, events: list[tuple[str, int, str]]) -> None:
    """Deliver change events through the (async) emitter from a sync callback.

    ``after_commit`` is synchronous. If an event loop is already running (the
    FastAPI async path), schedule the coroutine on it; otherwise (sync tests,
    scripts) run it to completion.
    """
    for entity, id_, op in events:
        coro = emitter.emit(entity, id_, op)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
        else:
            loop.create_task(coro)


def register_change_events(session_target, emitter: EventEmitter) -> None:
    """Publish a change event on every committed insert/update/delete.

    ``session_target`` must be a Session **event target**: a Session instance
    (test path — binds to that one session), a ``sessionmaker`` factory, or the
    ``Session`` class (app path — binds to every session it makes). These are
    Session-level events (``after_flush``/``after_commit``/``after_rollback``);
    they do **not** exist on an Engine.
    """

    def _record_flush(session: Session, flush_context, instances=None) -> None:
        pending = _pending.setdefault(session, [])
        for obj in session.new:
            entity = _entity_of(obj)
            if entity is not None:
                pending.append((entity, obj.id, "create"))
        for obj in session.dirty:
            if not session.is_modified(obj, include_collections=False):
                continue
            entity = _entity_of(obj)
            if entity is not None:
                pending.append((entity, obj.id, "update"))
        for obj in session.deleted:
            entity = _entity_of(obj)
            if entity is not None:
                pending.append((entity, obj.id, "delete"))

    def _emit_commit(session: Session) -> None:
        events = _pending.pop(session, [])
        if events:
            _dispatch(emitter, events)

    def _discard(session: Session) -> None:
        _pending.pop(session, None)

    event.listen(session_target, "after_flush", _record_flush)
    event.listen(session_target, "after_commit", _emit_commit)
    event.listen(session_target, "after_rollback", _discard)

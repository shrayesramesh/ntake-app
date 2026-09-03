"""FastAPI application.

Endpoints:
  * ``GET /health``        — liveness (1a)
  * ``GET /events``        — events read path (1c)
  * ``GET /events/stream`` — Server-Sent Events live-sync stream (1e)

Live sync (DESIGN §4.3): the module-level ``app_emitter`` is bound to the DB
engine via ``register_change_events`` so every commit publishes a change event
(1d). The SSE endpoint subscribes a per-connection queue to that emitter and
streams ``{entity, id, op}`` notifications; the front-end refetches on receipt.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

import app.db as db
from app import __version__
from app.config import config_path, load_config, seed_from_config
from app.db import SessionLocal, get_session, init_schema, register_change_events
from app.event_emitter import InProcessEmitter
from app.models import Event
from app.schemas import EventRead


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """On startup: ensure the schema exists, then seed identity from config.

    Schema init is unconditional (a real server needs its tables — the LAN smoke
    500'd on ``no such table`` before this existed). Config seeding is conditional
    on the file existing, so tests that boot the app without ``NTAKE_CONFIG`` set
    don't fail; a real deployment points ``NTAKE_CONFIG`` at its out-of-repo file.
    Reads ``db.engine`` at runtime so a rebound engine (tests) is honored.
    """
    init_schema(db.engine)

    path = config_path()
    if path.exists():
        session = db.SessionLocal()
        try:
            seed_from_config(session, load_config(path))
        finally:
            session.close()

    yield


app = FastAPI(title="Family Calendar", lifespan=lifespan)

# The single live-sync emitter. Bound to the session factory so every committed
# write (from any session it makes) publishes a change event.
app_emitter = InProcessEmitter()
register_change_events(SessionLocal, app_emitter)


@app.get("/health")
def health() -> dict:
    """Liveness check (checkpoint 1a)."""
    return {"status": "ok", "version": __version__}


@app.get("/events", response_model=list[EventRead])
def list_events(session: Session = Depends(get_session)) -> list[Event]:
    """Return all persisted events as JSON (checkpoint 1c).

    Ordered by start time. FastAPI serializes each ORM Event via EventRead
    (from_attributes).
    """
    stmt = select(Event).order_by(Event.start_at)
    return list(session.scalars(stmt).all())


def _format_change(entity: str, id: int, op: str) -> dict:
    """Render a change event as an SSE message dict (client refetches on it)."""
    data = json.dumps({"entity": entity, "id": id, "op": op})
    return {"event": "change", "data": data}


def subscribe(emitter: InProcessEmitter) -> tuple[asyncio.Queue, Callable[[], None]]:
    """Attach a queue listener to the emitter; return the queue + an unsubscribe.

    Kept separate from the endpoint so the subscription wiring is unit-testable
    without opening a real SSE socket (which never completes).
    """
    queue: asyncio.Queue[tuple[str, int, str]] = asyncio.Queue()

    async def listener(entity: str, id: int, op: str) -> None:
        await queue.put((entity, id, op))

    emitter.add_listener(listener)

    def unsubscribe() -> None:
        if listener in emitter.listeners:
            emitter.listeners.remove(listener)

    return queue, unsubscribe


@app.get("/events/stream")
async def events_stream() -> EventSourceResponse:
    """Server-Sent Events stream of change notifications (checkpoint 1e).

    Thin transport over :func:`subscribe`: each connection gets its own queue,
    the emitter fans committed changes out to it, and we stream them until the
    client disconnects. `EventSource` auto-reconnects.
    """
    queue, unsubscribe = subscribe(app_emitter)

    async def event_generator() -> AsyncIterator[dict]:
        try:
            while True:
                yield _format_change(*await queue.get())
        finally:
            unsubscribe()

    return EventSourceResponse(event_generator())

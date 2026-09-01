"""FastAPI application: health endpoint (1a) and events read path (1c)."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.db import get_session
from app.models import Event
from app.schemas import EventRead

app = FastAPI(title="Family Calendar")


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

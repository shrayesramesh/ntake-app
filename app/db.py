"""Database setup: SQLAlchemy 2.0 engine, session factory, and declarative Base.

SQLite to start (DESIGN §1.5 / research/04-data-layer.md). The database URL is
configurable via the CALENDAR_DB_URL env var so tests can use a separate/in-memory
database without touching the real file.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Default to a local SQLite file; override in tests via CALENDAR_DB_URL.
DB_URL = os.environ.get("CALENDAR_DB_URL", "sqlite:///./calendar.db")

# check_same_thread=False is the standard SQLite+SQLAlchemy setting for use
# across FastAPI request threads.
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_session():
    """FastAPI dependency: yield a session and always close it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

"""Pydantic DTOs for the API boundary (JSON <-> Python).

Separate from the ORM models (research/04-data-layer.md decision 2): ORM classes
handle persistence, these handle API validation/serialization.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EventRead(BaseModel):
    """Event as returned by the API."""

    # Allow constructing directly from an ORM object (obj.attr access).
    model_config = ConfigDict(from_attributes=True)

    id: int
    family_id: int
    title: str
    description: str | None = None
    location: str | None = None
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None

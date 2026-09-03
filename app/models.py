"""ORM models (SQLAlchemy 2.0, declarative, typed `Mapped[...]`).

Minimal schema per research/04-data-layer.md (simplified 2026-08-30). Timestamps
stored UTC (NFR-TIME); `families.timezone` required day-one. Defines Family and
Event (checkpoint 1b) and the identity tables Member and DeviceToken (Phase 2,
ACCESS). Work-item tables (WorkItem, WorkItemUpdate, ChecklistItem) come in
Phase 3.

Events are intentionally small: no iCalendar-mirroring columns (uid/sequence/
status), no recurrence. `.ics` import/export is a deferred capability whose
export function synthesizes UID/DTSTAMP as needed. Recurring needs surface via
the LLM reading the todo update log, not via event columns.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    # Required day-one: needed to resolve relative capture like "Tuesday 3pm"
    # (F-CAP-04) and to render all-day events correctly. e.g. "America/New_York".
    timezone: Mapped[str]


class Member(Base):
    """A family member (ACCESS / DESIGN §3). Role gates adult-vs-child (SAFE-2).

    Seeded from the out-of-repo config on startup (Phase 2). ``phone_number`` is
    contact-only, never used for auth.
    """

    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"))
    display_name: Mapped[str]
    role: Mapped[str]  # "adult" | "child" (app-level enum; kept as text)
    phone_number: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime]


class DeviceToken(Base):
    """A per-device credential (DESIGN §2). Stores only the token *hash*.

    ``revoked_at`` NULL = active; set to revoke. Minted by the manage CLI, which
    prints the plaintext once and persists the hash here.
    """

    __tablename__ = "device_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    token_hash: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]
    created_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"))
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    location: Mapped[str | None] = mapped_column(default=None)

    # Timing. Timed events use the UTC datetimes; all-day events use the plain
    # DATE fields (no timezone) to avoid the off-by-one all-day bug (NFR-TIME).
    all_day: Mapped[bool] = mapped_column(default=False)
    start_at: Mapped[datetime | None] = mapped_column(default=None)  # timed (UTC)
    end_at: Mapped[datetime | None] = mapped_column(default=None)
    start_date: Mapped[date | None] = mapped_column(default=None)  # all-day
    end_date: Mapped[date | None] = mapped_column(default=None)

    # Attribution: the todo_updates record that drove this event, if any. Person
    # + when + reason live on that update record (no person FK duplicated here).
    # NOTE: FK to todo_updates.id deferred until that table exists (later
    # checkpoint); plain nullable int for now so 1b is self-contained.
    source_update_id: Mapped[int | None] = mapped_column(default=None)

    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

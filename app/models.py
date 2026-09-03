"""ORM models (SQLAlchemy 2.0, declarative, typed `Mapped[...]`).

Minimal schema per research/04-data-layer.md (simplified 2026-08-30). Timestamps
stored UTC (NFR-TIME); `families.timezone` required day-one. Defines Family and
Event (checkpoint 1b), the identity tables Member and DeviceToken (Phase 2,
ACCESS), and the work-item tables WorkItem, WorkItemUpdate, ChecklistItem
(Phase 3).

Events are intentionally small: no iCalendar-mirroring columns (uid/sequence/
status), no recurrence. `.ics` import/export is a deferred capability whose
export function synthesizes UID/DTSTAMP as needed. Recurring needs surface via
the LLM reading the todo update log, not via event columns.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The fixed work-item status codes, in board order (WORKITEM-4 / GROOM). Single
# source of truth: the board projection (main), the fragment column order, and
# the UI labels (web) all derive from this — no drift. Display labels are a
# UI-layer concern (see app/web.py), keyed off these codes.
WORK_ITEM_STATUSES: tuple[str, ...] = ("todo", "on_deck", "doing", "done")


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
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
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

    # Attribution: the work_item_updates record that drove this event, if any.
    # Person + when + reason live on that update record (no person FK duplicated
    # here). SET NULL: removing the update unlinks the event, doesn't delete it.
    source_update_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_item_updates.id", ondelete="SET NULL"), default=None
    )

    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class WorkItem(Base):
    """A loose free-text work item + an append-only update log (WORKITEM).

    Status is a fixed code set (todo|on_deck|doing|done); display labels are
    UI-layer. ``tags`` is a shared-vocabulary string list (JSON column, portable).
    ``due_at`` is assistant-inferred + human-confirmed, not a core human field.
    """

    __tablename__ = "work_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id"))
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column()
    description: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="todo")  # todo|on_deck|doing|done
    position: Mapped[int] = mapped_column(default=0)  # order within a status column
    due_at: Mapped[datetime | None] = mapped_column(default=None)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    archived_at: Mapped[datetime | None] = mapped_column(default=None)


class WorkItemUpdate(Base):
    """Append-only update log — the primary daily object (WORKITEM-2/3).

    ``author`` is always a member: the human who wrote the note (human entries)
    or confirmed the change (assistant entries). ``source`` distinguishes a
    human-written note from a confirmed assistant-driven outcome — this is what
    lets the labor view credit human effort without conflating it with
    rubber-stamped assistant actions.
    """

    __tablename__ = "work_item_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE")
    )
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), default=None
    )
    source: Mapped[str] = mapped_column()  # "human" | "assistant"
    body: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column()


class ChecklistItem(Base):
    """Sub-items for the grocery-list-style use case (WORKITEM-6)."""

    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column()
    checked: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int] = mapped_column(default=0)

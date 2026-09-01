# Data layer — ORM choice & Python representation (decision)

> **⚠ HISTORICAL / partially superseded.** The *rationale* here (SQLAlchemy 2.0
> ORM not SQLModel; models + Pydantic DTOs, no dataclasses) still holds, but the
> **schema shown is pre-reframe** (old `todos`/`todo_updates` naming, fatter
> event table). **Current schema = [`../spec/DESIGN.md`](../spec/DESIGN.md) §3.**
>
> **Type: decision** (with rationale). Covers the SQL library choice and how the
> tables are represented in Python.

## Decision 1 — SQLAlchemy 2.0 ORM (not SQLModel)

**Chosen:** plain **SQLAlchemy 2.0** (ORM), with **SQLAlchemy Core / `select()`**
as an always-available escape hatch for hand-tuned queries. Alembic for
migrations. SQLite to start (engine confirmed at checkpoint 1b).

**Rejected: SQLModel** — it merges Pydantic + SQLAlchemy into one class (less
boilerplate) but is the **least transparent** option and **lags** SQLAlchemy/
Pydantic releases. The owner prefers **transparent SQL** and does query
optimization, so hiding the SQL is the wrong direction.

**Rationale (fits a SQL-fluent data-scientist owner):**
- SQLAlchemy 2.0's `select()` API maps closely to SQL and the emitted SQL is
  always inspectable (`echo=True`, `str(stmt)`) — the ORM never hides it.
- ORM change-tracking automates boring CRUD (add todo, tick item, edit event)
  without hand-written `UPDATE`s.
- For queries that matter (e.g. calendar date-range over events + due todos),
  drop to Core/`select()` for full control over joins/indexes — no need to fight
  the ORM.
- Standard, decoupled from FastAPI, tracks releases directly; Alembic pairs
  cleanly.

**Known ORM footguns to watch (the owner's SQL instinct is the mitigation):**
- **N+1 queries** — accessing a relationship inside a loop fires one query per
  row. Fix with eager loading / explicit joins. Catch it by reading emitted SQL.
- **Session / identity map** — stateful workspace between Python and the DB;
  learning curve on when it flushes/commits.

## Decision 2 — Python representation: SQLAlchemy models + Pydantic DTOs

**Two representations, each doing one job. No dataclasses.**

- **Persistence (DB ↔ Python):** **SQLAlchemy 2.0 ORM classes** — one per table
  (`Event`, `Todo`, `ChecklistItem`, `Family`, `Member`, `DeviceToken`). These
  *are* the data model in code, 1:1 with DESIGN §4.
- **API edge (JSON ↔ Python):** **Pydantic models** — request/response DTOs
  (e.g. `EventCreate`, `EventRead`), giving validation at the boundary.
- **Why not dataclasses:** a plain `@dataclass` is an in-memory struct with no
  persistence and no validation — you'd hand-write the row↔object mapping and
  validation the other two layers provide. It would be a redundant third
  representation. (Note: SQLAlchemy 2.0's `Mapped[...]` declarative style already
  *reads* dataclass-like, so you get the clean typed feel without giving up the
  ORM.)

> **⚠ Partially superseded (2026-08-30):** the **todo** half of this schema was
> reframed — todos are now a free-text item + an **append-only update log**
> (`todo_updates`), `due_at` is **LLM-inferred/confirmed** rather than core, and a
> labor-visibility purpose (R4) was added. See **`06-todo-updatelog-llm.md`** and
> `REQUIREMENTS_UPDATE.md`. The `events`, `families`, `members`, `device_tokens`
> tables and all the integrity/constraint guidance below **still stand**.

## Table → ORM model mapping (DESIGN §4) — fleshed out

Modern declarative style; `Mapped[...]` typed attributes. Timestamps stored UTC
(NFR-TIME); `families.timezone` required day-one. This is the **full target
schema** with constraints/integrity — tighter than the 1a–1c code subset already
built (see "Shipped subset vs. full model" below).

```python
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase): ...


# --- enums (stored as stable codes; display labels are presentation) ---------

class TodoStatus(str, enum.Enum):
    """Fixed Kanban columns (resolves OQ-COLS). Codes stored in DB; display
    labels live in the UI layer, so relabeling needs no migration."""
    todo = "todo"          # label: "Todo"
    on_deck = "on_deck"    # label: "On deck"
    doing = "doing"        # label: "Doing"
    done = "done"          # label: "Done"


class MemberRole(str, enum.Enum):
    adult = "adult"
    child = "child"        # future; schema-supported, not enforced day-one


# --- core tables -------------------------------------------------------------

class Family(Base):
    __tablename__ = "families"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    timezone: Mapped[str]                       # IANA tz, e.g. "America/New_York" (day-one, NFR-TIME)
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    display_name: Mapped[str]
    role: Mapped[MemberRole] = mapped_column(default=MemberRole.adult)
    phone_number: Mapped[str | None] = mapped_column(default=None)  # contact only, not auth (DESIGN §4.3)
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class DeviceToken(Base):
    __tablename__ = "device_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(unique=True)  # store hash, never the token (DESIGN §1.4)
    label: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)  # NULL = active


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_family_start", "family_id", "start_at"),  # calendar range query
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    location: Mapped[str | None] = mapped_column(default=None)

    # Timing — see "All-day events" note. all_day=False uses the UTC datetimes;
    # all_day=True uses the plain DATE fields (no timezone).
    all_day: Mapped[bool] = mapped_column(default=False)
    start_at: Mapped[datetime | None] = mapped_column(default=None)   # timed (UTC)
    end_at: Mapped[datetime | None] = mapped_column(default=None)
    start_date: Mapped[date | None] = mapped_column(default=None)     # all-day (no tz)
    end_date: Mapped[date | None] = mapped_column(default=None)

    # Attribution via the update record that drove this event (person/when/reason
    # live on that record — no person FK duplicated here). NULL for directly-
    # created or imported events (see notes).
    source_update_id: Mapped[int | None] = mapped_column(
        ForeignKey("todo_updates.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())


class Todo(Base):
    __tablename__ = "todos"
    __table_args__ = (
        Index("ix_todos_family_status_pos", "family_id", "status", "position"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)  # free text; loose by design
    status: Mapped[TodoStatus] = mapped_column(default=TodoStatus.todo)  # fixed enum; grooming snapshot
    position: Mapped[int]                        # order within (family, status) column
    due_at: Mapped[datetime | None] = mapped_column(default=None)  # LLM-inferred + confirmed (not core)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(default=None)  # entered Done
    archived_at: Mapped[datetime | None] = mapped_column(default=None)   # manual archive
    updates: Mapped[list[TodoUpdate]] = relationship(
        back_populates="todo", cascade="all, delete-orphan"
    )
    checklist: Mapped[list[ChecklistItem]] = relationship(
        back_populates="todo", cascade="all, delete-orphan"
    )


class TodoUpdate(Base):
    """Append-only update log — the primary daily interaction and source of
    narrative truth (F-TODO-13/14). Minimal by design: no type/metadata column."""
    __tablename__ = "todo_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    todo_id: Mapped[int] = mapped_column(ForeignKey("todos.id", ondelete="CASCADE"))
    author: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), default=None
    )  # who wrote it / who confirmed the LLM-driven outcome
    body: Mapped[str]                            # free text — human note OR narrated confirmed outcome
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    todo: Mapped[Todo] = relationship(back_populates="updates")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    todo_id: Mapped[int] = mapped_column(ForeignKey("todos.id", ondelete="CASCADE"))
    text: Mapped[str]
    checked: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int]
    todo: Mapped[Todo] = relationship(back_populates="checklist")
```

## Design notes (each ties to a requirement)

### Kanban status — fixed enum (resolves OQ-COLS)
Four fixed columns: **Todo / On deck / Doing / Done**. Stored as **codes**
(`todo`, `on_deck`, `doing`, `done`); display labels are UI-layer, so relabeling
needs no data migration. The SQLAlchemy `Enum` (+ a check constraint on Postgres)
prevents bad values. `position` orders cards within a `(family_id, status)`
column.

### Manual archive from Done (resolves OQ-DISP-DONE)
- **`todos.archived_at`** (nullable) is the archive axis — orthogonal to the
  status column, **not** a 5th column. `NULL` = on the board; set = archived
  (hidden from the board, retained in the DB for history).
- **Manual only.** Set by a user action during a periodic review — no scheduler,
  no background job, no new infrastructure. Two mutations: archive one Done card,
  and "archive all Done cards" (review convenience). Unarchive clears it.
- **App-level invariant:** only a `done` card may be archived (enforced in the
  mutation, not the schema — "archived ⇒ done" is awkward as a check constraint
  without over-constraining).
- `completed_at` (entered Done) is kept **distinct** from `archived_at` (swept in
  review): complete ≠ archived.
- Board query filters `WHERE archived_at IS NULL`.

### All-day events (NFR-TIME correctness)
An all-day event is a **date, not a UTC instant** — "birthday Sept 1" is not
"Sept 1 00:00 UTC" (that's the prior evening locally). So:
- **Timed events** (`all_day=False`): use `start_at`/`end_at` (UTC datetimes).
- **All-day events** (`all_day=True`): use `start_date`/`end_date` (plain dates,
  no timezone). Render against `families.timezone`.
This split avoids the classic off-by-one-day all-day bug. App-level invariant:
exactly one pair is populated per event, keyed by `all_day`.

### Recurrence — SCOPE DECISION: simple RRULE only for v1 (OQ-RECUR)
Store a bare `recurrence_rule` (RRULE) string only. **Per-instance exceptions
(`RECURRENCE-ID` / `EXDATE`) are explicitly out of scope for v1** — no schema for
"the Tuesday instance was moved/deleted." Consequence: the calendar view expands
RRULEs uniformly; you cannot yet edit a single occurrence. Revisit if a real need
appears (would add an `event_exceptions` table then). A conscious scope cut, not
an omission.

### Concurrency (§5.3, last-write-wins)
Both `events` and `todos` carry `sequence` (+ `updated_at` with `onupdate`).
`todos.sequence` is the fix for the concurrent-board-reorder case §5.3 named.
LWW resolution is app logic; the fields make it possible.

### Referential integrity (delete behavior)
- `family_id` → `CASCADE` (deleting a family removes its data; correct even if
  not a day-one operation).
- `checklist_items.todo_id` → `CASCADE` + ORM `delete-orphan`: deleting a card
  removes its checklist (no orphans).
- `created_by` / `assigned_to` → `SET NULL`: removing a member doesn't delete
  their events/todos, just unlinks attribution.
- `device_tokens.member_id` → `CASCADE`: removing a member revokes their devices.

### Indexes (performance, hot paths)
- `events(family_id, start_at)` — calendar range query.
- `todos(family_id, status, position)` — board render/order.
- `todos(family_id, due_at)` — the calendar/board bridge (due todos on calendar).

## Shipped subset vs. full model (for the coding agent)

The already-built, tested code (checkpoints 1a–1c) implements a **deliberately
minimal subset**: `Family` + `Event` with plain columns, no enums/constraints,
`created_by` as a bare int (members table didn't exist yet). That subset is
correct for 1a–1c and its tests pass.

**This section is the target.** When the remaining tables and constraints are
added (checkpoint 1b expansion / Phase 3), migrate toward this full schema
(enums, `uid` unique, `todos.sequence`, `archived_at`, all-day date fields,
cascade rules, indexes) via **Alembic migrations**, not by editing a live DB.

> **SQLite note:** SQLite enforces FKs only with `PRAGMA foreign_keys=ON` per
> connection, and enum/check enforcement is limited. Use SQLAlchemy `Enum` +
> constraints (portable if you later move to Postgres) and enable the pragma on
> connect. App-level invariants (archived⇒done, all-day pair) are enforced in
> mutations regardless of engine.

## Related decisions

- ORM library baseline/versions: `03-stack-libraries.md`.
- Timezone (`families.timezone` day-one), UTC storage: DESIGN §4.3 / NFR-TIME.
- `phone_number` is a contact field, not auth: DESIGN §4.3.
- Kanban columns + manual archive resolve OQ-COLS and OQ-DISP-DONE.

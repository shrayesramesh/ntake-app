"""DTO builders for data-layer tests (AWS_LLD §2/§8).

Terse constructors for the repository DTOs with sensible defaults, so a flow
test says ``make_work_item(status="done")`` instead of spelling out every field.
Ids default to short readable ULID-shaped strings (the real app mints true
ULIDs server-side; tests only need stable, unique, prefix-free strings).

These are **test support**, not production code — they live in the harness so
every data-layer session reuses them, and they are backend-agnostic (the same
DTOs feed the in-memory and, in Session 3, the DynamoDB repositories).
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime

from core.schemas import (
    Event,
    EventProvenance,
    Family,
    Member,
    WorkItem,
    WorkItemUpdate,
)

_counter = itertools.count(1)


def _ulid(prefix: str) -> str:
    """A stable, unique, prefix-free id token for tests (not a real ULID)."""
    return f"{prefix}{next(_counter):026d}"


def _now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_family(*, timezone: str = "America/New_York") -> Family:
    return Family(
        id=_ulid("fam"),
        name="Test Family",
        timezone=timezone,
        created_at=_now(),
    )


def make_member(
    family_id: str,
    *,
    display_name: str = "Alex",
    role: str = "adult",
) -> Member:
    return Member(
        id=_ulid("mem"),
        family_id=family_id,
        display_name=display_name,
        role=role,
        created_at=_now(),
    )


def make_work_item(
    family_id: str,
    *,
    title: str = "Buy milk",
    status: str = "todo",
    position: int = 0,
    assigned_to: str | None = None,
    due_at: datetime | None = None,
    tags: list[str] | None = None,
) -> WorkItem:
    now = _now()
    return WorkItem(
        id=_ulid("wi"),
        family_id=family_id,
        title=title,
        status=status,
        position=position,
        assigned_to=assigned_to,
        due_at=due_at,
        tags=tags or [],
        created_at=now,
        updated_at=now,
    )


def make_update(
    *,
    update_id: str | None = None,
    author_id: str | None = None,
    source: str = "human",
    body: str = "a note",
) -> WorkItemUpdate:
    return WorkItemUpdate(
        update_id=update_id or _ulid("upd"),
        author_id=author_id,
        source=source,
        body=body,
        created_at=_now(),
    )


def make_timed_event(
    family_id: str,
    *,
    title: str = "Dentist",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    provenance: EventProvenance | None = None,
    source_update_id: str | None = None,
) -> Event:
    now = _now()
    start = start_at or datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    return Event(
        id=_ulid("ev"),
        family_id=family_id,
        title=title,
        all_day=False,
        start_at=start,
        end_at=end_at or datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
        provenance=provenance,
        source_update_id=source_update_id,
        created_at=now,
        updated_at=now,
    )


def make_all_day_event(
    family_id: str,
    *,
    title: str = "Trip",
    start_date: date | None = None,
    end_date: date | None = None,
) -> Event:
    now = _now()
    start = start_date or date(2026, 2, 2)
    return Event(
        id=_ulid("ev"),
        family_id=family_id,
        title=title,
        all_day=True,
        start_date=start,
        end_date=end_date or start,
        created_at=now,
        updated_at=now,
    )


def seed_family(repo: object, family: Family, members: list[Member]) -> None:
    """Provision a family + its members into whatever backend ``repo`` is.

    Families and members are provisioned out-of-band of the ``Repository``
    protocol (there is no ``put_family``/``put_member`` — AWS_LLD §2.1, the
    minting/admin path owns member creation). Tests still need them seeded, so
    this harness helper does it **per-backend**, keeping the flow test body
    backend-agnostic:

    * ``InMemoryRepository`` exposes a ``seed_family`` provisioning method (an
      impl-only affordance, not part of the protocol) — call it directly.
    * ``DynamoRepository`` (Session 3) seeds via raw ``PutItem``\\s; wire that
      branch when the Dynamo impl lands.
    """
    seed = getattr(repo, "seed_family", None)
    if callable(seed):
        seed(family, members)
        return
    raise NotImplementedError(
        f"seed_family not wired for backend {type(repo).__name__} "
        "(DynamoRepository seeding arrives in Session 3)."
    )

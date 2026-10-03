"""The repository persistence seam (AWS_LLD §2).

The seat the SQLAlchemy ``Session`` used to hold on the action context (HLD §6):
a narrow interface the action handlers depend on, so the engine stays
persistence-ignorant (the boundary test forbids ``boto3`` there). Two
implementations satisfy the one :class:`Repository` ``Protocol`` — the
:class:`core.repository_memory.InMemoryRepository` (fast unit-test double, this
session) and the ``DynamoRepository`` (boto3 over the single table, Session 3).

This module also owns the **pure key/sort-derivation helpers** (``board_sort_key``,
``calendar_sort_ts``, and the ``FAM#``/``WI#``/``EV#`` prefix composers). They
live here — not inside ``DynamoRepository`` — so the one definition of how a
board position sorts and how an event's unified calendar instant is computed is
shared, unit-testable in isolation, and reused byte-for-byte by the Dynamo impl
in Session 3 (DRY: table-key knowledge has a single home). The in-memory impl
uses the same ``board_sort_key`` / ``calendar_sort_ts`` so both backends order
identically.

**No ``commit()``** (AWS_LLD §2.1): there is no deferred unit of work — each
method is one atomic DynamoDB op (or one ``TransactWriteItems`` for the two
cross-item methods). The HLD §6 "no unit-of-work interface" decision, concrete.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from core.schemas import (
    CalendarRow,
    Event,
    Family,
    Member,
    WorkItem,
    WorkItemUpdate,
)

# --- key / sort derivation (pure; the single source of table-key knowledge) ---

# Prefix convention (AWS_LLD §1.1): readability + collision-free. The DTOs carry
# prefix-free ULIDs; these composers add the type prefix at the key boundary.
FAM_PREFIX = "FAM#"
WI_PREFIX = "WI#"
EV_PREFIX = "EV#"
MEM_PREFIX = "MEM#"
CONN_PREFIX = "CONN#"

# Zero-pad board positions so string sort == numeric sort (AWS_LLD §1.2:
# GSI1SK = STATUS#<status>#POS#<zero-padded-position>). 6 digits covers a
# household's board far past any realistic column depth.
_POSITION_WIDTH = 6


def family_pk(family_id: str) -> str:
    """The partition key for everything under a family (AWS_LLD §1.1)."""
    return f"{FAM_PREFIX}{family_id}"


def work_item_sk(work_item_id: str) -> str:
    """The sort key of a work-item item under its family partition."""
    return f"{WI_PREFIX}{work_item_id}"


def event_sk(event_id: str) -> str:
    """The sort key of an event item under its family partition."""
    return f"{EV_PREFIX}{event_id}"


def member_sk(member_id: str) -> str:
    """The sort key of a member item under its family partition."""
    return f"{MEM_PREFIX}{member_id}"


def connection_sk(connection_id: str) -> str:
    """The sort key of a WebSocket-connection item under its family partition."""
    return f"{CONN_PREFIX}{connection_id}"


def board_sort_key(status: str, position: int) -> str:
    """The board GSI1 sort key: ``STATUS#<status>#POS#<zero-padded>`` (AWS_LLD §1.2).

    Status groups the column; the zero-padded position orders within it so a
    lexical sort of this key reproduces column-then-position order in one Query.
    """
    return f"STATUS#{status}#POS#{position:0{_POSITION_WIDTH}d}"


def calendar_sort_ts(event: Event, family_timezone: str) -> datetime:
    """The unified calendar instant an :class:`Event` sorts by (AWS_LLD §1.2).

    Timed events sort by their UTC ``start_at``; all-day events sort by
    **family-midnight expressed as a UTC instant** (so an all-day row lands on
    its local day, not a timezone-shifted neighbour). Returns a tz-aware UTC
    datetime; both stored timing fields are kept on the event for rendering.
    """
    if not event.all_day and event.start_at is not None:
        return to_utc(event.start_at)
    if event.all_day and event.start_date is not None:
        local_midnight = datetime.combine(event.start_date, time())
        # Reuse the one timezone mapper (DRY): round-trip local-midnight -> UTC.
        return _family_local_midnight_to_utc(local_midnight, family_timezone)
    # A malformed event (neither timing shape set) sorts at its creation instant
    # rather than raising into a read path.
    return to_utc(event.created_at)


def work_item_due_sort_ts(work_item: WorkItem) -> datetime | None:
    """The calendar instant a due-dated work item sorts by, or ``None``.

    A work item participates in the calendar Query only when it has a ``due_at``
    (AWS_LLD §1.2: the calendar/due-date bridge). Returns the UTC due instant, or
    ``None`` when the item has no due date (so it is absent from the calendar).
    """
    if work_item.due_at is None:
        return None
    return to_utc(work_item.due_at)


def to_utc(value: datetime) -> datetime:
    """Normalize a stored datetime to a tz-aware UTC instant.

    A tz-naive value is assumed to already be UTC (the storage convention,
    AWS_LLD preamble); an aware value is converted. Shared by both repository
    implementations so the two backends normalize timestamps identically.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _family_local_midnight_to_utc(local_midnight: datetime, timezone: str) -> datetime:
    """Map a family-local midnight wall time to its UTC instant.

    Attaches the family zone to the naive local midnight and converts to UTC, so
    an all-day event sorts on its local day rather than a timezone-shifted
    neighbour.
    """
    aware_local = local_midnight.replace(tzinfo=ZoneInfo(timezone))
    return aware_local.astimezone(UTC)


# --- the repository protocol (AWS_LLD §2.1) --------------------------------


@runtime_checkable
class Repository(Protocol):
    """The persistence seam the action handlers depend on (AWS_LLD §2.1).

    Method set derived from the action handlers (YAGNI — only what the handlers
    call). Reads return DTOs (or ``None`` on a miss); writes are void and atomic.
    The two cross-item methods (``create_event_from_update``) map to a
    ``TransactWriteItems`` in the Dynamo impl; everything else is one op.
    """

    # reads
    def get_work_item(self, family_id: str, work_item_id: str) -> WorkItem | None: ...
    def get_member(self, family_id: str, member_id: str) -> Member | None: ...
    def list_members(self, family_id: str) -> list[Member]: ...
    def get_event(self, family_id: str, event_id: str) -> Event | None: ...
    def list_board(self, family_id: str) -> dict[str, list[WorkItem]]: ...
    def list_calendar(
        self, family_id: str, frm: datetime, to: datetime
    ) -> list[CalendarRow]: ...
    def list_done_work_items(self, family_id: str) -> list[WorkItem]: ...
    def get_family(self, family_id: str) -> Family | None: ...

    # writes (intra-item -> UpdateItem; marked ones -> TransactWriteItems)
    def put_work_item(self, wi: WorkItem) -> None: ...
    def update_work_item(
        self, family_id: str, work_item_id: str, changes: dict
    ) -> None: ...
    def append_update(
        self, family_id: str, work_item_id: str, update: WorkItemUpdate
    ) -> None: ...
    def put_event(self, ev: Event) -> None: ...
    def update_event(self, family_id: str, event_id: str, changes: dict) -> None: ...
    def create_event_from_update(
        self, ev: Event, wi_log_entry: WorkItemUpdate
    ) -> None: ...
    def delete_event(self, family_id: str, event_id: str) -> None: ...
    def archive_work_item(self, family_id: str, work_item_id: str) -> None: ...

    # connections (live sync)
    def put_connection(
        self, family_id: str, connection_id: str, member_id: str
    ) -> None: ...
    def list_connections(self, family_id: str) -> list[str]: ...
    def delete_connection(self, family_id: str, connection_id: str) -> None: ...

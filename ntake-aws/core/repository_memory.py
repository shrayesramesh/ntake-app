"""The in-memory repository — the fast, networkless test double (AWS_LLD §2.2).

Satisfies the :class:`core.repository.Repository` ``Protocol`` with plain dicts,
replacing the old SQLite fixtures. It is the ``"memory"`` backend the parametrized
``repo`` fixture yields; the same flow tests run against ``DynamoRepository`` on
DynamoDB Local in Session 3.

Design notes:

* **Value semantics.** Reads return **deep copies** and writes **store copies**,
  so a caller mutating a returned DTO can't reach back into the store — matching
  DynamoDB's by-value item semantics (a ``GetItem`` hands you a fresh item). This
  keeps the two backends behaviourally interchangeable.
* **Shared ordering.** Board and calendar ordering reuse the pure
  ``board_sort_key`` / ``calendar_sort_ts`` / ``work_item_due_sort_ts`` helpers
  from :mod:`core.repository` — the one definition both backends sort by (DRY).
* **Family scoping.** Everything is keyed first by ``family_id`` (the partition
  dimension, HLD §6), so cross-family reads miss by construction.
* **Provisioning.** ``seed_family`` is an **impl-only** affordance (not on the
  protocol) for tests/fixtures to insert a family + members, which the real app
  provisions out-of-band via the minting/admin path (no ``put_family`` /
  ``put_member`` in the method set, AWS_LLD §2.1).
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from core.repository import (
    board_sort_key,
    calendar_sort_ts,
    to_utc,
    work_item_due_sort_ts,
)
from core.schemas import (
    BOARD_COLUMNS,
    CalendarKind,
    CalendarRow,
    Event,
    Family,
    Member,
    WorkItem,
    WorkItemStatus,
    WorkItemUpdate,
)


class InMemoryRepository:
    """Dict-backed :class:`core.repository.Repository` (unit-test double)."""

    def __init__(self) -> None:
        # family_id -> Family
        self._families: dict[str, Family] = {}
        # family_id -> {member_id -> Member}
        self._members: dict[str, dict[str, Member]] = {}
        # family_id -> {work_item_id -> WorkItem}
        self._work_items: dict[str, dict[str, WorkItem]] = {}
        # family_id -> {event_id -> Event}
        self._events: dict[str, dict[str, Event]] = {}
        # family_id -> {connection_id -> member_id}
        self._connections: dict[str, dict[str, str]] = {}

    # --- provisioning (impl-only; not part of the Repository protocol) ------

    def seed_family(self, family: Family, members: list[Member]) -> None:
        """Insert a family + its members (test/fixture provisioning)."""
        self._families[family.id] = copy.deepcopy(family)
        self._members[family.id] = {m.id: copy.deepcopy(m) for m in members}

    # --- reads --------------------------------------------------------------

    def get_work_item(self, family_id: str, work_item_id: str) -> WorkItem | None:
        wi = self._work_items.get(family_id, {}).get(work_item_id)
        return copy.deepcopy(wi) if wi is not None else None

    def get_member(self, family_id: str, member_id: str) -> Member | None:
        m = self._members.get(family_id, {}).get(member_id)
        return copy.deepcopy(m) if m is not None else None

    def list_members(self, family_id: str) -> list[Member]:
        return [copy.deepcopy(m) for m in self._members.get(family_id, {}).values()]

    def get_event(self, family_id: str, event_id: str) -> Event | None:
        ev = self._events.get(family_id, {}).get(event_id)
        return copy.deepcopy(ev) if ev is not None else None

    def list_board(self, family_id: str) -> dict[str, list[WorkItem]]:
        """Group unarchived items by column (BOARD_COLUMNS order), sorted within.

        Mirrors the sparse board GSI (AWS_LLD §1.2): archived items carry no GSI1
        key, so they are absent here; within a column, items are ordered by the
        shared ``board_sort_key`` (status then zero-padded position).
        """
        board: dict[str, list[WorkItem]] = {col: [] for col in BOARD_COLUMNS}
        items = [
            wi
            for wi in self._work_items.get(family_id, {}).values()
            if wi.archived_at is None and wi.status in board
        ]
        items.sort(key=lambda wi: board_sort_key(wi.status, wi.position))
        for wi in items:
            board[wi.status].append(copy.deepcopy(wi))
        return board

    def list_calendar(
        self, family_id: str, frm: datetime, to: datetime
    ) -> list[CalendarRow]:
        """Events + due-dated (unarchived) work items in [frm, to], time-ordered.

        One unified, time-sorted pass (AWS_LLD §1.2/§1.3): events sort by
        ``calendar_sort_ts`` (needing the family timezone for all-day), due items
        by ``work_item_due_sort_ts``. An archived work item carries no GSI2 key, so
        it leaves the calendar.
        """
        frm_utc, to_utc_bound = to_utc(frm), to_utc(to)
        tz = self._family_timezone(family_id)
        rows: list[tuple[datetime, CalendarRow]] = []

        for ev in self._events.get(family_id, {}).values():
            ts = calendar_sort_ts(ev, tz)
            if frm_utc <= ts <= to_utc_bound:
                rows.append(
                    (
                        ts,
                        CalendarRow(
                            id=ev.id,
                            kind=CalendarKind.EVENT,
                            title=ev.title,
                            sort_ts=ts,
                        ),
                    )
                )

        for wi in self._work_items.get(family_id, {}).values():
            if wi.archived_at is not None:
                continue
            due_ts = work_item_due_sort_ts(wi)
            if due_ts is not None and frm_utc <= due_ts <= to_utc_bound:
                rows.append(
                    (
                        due_ts,
                        CalendarRow(
                            id=wi.id,
                            kind=CalendarKind.WORK_ITEM,
                            title=wi.title,
                            sort_ts=due_ts,
                        ),
                    )
                )

        rows.sort(key=lambda pair: pair[0])
        return [row for _ts, row in rows]

    def list_done_work_items(self, family_id: str) -> list[WorkItem]:
        return [
            copy.deepcopy(wi)
            for wi in self._work_items.get(family_id, {}).values()
            if wi.status == WorkItemStatus.DONE and wi.archived_at is None
        ]

    def get_family(self, family_id: str) -> Family | None:
        fam = self._families.get(family_id)
        return copy.deepcopy(fam) if fam is not None else None

    # --- writes -------------------------------------------------------------

    def put_work_item(self, wi: WorkItem) -> None:
        self._work_items.setdefault(wi.family_id, {})[wi.id] = copy.deepcopy(wi)

    def update_work_item(
        self, family_id: str, work_item_id: str, changes: dict
    ) -> None:
        wi = self._require_work_item(family_id, work_item_id)
        for key, value in changes.items():
            setattr(wi, key, value)
        wi.updated_at = datetime.now(UTC)

    def append_update(
        self, family_id: str, work_item_id: str, update: WorkItemUpdate
    ) -> None:
        wi = self._require_work_item(family_id, work_item_id)
        wi.updates.append(copy.deepcopy(update))
        wi.updated_at = datetime.now(UTC)

    def put_event(self, ev: Event) -> None:
        self._events.setdefault(ev.family_id, {})[ev.id] = copy.deepcopy(ev)

    def update_event(self, family_id: str, event_id: str, changes: dict) -> None:
        ev = self._require_event(family_id, event_id)
        for key, value in changes.items():
            setattr(ev, key, value)
        ev.updated_at = datetime.now(UTC)

    def create_event_from_update(self, ev: Event, wi_log_entry: WorkItemUpdate) -> None:
        """Put the event AND append the work-item log entry — the cross-item pair.

        In DynamoDB this is one ``TransactWriteItems`` (event ``Put`` + work-item
        ``UpdateItem``); in memory both mutations simply apply together. The event
        carries the work item's id via its ``provenance.work_item_id``.
        """
        if ev.provenance is None:
            raise ValueError("create_event_from_update requires event.provenance")
        work_item_id = ev.provenance.work_item_id
        wi = self._require_work_item(ev.family_id, work_item_id)
        self._events.setdefault(ev.family_id, {})[ev.id] = copy.deepcopy(ev)
        wi.updates.append(copy.deepcopy(wi_log_entry))
        wi.updated_at = datetime.now(UTC)

    def delete_event(self, family_id: str, event_id: str) -> None:
        self._events.get(family_id, {}).pop(event_id, None)

    def archive_work_item(self, family_id: str, work_item_id: str) -> None:
        wi = self._require_work_item(family_id, work_item_id)
        now = datetime.now(UTC)
        wi.archived_at = now
        wi.updated_at = now

    # --- connections --------------------------------------------------------

    def put_connection(
        self, family_id: str, connection_id: str, member_id: str
    ) -> None:
        self._connections.setdefault(family_id, {})[connection_id] = member_id

    def list_connections(self, family_id: str) -> list[str]:
        return list(self._connections.get(family_id, {}).keys())

    def delete_connection(self, family_id: str, connection_id: str) -> None:
        self._connections.get(family_id, {}).pop(connection_id, None)

    # --- internals ----------------------------------------------------------

    def _require_work_item(self, family_id: str, work_item_id: str) -> WorkItem:
        wi = self._work_items.get(family_id, {}).get(work_item_id)
        if wi is None:
            raise KeyError(f"work item not found: {family_id}/{work_item_id}")
        return wi

    def _require_event(self, family_id: str, event_id: str) -> Event:
        ev = self._events.get(family_id, {}).get(event_id)
        if ev is None:
            raise KeyError(f"event not found: {family_id}/{event_id}")
        return ev

    def _family_timezone(self, family_id: str) -> str:
        """The family's timezone for all-day calendar sorting; UTC if unseeded.

        Tests that put events without seeding a family still get a stable sort
        (all-day sort falls back to a UTC day boundary).
        """
        fam = self._families.get(family_id)
        return fam.timezone if fam is not None else "UTC"

"""Tier-2: Dynamo-specific access-pattern tests (AWS_LLD §1).

Beyond the shared flow tests (which assert behavior at the ``Repository`` seam,
identically in-memory and on Dynamo), these pin the single-table mechanics that
*only* the real table can show: the sparse GSI1 board drop-out on archive, the
GSI2 range Query for the calendar, the co-created-event ``TransactWriteItems``
landing both sides atomically, and that a standalone event create is a single
``Put`` (not a transaction). Run only under ``make integration``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock

from adapters.dynamo_repository import DynamoRepository
from core.schemas import CalendarKind, EventProvenance
from tests.harness.factories import (
    make_family,
    make_member,
    make_timed_event,
    make_update,
    make_work_item,
    seed_family,
)


def test_sparse_gsi1_board_query_drops_archived(dynamo_repo: DynamoRepository) -> None:
    """GSI1 is sparse: an archived item carries no board key, so the board Query
    (not a filtered scan) simply doesn't return it."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    live = make_work_item(fam.id, title="live", status="todo", position=0)
    done = make_work_item(fam.id, title="to-archive", status="done", position=0)
    repo.put_work_item(live)
    repo.put_work_item(done)

    assert [w.title for w in repo.list_board(fam.id)["done"]] == ["to-archive"]
    repo.archive_work_item(fam.id, done.id)
    board = repo.list_board(fam.id)
    assert board["done"] == []
    assert [w.title for w in board["todo"]] == ["live"]
    # Still directly readable (archived, not deleted).
    assert repo.get_work_item(fam.id, done.id) is not None


def test_gsi2_calendar_range_query(dynamo_repo: DynamoRepository) -> None:
    """The calendar range Query over GSI2 returns only in-window rows, in time
    order, unifying events + due-dated work items in one pass."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    repo.put_event(
        make_timed_event(
            fam.id, title="in-early", start_at=datetime(2026, 2, 2, 9, 0, tzinfo=UTC)
        )
    )
    repo.put_event(
        make_timed_event(
            fam.id, title="out", start_at=datetime(2027, 1, 1, 9, 0, tzinfo=UTC)
        )
    )
    repo.put_work_item(
        make_work_item(
            fam.id, title="due-mid", due_at=datetime(2026, 2, 5, 17, 0, tzinfo=UTC)
        )
    )

    rows = repo.list_calendar(
        fam.id, datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)
    )
    assert [r.title for r in rows] == ["in-early", "due-mid"]
    kinds = {r.title: r.kind for r in rows}
    assert kinds["in-early"] == CalendarKind.EVENT
    assert kinds["due-mid"] == CalendarKind.WORK_ITEM


def test_co_created_event_transact_writes_both_sides(
    dynamo_repo: DynamoRepository,
) -> None:
    """create_event_from_update is one TransactWriteItems: the event Put and the
    work-item log append both land (or neither)."""
    repo = dynamo_repo
    fam = make_family()
    mem = make_member(fam.id, display_name="Alex")
    seed_family(repo, fam, [mem])
    wi = make_work_item(fam.id, title="plan party")
    repo.put_work_item(wi)

    log_entry = make_update(
        author_id=mem.id, source="assistant", body="Created calendar event: Party"
    )
    ev = make_timed_event(
        fam.id,
        title="Party",
        source_update_id=log_entry.update_id,
        provenance=EventProvenance(
            work_item_id=wi.id,
            member_id=mem.id,
            member_name=mem.display_name,
            note_snippet="plan party",
            at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        ),
    )
    repo.create_event_from_update(ev, log_entry)

    got_ev = repo.get_event(fam.id, ev.id)
    assert got_ev is not None and got_ev.source_update_id == log_entry.update_id
    got_wi = repo.get_work_item(fam.id, wi.id)
    assert got_wi is not None
    assert [u.body for u in got_wi.updates] == ["Created calendar event: Party"]


def test_standalone_event_create_is_a_single_put(
    dynamo_repo: DynamoRepository,
) -> None:
    """A standalone event create goes through one ``put_item`` and NO
    ``transact_write_items`` (the co-created path is the only transaction)."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])

    with (
        mock.patch.object(
            repo._table, "put_item", wraps=repo._table.put_item
        ) as put_spy,
        mock.patch.object(
            repo._table.meta.client,
            "transact_write_items",
            wraps=repo._table.meta.client.transact_write_items,
        ) as transact_spy,
    ):
        repo.put_event(make_timed_event(fam.id, title="standalone"))

    assert put_spy.call_count == 1
    assert transact_spy.call_count == 0

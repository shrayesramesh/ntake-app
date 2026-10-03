"""Tier-2: Dynamo-specific access-pattern tests (AWS_LLD §1), native + poll-based.

These pin the single-table mechanics that only the real table exercises — the
two GSIs, the sparse-archive drop-out, the unified calendar Query, the co-created
``TransactWriteItems``, and the single-``Put`` standalone create. Written
**natively** (not re-used from the shared bodies) because every GSI read is
**eventually consistent**: each assertion uses ``poll_until`` to converge on the
*exact* expected result, which is correct for both an item appearing and an item
dropping out — a blanket "retry until non-empty" cannot express the drop-out
(negative) cases.

Seeds are deliberately **rich** — several items across multiple board columns,
multiple interleaved events + due items, a family with members — so grouping,
ordering, and the sparse-index drop-out are genuinely demonstrated, not trivially
satisfied by a one-item fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest import mock

from adapters.dynamo_repository import DynamoRepository
from core.schemas import CalendarKind, EventProvenance
from tests.harness.factories import (
    make_all_day_event,
    make_family,
    make_member,
    make_timed_event,
    make_update,
    make_work_item,
    seed_family,
)


def _titles(rows: Any) -> list[str]:
    return [r.title for r in rows]


# --- GSI1 board: grouping + intra-column order + sparse-archive drop-out ----


def test_board_grouping_ordering_and_sparse_archive(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """A rich board (multiple columns, out-of-order positions) groups by column
    and orders within it via GSI1. (The sparse-archive drop-out is asserted
    directly against the index in
    ``test_gsi1_index_holds_board_keys_and_drops_on_archive``.)"""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    # Insert out of order across three columns to prove grouping + sort.
    repo.put_work_item(
        make_work_item(fam.id, title="todo-b", status="todo", position=1)
    )
    repo.put_work_item(
        make_work_item(fam.id, title="todo-a", status="todo", position=0)
    )
    repo.put_work_item(
        make_work_item(fam.id, title="doing-a", status="doing", position=0)
    )
    repo.put_work_item(
        make_work_item(fam.id, title="done-a", status="done", position=0)
    )

    board = poll_until(
        lambda: repo.list_board(fam.id),
        expected=(["todo-a", "todo-b"], ["doing-a"], ["done-a"]),
        key=lambda b: (_titles(b["todo"]), _titles(b["doing"]), _titles(b["done"])),
    )
    assert _titles(board["todo"]) == ["todo-a", "todo-b"]  # ordered by position
    assert _titles(board["doing"]) == ["doing-a"]
    assert _titles(board["done"]) == ["done-a"]
    assert board["on_deck"] == []


def test_list_done_work_items_excludes_archived(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """The done-column GSI1 Query returns done+unarchived items; archiving one
    drops it."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    d1 = make_work_item(fam.id, title="d1", status="done", position=0)
    d2 = make_work_item(fam.id, title="d2", status="done", position=1)
    repo.put_work_item(d1)
    repo.put_work_item(d2)
    repo.put_work_item(make_work_item(fam.id, title="t1", status="todo", position=0))

    done = poll_until(
        lambda: repo.list_done_work_items(fam.id),
        expected=["d1", "d2"],
        key=lambda rows: sorted(_titles(rows)),
    )
    assert sorted(_titles(done)) == ["d1", "d2"]

    repo.archive_work_item(fam.id, d1.id)
    done = poll_until(
        lambda: repo.list_done_work_items(fam.id),
        expected=["d2"],
        key=lambda rows: sorted(_titles(rows)),
    )
    assert sorted(_titles(done)) == ["d2"]


# --- GSI2 calendar: unified range Query, ordering, due-bridge, drop-out -----


def test_calendar_range_unifies_events_and_due_items_in_order(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """One GSI2 range Query returns in-window events + due-dated items together,
    time-ordered, and excludes out-of-window rows."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    repo.put_event(
        make_timed_event(
            fam.id, title="late-ev", start_at=datetime(2026, 2, 10, 9, 0, tzinfo=UTC)
        )
    )
    repo.put_event(
        make_timed_event(
            fam.id, title="early-ev", start_at=datetime(2026, 2, 2, 9, 0, tzinfo=UTC)
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

    window = (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
    rows = poll_until(
        lambda: repo.list_calendar(fam.id, *window),
        expected=["early-ev", "due-mid", "late-ev"],
        key=_titles,
    )
    assert _titles(rows) == ["early-ev", "due-mid", "late-ev"]
    kinds = {r.title: r.kind for r in rows}
    assert kinds["due-mid"] == CalendarKind.WORK_ITEM
    assert kinds["early-ev"] == CalendarKind.EVENT


def test_due_at_set_then_cleared_bridges_and_leaves_calendar(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """Setting due_at puts the item on the calendar (GSI2 due-bridge); clearing
    it removes the GSI2 key again."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    wi = make_work_item(fam.id, title="later-due")
    repo.put_work_item(wi)
    window = (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))

    repo.update_work_item(
        fam.id, wi.id, {"due_at": datetime(2026, 2, 5, 12, 0, tzinfo=UTC)}
    )
    rows = poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=["later-due"], key=_titles
    )
    assert _titles(rows) == ["later-due"]

    repo.update_work_item(fam.id, wi.id, {"due_at": None})
    rows = poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=[], key=_titles
    )
    assert _titles(rows) == []


def test_archive_drops_due_item_from_calendar(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """Archiving a due-dated item drops it from the calendar too (GSI2 sparse)."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    due = make_work_item(
        fam.id, title="due", status="done", due_at=datetime(2026, 2, 5, tzinfo=UTC)
    )
    repo.put_work_item(due)
    window = (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
    poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=["due"], key=_titles
    )

    repo.archive_work_item(fam.id, due.id)
    rows = poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=[], key=_titles
    )
    assert _titles(rows) == []


def test_all_day_event_appears_on_its_local_day(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """An all-day event sorts by family-midnight UTC (needs the family tz), so it
    lands on its local day, not a shifted neighbour."""
    repo = dynamo_repo
    fam = make_family(timezone="America/New_York")
    seed_family(repo, fam, [])
    repo.put_event(make_all_day_event(fam.id, title="holiday", start_date=None))
    window = (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 28, tzinfo=UTC))
    rows = poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=["holiday"], key=_titles
    )
    assert _titles(rows) == ["holiday"]


def test_delete_event_removes_it_from_calendar(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    ev = make_timed_event(fam.id, title="cancelled")
    repo.put_event(ev)
    window = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 12, 31, tzinfo=UTC))
    poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=["cancelled"], key=_titles
    )

    repo.delete_event(fam.id, ev.id)
    assert repo.get_event(fam.id, ev.id) is None
    rows = poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=[], key=_titles
    )
    assert _titles(rows) == []


def test_board_reads_are_scoped_to_family(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """GSI1 is partitioned by family — one family's board never sees another's."""
    repo = dynamo_repo
    fam_a = make_family()
    fam_b = make_family()
    seed_family(repo, fam_a, [])
    seed_family(repo, fam_b, [])
    repo.put_work_item(make_work_item(fam_a.id, title="a-item", status="todo"))
    repo.put_work_item(make_work_item(fam_b.id, title="b-item", status="todo"))

    board_a = poll_until(
        lambda: repo.list_board(fam_a.id),
        expected=["a-item"],
        key=lambda b: _titles(b["todo"]),
    )
    board_b = poll_until(
        lambda: repo.list_board(fam_b.id),
        expected=["b-item"],
        key=lambda b: _titles(b["todo"]),
    )
    assert _titles(board_a["todo"]) == ["a-item"]
    assert _titles(board_b["todo"]) == ["b-item"]


# --- raw GSI assertions: verify the INDEX directly, not via the repo reads ---
# These query GSI1/GSI2 straight through the table so the index is checked
# independently of list_board / list_calendar (whose own code could otherwise
# mask a missing-key bug symmetrically). This closes the transitive-verification
# gap: we assert the sparse keys literally exist / are absent in the index.


def _gsi_sks(repo: DynamoRepository, index: str, pk_attr: str, pk_value: str) -> Any:
    """All sort-key values currently in ``index`` under ``pk_value`` (raw query)."""
    from boto3.dynamodb.conditions import Key

    sk_attr = "GSI1SK" if index == "GSI1" else "GSI2SK"
    resp = repo._table.query(
        IndexName=index, KeyConditionExpression=Key(pk_attr).eq(pk_value)
    )
    return sorted(i[sk_attr] for i in resp.get("Items", []))


def test_gsi1_index_holds_board_keys_and_drops_on_archive(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """GSI1 itself carries ``STATUS#…#POS#…`` for an unarchived item and loses it
    on archive — asserted by querying the index directly."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    wi = make_work_item(fam.id, title="x", status="doing", position=3)
    repo.put_work_item(wi)
    gsi1pk = f"FAM#{fam.id}#BOARD"

    keys = poll_until(
        lambda: _gsi_sks(repo, "GSI1", "GSI1PK", gsi1pk),
        expected=["STATUS#doing#POS#000003"],
    )
    assert keys == ["STATUS#doing#POS#000003"]  # exact sort-key shape in the index

    repo.archive_work_item(fam.id, wi.id)
    keys = poll_until(lambda: _gsi_sks(repo, "GSI1", "GSI1PK", gsi1pk), expected=[])
    assert keys == []  # the sparse key is gone from the index entirely


def test_gsi2_index_holds_event_and_due_keys_and_drops_them(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """GSI2 itself carries a ``TS#…#EV#`` key for an event and a ``TS#…#WI#`` key
    for a due-dated item; deleting the event and clearing the due date remove
    them — asserted by querying the index directly."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    ev = make_timed_event(
        fam.id, title="ev", start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    )
    due = make_work_item(
        fam.id, title="due", due_at=datetime(2026, 2, 5, 12, 0, tzinfo=UTC)
    )
    repo.put_event(ev)
    repo.put_work_item(due)
    gsi2pk = f"FAM#{fam.id}#CAL"

    keys = poll_until(
        lambda: _gsi_sks(repo, "GSI2", "GSI2PK", gsi2pk),
        expected=[
            f"TS#2026-02-01T09:00:00.000000Z#EV#{ev.id}",
            f"TS#2026-02-05T12:00:00.000000Z#WI#{due.id}",
        ],
    )
    assert keys == [
        f"TS#2026-02-01T09:00:00.000000Z#EV#{ev.id}",
        f"TS#2026-02-05T12:00:00.000000Z#WI#{due.id}",
    ]

    repo.delete_event(fam.id, ev.id)
    repo.update_work_item(fam.id, due.id, {"due_at": None})
    keys = poll_until(lambda: _gsi_sks(repo, "GSI2", "GSI2PK", gsi2pk), expected=[])
    assert keys == []  # both sparse calendar keys removed from the index


# --- cross-item + single-op write shapes -----------------------------------


def test_co_created_event_transact_writes_both_sides(
    dynamo_repo: DynamoRepository,
) -> None:
    """create_event_from_update is one TransactWriteItems: the event Put and the
    work-item log append both land (base-table reads → strongly consistent, no
    poll needed)."""
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
            repo._ddb,
            "transact_write_items",
            wraps=repo._ddb.transact_write_items,
        ) as transact_spy,
    ):
        repo.put_event(make_timed_event(fam.id, title="standalone"))

    assert put_spy.call_count == 1
    assert transact_spy.call_count == 0

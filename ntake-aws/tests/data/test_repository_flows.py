"""Integration-first flow tests for the ``Repository`` seam (AWS_LLD §2/§8).

Written against the :class:`core.repository.Repository` **protocol** via the
parametrized ``repo`` fixture — so each flow runs against ``InMemoryRepository``
now and, **unchanged**, against ``DynamoRepository`` on DynamoDB Local in
Session 3 (the DRY backbone: one test body, two backends). They drive whole
flows end to end (create -> mutate -> read back the aggregate), asserting
behavior at the seam, not implementation detail.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.repository import Repository
from core.schemas import CalendarKind, EventProvenance, WorkItemStatus
from tests.harness.factories import (
    make_all_day_event,
    make_family,
    make_member,
    make_timed_event,
    make_update,
    make_work_item,
    seed_family,
)


def test_repo_satisfies_the_protocol(repo: Repository) -> None:
    """The fixture's backend is a structural ``Repository`` (runtime check)."""
    assert isinstance(repo, Repository)


# --- work item: create -> append update -> read back the aggregate ---------


def test_create_append_update_read_back_aggregate(repo: Repository) -> None:
    fam = make_family()
    wi = make_work_item(fam.id, title="Taxes")
    repo.put_work_item(wi)

    human = make_update(source="human", body="started gathering forms")
    assistant = make_update(source="assistant", body="Set due date to Apr 15")
    repo.append_update(fam.id, wi.id, human)
    repo.append_update(fam.id, wi.id, assistant)

    got = repo.get_work_item(fam.id, wi.id)
    assert got is not None
    assert got.title == "Taxes"
    # The co-located aggregate carries its log, in append order (AWS_LLD §1.2).
    assert [u.body for u in got.updates] == [
        "started gathering forms",
        "Set due date to Apr 15",
    ]
    assert [u.source for u in got.updates] == ["human", "assistant"]


def test_get_work_item_miss_returns_none(repo: Repository) -> None:
    fam = make_family()
    assert repo.get_work_item(fam.id, "nope") is None


def test_update_work_item_applies_changes(repo: Repository) -> None:
    fam = make_family()
    wi = make_work_item(fam.id, status="todo", position=0)
    repo.put_work_item(wi)

    repo.update_work_item(
        fam.id, wi.id, {"status": "doing", "position": 2, "title": "Renamed"}
    )

    got = repo.get_work_item(fam.id, wi.id)
    assert got is not None
    assert got.status == "doing" and got.position == 2 and got.title == "Renamed"


# --- board: grouping + ordering (AWS_LLD §1.2, §1.3) -----------------------


def test_list_board_groups_by_column_and_orders_by_position(
    repo: Repository,
) -> None:
    fam = make_family()
    # Insert out of order across columns to prove grouping + intra-column sort.
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

    board = repo.list_board(fam.id)

    # Every column present, in BOARD_COLUMNS order.
    assert list(board.keys()) == [s.value for s in WorkItemStatus]
    # Todo column ordered by position.
    assert [wi.title for wi in board["todo"]] == ["todo-a", "todo-b"]
    assert [wi.title for wi in board["doing"]] == ["doing-a"]
    assert [wi.title for wi in board["done"]] == ["done-a"]
    assert board["on_deck"] == []


def test_board_excludes_archived_items(repo: Repository) -> None:
    """Archiving drops the item from the board (sparse GSI1, AWS_LLD §1.2)."""
    fam = make_family()
    wi = make_work_item(fam.id, title="done-item", status="done", position=0)
    repo.put_work_item(wi)
    assert [w.title for w in repo.list_board(fam.id)["done"]] == ["done-item"]

    repo.archive_work_item(fam.id, wi.id)

    assert repo.list_board(fam.id)["done"] == []
    # Archived item still readable directly (never deleted, only archived).
    got = repo.get_work_item(fam.id, wi.id)
    assert got is not None and got.archived_at is not None


def test_list_done_work_items(repo: Repository) -> None:
    fam = make_family()
    repo.put_work_item(make_work_item(fam.id, title="d1", status="done", position=0))
    repo.put_work_item(make_work_item(fam.id, title="d2", status="done", position=1))
    repo.put_work_item(make_work_item(fam.id, title="t1", status="todo", position=0))

    done = repo.list_done_work_items(fam.id)

    assert sorted(wi.title for wi in done) == ["d1", "d2"]


def test_archived_done_item_excluded_from_list_done(repo: Repository) -> None:
    fam = make_family()
    wi = make_work_item(fam.id, title="d1", status="done", position=0)
    repo.put_work_item(wi)
    repo.archive_work_item(fam.id, wi.id)
    assert repo.list_done_work_items(fam.id) == []


# --- events: put standalone -> list calendar range -------------------------


def test_put_event_then_list_calendar_in_range(repo: Repository) -> None:
    fam = make_family()
    ev = make_timed_event(
        fam.id,
        title="Dentist",
        start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
    )
    repo.put_event(ev)

    rows = repo.list_calendar(
        fam.id,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )

    assert len(rows) == 1
    assert rows[0].id == ev.id
    assert rows[0].kind == CalendarKind.EVENT
    assert rows[0].title == "Dentist"


def test_calendar_range_excludes_out_of_window_events(repo: Repository) -> None:
    fam = make_family()
    inside = make_timed_event(
        fam.id, title="in", start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    )
    before = make_timed_event(
        fam.id, title="before", start_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC)
    )
    after = make_timed_event(
        fam.id, title="after", start_at=datetime(2027, 1, 1, 9, 0, tzinfo=UTC)
    )
    for ev in (inside, before, after):
        repo.put_event(ev)

    rows = repo.list_calendar(
        fam.id,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert [r.title for r in rows] == ["in"]


def test_calendar_orders_events_and_due_items_by_time(repo: Repository) -> None:
    """Events + due-dated work items return in one time-ordered pass (§1.2)."""
    fam = make_family()
    ev_late = make_timed_event(
        fam.id, title="late-ev", start_at=datetime(2026, 2, 10, 9, 0, tzinfo=UTC)
    )
    ev_early = make_timed_event(
        fam.id, title="early-ev", start_at=datetime(2026, 2, 2, 9, 0, tzinfo=UTC)
    )
    repo.put_event(ev_late)
    repo.put_event(ev_early)
    # A due-dated work item bridges onto the calendar between the two events.
    due = make_work_item(
        fam.id, title="due-mid", due_at=datetime(2026, 2, 5, 17, 0, tzinfo=UTC)
    )
    repo.put_work_item(due)

    rows = repo.list_calendar(
        fam.id,
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )

    assert [r.title for r in rows] == ["early-ev", "due-mid", "late-ev"]
    kinds = {r.title: r.kind for r in rows}
    assert kinds["due-mid"] == CalendarKind.WORK_ITEM
    assert kinds["early-ev"] == CalendarKind.EVENT


def test_all_day_event_appears_on_its_local_day(repo: Repository) -> None:
    """An all-day event sorts by family-midnight UTC, not a shifted neighbour."""
    fam = make_family(timezone="America/New_York")
    ev = make_all_day_event(fam.id, title="holiday", start_date=None)
    repo.put_event(ev)

    rows = repo.list_calendar(
        fam.id,
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 2, 28, tzinfo=UTC),
    )
    assert [r.title for r in rows] == ["holiday"]


def test_delete_event_removes_it_from_calendar(repo: Repository) -> None:
    fam = make_family()
    ev = make_timed_event(fam.id, title="cancelled")
    repo.put_event(ev)
    repo.delete_event(fam.id, ev.id)

    assert repo.get_event(fam.id, ev.id) is None
    rows = repo.list_calendar(
        fam.id,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 12, 31, tzinfo=UTC),
    )
    assert rows == []


def test_due_item_leaves_calendar_when_archived(repo: Repository) -> None:
    """Archiving a due-dated item drops it from the calendar too (§1.2)."""
    fam = make_family()
    due = make_work_item(
        fam.id, title="due", status="done", due_at=datetime(2026, 2, 5, tzinfo=UTC)
    )
    repo.put_work_item(due)
    repo.archive_work_item(fam.id, due.id)

    rows = repo.list_calendar(
        fam.id,
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert rows == []


def test_update_work_item_due_at_bridges_onto_calendar(repo: Repository) -> None:
    """Setting due_at via update_work_item puts the item on the calendar (§1.2)."""
    fam = make_family()
    wi = make_work_item(fam.id, title="later-due")
    repo.put_work_item(wi)
    window = (
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert repo.list_calendar(fam.id, *window) == []

    repo.update_work_item(
        fam.id, wi.id, {"due_at": datetime(2026, 2, 5, 12, 0, tzinfo=UTC)}
    )
    rows = repo.list_calendar(fam.id, *window)
    assert [r.title for r in rows] == ["later-due"]

    # Clearing due_at removes it again.
    repo.update_work_item(fam.id, wi.id, {"due_at": None})
    assert repo.list_calendar(fam.id, *window) == []


def test_update_event_reschedules_in_calendar(repo: Repository) -> None:
    fam = make_family()
    ev = make_timed_event(
        fam.id, title="movable", start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    )
    repo.put_event(ev)
    repo.update_event(
        fam.id, ev.id, {"start_at": datetime(2026, 5, 1, 9, 0, tzinfo=UTC)}
    )

    feb = repo.list_calendar(
        fam.id, datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 28, tzinfo=UTC)
    )
    may = repo.list_calendar(
        fam.id, datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 5, 31, tzinfo=UTC)
    )
    assert feb == []
    assert [r.title for r in may] == ["movable"]


# --- cross-item: create_event_from_update (TransactWriteItems in Dynamo) ----


def test_create_event_from_update_writes_event_and_logs(repo: Repository) -> None:
    fam = make_family()
    mem = make_member(fam.id, display_name="Alex")
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

    # Both sides of the atomic pair landed: the event exists...
    got_ev = repo.get_event(fam.id, ev.id)
    assert got_ev is not None and got_ev.provenance is not None
    assert got_ev.provenance.work_item_id == wi.id
    assert got_ev.source_update_id == log_entry.update_id
    # ...and the work item's log gained the assistant entry.
    got_wi = repo.get_work_item(fam.id, wi.id)
    assert got_wi is not None
    assert [u.body for u in got_wi.updates] == ["Created calendar event: Party"]


# --- members + family ------------------------------------------------------


def test_members_and_family_reads(repo: Repository) -> None:
    fam = make_family()
    # Families/members are provisioned out-of-band (the minting/admin path), so
    # there is no put_member/put_family on the Repository protocol (AWS_LLD §2.1).
    # The harness seeds them per-backend (``seed_family``) so this flow stays
    # backend-agnostic — in-memory now, DynamoDB raw-put in Session 3.
    alex = make_member(fam.id, display_name="Alex")
    sam = make_member(fam.id, display_name="Sam")
    seed_family(repo, fam, [alex, sam])

    got_family = repo.get_family(fam.id)
    assert got_family is not None and got_family.name == "Test Family"
    members = repo.list_members(fam.id)
    assert sorted(m.display_name for m in members) == ["Alex", "Sam"]
    assert repo.get_member(fam.id, alex.id) is not None
    assert repo.get_member(fam.id, "missing") is None


# --- connections (live sync) -----------------------------------------------


def test_connection_lifecycle(repo: Repository) -> None:
    fam = make_family()
    repo.put_connection(fam.id, "conn-1", "mem-1")
    repo.put_connection(fam.id, "conn-2", "mem-2")
    assert sorted(repo.list_connections(fam.id)) == ["conn-1", "conn-2"]

    repo.delete_connection(fam.id, "conn-1")
    assert repo.list_connections(fam.id) == ["conn-2"]


# --- family-scoping (the partition boundary, HLD §6) -----------------------


def test_reads_are_scoped_to_family(repo: Repository) -> None:
    fam_a = make_family()
    fam_b = make_family()
    wi_a = make_work_item(fam_a.id, title="a-item", status="todo")
    wi_b = make_work_item(fam_b.id, title="b-item", status="todo")
    repo.put_work_item(wi_a)
    repo.put_work_item(wi_b)

    assert repo.get_work_item(fam_a.id, wi_b.id) is None
    assert [w.title for w in repo.list_board(fam_a.id)["todo"]] == ["a-item"]
    assert [w.title for w in repo.list_board(fam_b.id)["todo"]] == ["b-item"]

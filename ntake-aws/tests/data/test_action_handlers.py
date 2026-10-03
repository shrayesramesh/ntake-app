"""Handler flow tests — the ported action handlers over the ``Repository`` seam.

Session 3 brought the six formerly-parked action modules back under the gate
(AWS_LLD §2). These tests drive the handlers end to end through
``core.actions.registry.apply_action`` against the in-memory repository (Tier 1,
no network): confirm → repository write → read-back, asserting behavior at the
seam. They cover the fidelity rules from the Session-2 hand-off — ``KeyError`` →
``ActionError`` translation, the co-created-event ``create_event_from_update``
pairing, and the handler-level ``archive_all_done`` / checklist loops — plus the
member-whitelist validation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.actions.registry import apply_action
from core.engine.engine import ActionError
from core.repository_memory import InMemoryRepository
from core.schemas import Member, TargetType, WorkItemStatus
from tests.harness.factories import (
    make_family,
    make_member,
    make_timed_event,
    make_work_item,
    seed_family,
)


def _repo_with_family() -> tuple[InMemoryRepository, str, Member]:
    """A seeded in-memory repo + the family id + the confirming member."""
    repo = InMemoryRepository()
    fam = make_family(timezone="America/New_York")
    member = make_member(fam.id, display_name="Alex")
    seed_family(repo, fam, [member])
    return repo, fam.id, member


# --- create / read-back ----------------------------------------------------


def test_create_work_item_persists_and_logs() -> None:
    repo, fam_id, member = _repo_with_family()
    summary = apply_action(
        repo,
        member,
        "create_work_item",
        None,
        {"title": "Taxes", "tags": ["finance"]},
    )
    assert summary == "Created work item: Taxes"

    board = repo.list_board(fam_id)
    [created] = board[WorkItemStatus.TODO]
    assert created.title == "Taxes"
    assert created.tags == ["finance"]
    # The create appended an assistant log entry (the labor record).
    got = repo.get_work_item(fam_id, created.id)
    assert got is not None
    assert [u.source for u in got.updates] == ["assistant"]
    assert got.updates[0].author_id == member.id


def test_create_work_item_with_checklist() -> None:
    repo, fam_id, member = _repo_with_family()
    apply_action(
        repo,
        member,
        "create_work_item",
        None,
        {"title": "Groceries", "checklist_items": ["milk", "eggs"]},
    )
    [wi] = repo.list_board(fam_id)[WorkItemStatus.TODO]
    got = repo.get_work_item(fam_id, wi.id)
    assert got is not None
    assert [(c.text, c.position) for c in got.checklist] == [("milk", 1), ("eggs", 2)]


# --- status transitions + due date -----------------------------------------


def test_complete_then_reopen() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="chore", status="todo")
    repo.put_work_item(wi)

    apply_action(repo, member, "complete_work_item", wi.id, {})
    got = repo.get_work_item(fam_id, wi.id)
    assert got is not None and got.status == WorkItemStatus.DONE
    assert got.completed_at is not None

    apply_action(repo, member, "reopen_work_item", wi.id, {})
    got = repo.get_work_item(fam_id, wi.id)
    assert got is not None and got.status == WorkItemStatus.TODO
    assert got.completed_at is None


def test_set_due_date_bridges_onto_calendar() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="file taxes")
    repo.put_work_item(wi)

    apply_action(
        repo, member, "set_due_date", wi.id, {"local_due_at": "2026-04-15T17:00"}
    )
    rows = repo.list_calendar(
        fam_id, datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 30, tzinfo=UTC)
    )
    assert [r.title for r in rows] == ["file taxes"]


def test_assign_validates_member_in_family() -> None:
    repo = InMemoryRepository()
    fam = make_family()
    member = make_member(fam.id, display_name="Alex")
    sam = make_member(fam.id, display_name="Sam")
    seed_family(repo, fam, [member, sam])
    wi = make_work_item(fam.id, title="dishes")
    repo.put_work_item(wi)

    summary = apply_action(
        repo, member, "assign_work_item", wi.id, {"member_id": sam.id}
    )
    assert summary == "Assigned to Sam"
    got = repo.get_work_item(fam.id, wi.id)
    assert got is not None and got.assigned_to == sam.id


def test_assign_rejects_unknown_member() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="dishes")
    repo.put_work_item(wi)
    with pytest.raises(ActionError, match="member not in family"):
        apply_action(repo, member, "assign_work_item", wi.id, {"member_id": "nope"})


# --- KeyError -> ActionError translation (the Session-2 fidelity rule) ------


def test_missing_target_translates_to_action_error() -> None:
    repo, fam_id, member = _repo_with_family()
    with pytest.raises(ActionError, match="work item not found"):
        apply_action(repo, member, "complete_work_item", "ghost", {})


def test_missing_event_target_translates_to_action_error() -> None:
    repo, fam_id, member = _repo_with_family()
    with pytest.raises(ActionError, match="event not found"):
        apply_action(
            repo,
            member,
            "set_event_location",
            "ghost",
            {"location": "home"},
            TargetType.EVENT,
        )


# --- archive + archive-all-done (handler-level loop) ------------------------


def test_archive_only_done_item() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="not done", status="todo")
    repo.put_work_item(wi)
    with pytest.raises(ActionError, match="only a done work item"):
        apply_action(repo, member, "archive_work_item", wi.id, {})


def test_archive_all_done_loops_over_done_items() -> None:
    repo, fam_id, member = _repo_with_family()
    for i in range(3):
        repo.put_work_item(
            make_work_item(fam_id, title=f"d{i}", status="done", position=i)
        )
    repo.put_work_item(make_work_item(fam_id, title="t", status="todo"))

    summary = apply_action(repo, member, "archive_all_done", None, {})
    assert summary == "Archived 3 done work items"
    assert repo.list_board(fam_id)[WorkItemStatus.DONE] == []
    assert len(repo.list_board(fam_id)[WorkItemStatus.TODO]) == 1


# --- checklist add + check-off (handler-level loops) ------------------------


def test_add_then_check_off_checklist_items() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="party prep")
    repo.put_work_item(wi)

    apply_action(
        repo, member, "add_checklist_items", wi.id, {"items": ["cake", "balloons"]}
    )
    got = repo.get_work_item(fam_id, wi.id)
    assert got is not None
    assert [c.text for c in got.checklist] == ["cake", "balloons"]

    apply_action(repo, member, "check_off_items", wi.id, {"items": ["cake"]})
    got = repo.get_work_item(fam_id, wi.id)
    assert got is not None
    checked = {c.text: c.checked for c in got.checklist}
    assert checked == {"cake": True, "balloons": False}


def test_check_off_unknown_item_raises() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="prep")
    repo.put_work_item(wi)
    apply_action(repo, member, "add_checklist_items", wi.id, {"items": ["cake"]})
    with pytest.raises(ActionError, match="checklist items not found"):
        apply_action(repo, member, "check_off_items", wi.id, {"items": ["ghost"]})


# --- events: standalone create (single Put) vs co-created (transact) --------


def test_create_timed_event_standalone_no_work_item_log() -> None:
    repo, fam_id, member = _repo_with_family()
    summary = apply_action(
        repo,
        member,
        "create_timed_event",
        None,
        {
            "title": "Dentist",
            "local_start_at": "2026-02-01T09:00",
            "local_end_at": "2026-02-01T10:00",
        },
    )
    assert summary == "Created event: Dentist"
    rows = repo.list_calendar(
        fam_id, datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 2, tzinfo=UTC)
    )
    assert [r.title for r in rows] == ["Dentist"]


def test_create_event_from_work_item_co_creates_and_logs() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="plan party")
    repo.put_work_item(wi)

    summary = apply_action(
        repo,
        member,
        "create_all_day_event",
        wi.id,
        {"title": "Party", "start_date": "2026-03-01"},
        TargetType.WORK_ITEM,
    )
    assert summary == "Created event: Party"

    # The work item gained an assistant log entry (the labor link)...
    got = repo.get_work_item(fam_id, wi.id)
    assert got is not None
    assert [u.body for u in got.updates] == ["Created calendar event: Party"]
    source_update_id = got.updates[0].update_id

    # ...and the event carries provenance + the backlink to that log entry.
    rows = repo.list_calendar(
        fam_id, datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)
    )
    [row] = rows
    ev = repo.get_event(fam_id, row.id)
    assert ev is not None and ev.provenance is not None
    assert ev.provenance.work_item_id == wi.id
    assert ev.provenance.member_name == "Alex"
    assert ev.source_update_id == source_update_id


def test_reschedule_and_delete_event() -> None:
    repo, fam_id, member = _repo_with_family()
    ev = make_timed_event(
        fam_id, title="movable", start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    )
    repo.put_event(ev)

    apply_action(
        repo,
        member,
        "reschedule_timed_event",
        ev.id,
        {"local_start_at": "2026-05-01T09:00", "local_end_at": "2026-05-01T10:00"},
        TargetType.EVENT,
    )
    may = repo.list_calendar(
        fam_id, datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 5, 2, tzinfo=UTC)
    )
    assert [r.title for r in may] == ["movable"]

    apply_action(repo, member, "delete_event", ev.id, {}, TargetType.EVENT)
    assert repo.get_event(fam_id, ev.id) is None


# --- meta + unknown-name + family-not-found --------------------------------


def test_no_action_dispatches() -> None:
    repo, fam_id, member = _repo_with_family()
    assert apply_action(repo, member, "no_action", None, {}) == "No action"


def test_unknown_action_raises() -> None:
    repo, fam_id, member = _repo_with_family()
    with pytest.raises(ActionError, match="unknown action"):
        apply_action(repo, member, "frobnicate", None, {})


def test_family_not_found_raises() -> None:
    repo = InMemoryRepository()
    orphan = make_member("fam-missing", display_name="Nobody")
    with pytest.raises(ActionError, match="family not found"):
        apply_action(repo, orphan, "no_action", None, {})


# --- remaining work-item handlers (status moves, tags, append) -------------


def test_status_moves_and_append_and_tags() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="chore", status="todo")
    repo.put_work_item(wi)

    assert apply_action(repo, member, "start_work_item", wi.id, {}) == "Started work"
    assert repo.get_work_item(fam_id, wi.id).status == WorkItemStatus.DOING  # type: ignore[union-attr]

    assert (
        apply_action(repo, member, "move_to_on_deck", wi.id, {}) == "Moved to On deck"
    )
    assert repo.get_work_item(fam_id, wi.id).status == WorkItemStatus.ON_DECK  # type: ignore[union-attr]

    assert apply_action(repo, member, "move_to_todo", wi.id, {}) == "Moved to Todo"
    assert repo.get_work_item(fam_id, wi.id).status == WorkItemStatus.TODO  # type: ignore[union-attr]

    assert (
        apply_action(repo, member, "append_update", wi.id, {"body": "a note"})
        == "Appended work-item update"
    )

    note = apply_action(
        repo, member, "set_work_item_tags", wi.id, {"tags": ["home", "home", "Errand"]}
    )
    assert note == "Set tags: home, Errand"  # de-duped, first spelling kept
    got = repo.get_work_item(fam_id, wi.id)
    assert got is not None and got.tags == ["home", "Errand"]


def test_set_work_item_tags_rejects_non_list() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="chore")
    repo.put_work_item(wi)
    with pytest.raises(ActionError, match="tags must be a list"):
        apply_action(repo, member, "set_work_item_tags", wi.id, {"tags": "nope"})


def test_archive_work_item_drops_off_board() -> None:
    repo, fam_id, member = _repo_with_family()
    wi = make_work_item(fam_id, title="done-item", status="done")
    repo.put_work_item(wi)
    assert apply_action(repo, member, "archive_work_item", wi.id, {}) == "Archived"
    assert repo.list_board(fam_id)[WorkItemStatus.DONE] == []


# --- remaining event handlers (location, participants, tags, deconflict) ---


def test_event_location_participants_tags_and_deconflict() -> None:
    repo, fam_id, member = _repo_with_family()
    ev = make_timed_event(
        fam_id, title="meet", start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    )
    repo.put_event(ev)

    assert (
        apply_action(
            repo,
            member,
            "set_event_location",
            ev.id,
            {"location": "Park"},
            TargetType.EVENT,
        )
        == "Set event location to Park"
    )
    assert repo.get_event(fam_id, ev.id).location == "Park"  # type: ignore[union-attr]

    apply_action(
        repo,
        member,
        "add_event_participants",
        ev.id,
        {"participants": ["Alex", "Sam"]},
        TargetType.EVENT,
    )
    got = repo.get_event(fam_id, ev.id)
    assert got is not None and got.participants == ["Alex", "Sam"]

    apply_action(
        repo, member, "set_event_tags", ev.id, {"tags": ["school"]}, TargetType.EVENT
    )
    assert repo.get_event(fam_id, ev.id).tags == ["school"]  # type: ignore[union-attr]

    apply_action(repo, member, "deconflict_events", ev.id, {}, TargetType.EVENT)
    got = repo.get_event(fam_id, ev.id)
    assert got is not None and got.start_at == datetime(2026, 2, 2, 9, 0, tzinfo=UTC)


def test_reschedule_all_day_event() -> None:
    repo, fam_id, member = _repo_with_family()
    ev = make_timed_event(
        fam_id, title="shifts", start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    )
    repo.put_event(ev)
    apply_action(
        repo,
        member,
        "reschedule_all_day_event",
        ev.id,
        {"start_date": "2026-06-01"},
        TargetType.EVENT,
    )
    got = repo.get_event(fam_id, ev.id)
    assert got is not None and got.all_day is True
    assert got.start_date is not None and got.start_at is None


def test_deconflict_all_day_event_shifts_dates() -> None:
    repo, fam_id, member = _repo_with_family()
    from tests.harness.factories import make_all_day_event

    ev = make_all_day_event(fam_id, title="trip", start_date=None)
    repo.put_event(ev)
    before = repo.get_event(fam_id, ev.id)
    assert before is not None and before.start_date is not None
    apply_action(repo, member, "deconflict_events", ev.id, {}, TargetType.EVENT)
    after = repo.get_event(fam_id, ev.id)
    assert after is not None and after.start_date is not None
    assert (after.start_date - before.start_date).days == 1

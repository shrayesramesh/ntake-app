"""Tests for the LINK-driven listing reads ``list_work_items`` / ``list_events``.

Added for the LINK seam (AWS_LLD §2.1/§3.1): the world-view + deep-context need
*all* non-archived work items (done included) and *all* events as full DTOs —
reads that ``list_board`` (grouped, archived-less) and ``list_calendar`` (thin
``CalendarRow``) cannot serve. Exercised here against ``InMemoryRepository``; the
DynamoDB impl (a single family-partition ``Query``) is a Session-4 Tier-2
follow-up, after which these join the backend-agnostic flow suite.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.repository_memory import InMemoryRepository
from tests.harness.factories import (
    make_all_day_event,
    make_family,
    make_timed_event,
    make_work_item,
)


def _seeded() -> tuple[InMemoryRepository, str]:
    repo = InMemoryRepository()
    fam = make_family()
    repo.seed_family(fam, [])
    return repo, fam.id


# --- list_work_items -------------------------------------------------------


def test_list_work_items_returns_all_non_archived_including_done() -> None:
    repo, fam = _seeded()
    todo = make_work_item(fam, title="todo task", status="todo")
    done = make_work_item(fam, title="done task", status="done")
    repo.put_work_item(todo)
    repo.put_work_item(done)

    items = repo.list_work_items(fam)

    titles = {wi.title for wi in items}
    assert titles == {"todo task", "done task"}  # done IS included


def test_list_work_items_excludes_archived() -> None:
    repo, fam = _seeded()
    live = make_work_item(fam, title="live")
    gone = make_work_item(fam, title="archived")
    repo.put_work_item(live)
    repo.put_work_item(gone)
    repo.archive_work_item(fam, gone.id)

    items = repo.list_work_items(fam)

    assert [wi.title for wi in items] == ["live"]


def test_list_work_items_is_family_scoped() -> None:
    repo, fam = _seeded()
    other = make_family()
    repo.seed_family(other, [])
    repo.put_work_item(make_work_item(fam, title="ours"))
    repo.put_work_item(make_work_item(other.id, title="theirs"))

    assert [wi.title for wi in repo.list_work_items(fam)] == ["ours"]


def test_list_work_items_empty_family_returns_empty() -> None:
    repo, fam = _seeded()
    assert repo.list_work_items(fam) == []


def test_list_work_items_returns_copies() -> None:
    repo, fam = _seeded()
    repo.put_work_item(make_work_item(fam, title="original"))
    fetched = repo.list_work_items(fam)
    fetched[0].title = "mutated"
    assert repo.list_work_items(fam)[0].title == "original"  # store not poisoned


# --- list_events -----------------------------------------------------------


def test_list_events_returns_all_events_as_full_dtos() -> None:
    repo, fam = _seeded()
    timed = make_timed_event(
        fam, title="Dentist", start_at=datetime(2026, 9, 5, 15, 0, tzinfo=UTC)
    )
    allday = make_all_day_event(fam, title="Trip")
    repo.put_event(timed)
    repo.put_event(allday)

    events = repo.list_events(fam)

    by_title = {e.title: e for e in events}
    assert set(by_title) == {"Dentist", "Trip"}
    # Full DTO fields survive (unlike CalendarRow): timing + all_day flag.
    assert by_title["Dentist"].all_day is False
    assert by_title["Dentist"].start_at == datetime(2026, 9, 5, 15, 0, tzinfo=UTC)
    assert by_title["Trip"].all_day is True


def test_list_events_is_family_scoped() -> None:
    repo, fam = _seeded()
    other = make_family()
    repo.seed_family(other, [])
    repo.put_event(make_timed_event(fam, title="ours"))
    repo.put_event(make_timed_event(other.id, title="theirs"))

    assert [e.title for e in repo.list_events(fam)] == ["ours"]


def test_list_events_empty_family_returns_empty() -> None:
    repo, fam = _seeded()
    assert repo.list_events(fam) == []


def test_list_events_returns_copies() -> None:
    repo, fam = _seeded()
    repo.put_event(make_timed_event(fam, title="original"))
    fetched = repo.list_events(fam)
    fetched[0].title = "mutated"
    assert repo.list_events(fam)[0].title == "original"

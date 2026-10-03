"""Edge-case + error-path tests for the in-memory repository (AWS_LLD §2.2).

Impl-specific guards that the backend-agnostic flow tests don't drive: the
not-found guards on intra-item writes, the ``create_event_from_update``
provenance precondition, and the malformed-event calendar-sort fallback. These
pin the in-memory contract (Session 3's Dynamo impl mirrors the behaviour).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.repository import calendar_sort_ts
from core.repository_memory import InMemoryRepository
from core.schemas import Event
from tests.harness.factories import make_family, make_timed_event, make_update


def _repo() -> InMemoryRepository:
    return InMemoryRepository()


def test_update_missing_work_item_raises() -> None:
    repo = _repo()
    with pytest.raises(KeyError, match="work item not found"):
        repo.update_work_item("fam", "missing", {"status": "doing"})


def test_append_update_missing_work_item_raises() -> None:
    repo = _repo()
    with pytest.raises(KeyError, match="work item not found"):
        repo.append_update("fam", "missing", make_update())


def test_archive_missing_work_item_raises() -> None:
    repo = _repo()
    with pytest.raises(KeyError, match="work item not found"):
        repo.archive_work_item("fam", "missing")


def test_update_missing_event_raises() -> None:
    repo = _repo()
    with pytest.raises(KeyError, match="event not found"):
        repo.update_event("fam", "missing", {"title": "x"})


def test_create_event_from_update_requires_provenance() -> None:
    repo = _repo()
    ev = make_timed_event("fam", title="no-prov")  # provenance defaults to None
    with pytest.raises(ValueError, match="requires event.provenance"):
        repo.create_event_from_update(ev, make_update())


def test_delete_missing_event_is_a_noop() -> None:
    repo = _repo()
    # Idempotent delete — a missing event does not raise.
    repo.delete_event("fam", "missing")


def test_calendar_sort_ts_malformed_event_falls_back_to_created_at() -> None:
    """An event with neither timing shape sorts at its creation instant."""
    created = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    ev = Event(
        id="ev1",
        family_id="fam1",
        title="malformed",
        all_day=False,
        start_at=None,  # no timed start...
        start_date=None,  # ...and no all-day date either
        created_at=created,
        updated_at=created,
    )
    assert calendar_sort_ts(ev, "UTC") == created


def test_list_calendar_defaults_to_utc_when_family_unseeded() -> None:
    """All-day sort uses a UTC day boundary when no family is seeded."""
    repo = _repo()
    fam = make_family()
    repo.put_event(make_timed_event(fam.id, title="x"))
    rows = repo.list_calendar(
        fam.id,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 12, 31, tzinfo=UTC),
    )
    assert [r.title for r in rows] == ["x"]

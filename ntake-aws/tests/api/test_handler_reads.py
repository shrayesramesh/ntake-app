"""Read conversions — repository DTO → API *Read DTO (local timing + nesting).

Pins the two error-prone conversions in ``handlers._support``: UTC→family-local
timing on events and work items, and the nested log/checklist mapping (the
update_id→id + injected work_item_id and ChecklistEntry→ChecklistItemRead id
synthesis).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from core.schemas import (
    ChecklistEntry,
    Event,
    WorkItem,
    WorkItemUpdate,
)
from handlers._support import event_read, work_item_read

TZ = "America/New_York"  # UTC-4 in summer
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_event_read_converts_utc_to_family_local() -> None:
    ev = Event(
        id="e1",
        family_id="fam1",
        title="Dentist",
        all_day=False,
        start_at=datetime(2026, 7, 1, 23, 0, tzinfo=UTC),  # 7pm EDT
        end_at=datetime(2026, 7, 2, 0, 0, tzinfo=UTC),  # 8pm EDT
        created_at=NOW,
        updated_at=NOW,
    )
    dto = event_read(ev, TZ)
    assert dto.title == "Dentist"
    # 23:00Z → 19:00 local (offset-free family-local wall time).
    assert dto.local_start_at == datetime(2026, 7, 1, 19, 0)
    assert dto.local_end_at == datetime(2026, 7, 1, 20, 0)


def test_work_item_read_local_due_and_nested_log_and_checklist() -> None:
    wi = WorkItem(
        id="w1",
        family_id="fam1",
        title="Taxes",
        status="doing",
        due_at=datetime(2026, 7, 2, 3, 0, tzinfo=UTC),  # 11pm EDT on the 1st
        created_at=NOW,
        updated_at=NOW,
        updates=[
            WorkItemUpdate(
                update_id="u1",
                author_id="m1",
                source="human",
                body="started",
                created_at=NOW,
            )
        ],
        checklist=[
            ChecklistEntry(text="W-2", checked=False, position=1),
            ChecklistEntry(text="1099", checked=True, position=2),
        ],
    )
    dto = work_item_read(wi, TZ)

    # due_at (UTC) → local_due_at (family-local wall time).
    assert dto.local_due_at == datetime(2026, 7, 1, 23, 0)
    # nested update: update_id → id, work_item_id injected.
    assert len(dto.updates) == 1
    u = dto.updates[0]
    assert u.id == "u1" and u.work_item_id == "w1" and u.source == "human"
    # checklist: ChecklistEntry (no id) → ChecklistItemRead (synthesized id).
    assert [c.text for c in dto.checklist] == ["W-2", "1099"]
    assert [c.checked for c in dto.checklist] == [False, True]
    assert dto.checklist[0].id == "w1:1" and dto.checklist[1].id == "w1:2"


def test_all_day_event_read_keeps_dates() -> None:
    ev = Event(
        id="e2",
        family_id="fam1",
        title="Trip",
        all_day=True,
        start_date=date(2026, 7, 4),
        end_date=date(2026, 7, 6),
        created_at=NOW,
        updated_at=NOW,
    )
    dto = event_read(ev, TZ)
    assert dto.all_day is True
    assert dto.start_date == date(2026, 7, 4) and dto.end_date == date(2026, 7, 6)
    assert dto.local_start_at is None and dto.local_end_at is None

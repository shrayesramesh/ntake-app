"""API + repository DTOs (core/schemas.py) — the validation/serialization layer.

Two layers tested here: the **API DTOs** (field contracts the handlers/frontend
rely on) and the **repository DTOs** (the storage aggregates the Repository seam
exchanges — AWS_LLD §2.2). The **ULID ripple (AWS_LLD §1)** is applied: every id
field is a ``str`` (ULID), server-minted at write time — these tests pin that.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from core.schemas import (
    BOARD_COLUMNS,
    CalendarKind,
    CalendarRow,
    CaptureCreate,
    CaptureResponse,
    ChecklistEntry,
    ConfirmAction,
    Event,
    EventProvenance,
    EventRead,
    Family,
    Member,
    ProposalRead,
    WorkItem,
    WorkItemCreate,
    WorkItemRead,
    WorkItemStatus,
    WorkItemUpdate,
    WorkItemUpdateCreate,
    WorkItemUpdateRead,
)

# --- API DTOs (ULID-string ids) --------------------------------------------


def test_event_read_maps_start_at_alias_to_local_start_at() -> None:
    ev = EventRead.model_validate(
        {
            "id": "ev1",
            "family_id": "fam1",
            "title": "Dentist",
            "start_at": datetime(2025, 1, 2, 9, 0),
            "end_at": datetime(2025, 1, 2, 10, 0),
        }
    )
    assert ev.local_start_at == datetime(2025, 1, 2, 9, 0)
    assert ev.local_end_at == datetime(2025, 1, 2, 10, 0)
    assert ev.all_day is False and ev.participants == [] and ev.tags == []


def test_event_read_all_day_dates() -> None:
    ev = EventRead.model_validate(
        {
            "id": "ev2",
            "family_id": "fam1",
            "title": "Trip",
            "all_day": True,
            "start_date": date(2025, 6, 1),
            "end_date": date(2025, 6, 3),
        }
    )
    assert ev.all_day is True
    assert ev.start_date == date(2025, 6, 1) and ev.end_date == date(2025, 6, 3)


def test_work_item_create_defaults() -> None:
    wi = WorkItemCreate(title="Buy milk")
    assert wi.title == "Buy milk"
    assert wi.description is None and wi.tags == [] and wi.assigned_to is None


def test_work_item_read_maps_due_at_alias_and_nests_log_checklist() -> None:
    wi = WorkItemRead.model_validate(
        {
            "id": "wi5",
            "family_id": "fam1",
            "title": "Taxes",
            "status": "todo",
            "position": 0,
            "due_at": datetime(2025, 4, 15, 0, 0),
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
            "updates": [
                {
                    "id": "upd1",
                    "work_item_id": "wi5",
                    "source": "human",
                    "body": "started",
                    "created_at": datetime(2025, 1, 1),
                }
            ],
            "checklist": [{"id": "c1", "text": "W2", "checked": False, "position": 1}],
        }
    )
    assert wi.local_due_at == datetime(2025, 4, 15, 0, 0)
    assert wi.updates[0].body == "started" and wi.checklist[0].text == "W2"


def test_work_item_update_dtos() -> None:
    assert WorkItemUpdateCreate(body="note").body == "note"
    read = WorkItemUpdateRead.model_validate(
        {
            "id": "upd1",
            "work_item_id": "wi2",
            "source": "assistant",
            "body": "did it",
            "created_at": datetime(2025, 1, 1),
        }
    )
    assert read.author_id is None and read.source == "assistant"


def test_capture_create_and_confirm_action() -> None:
    assert CaptureCreate(text="buy milk").text == "buy milk"
    confirm = ConfirmAction(
        name="complete_work_item", target_id="wi3", target_type="work_item"
    )
    assert confirm.name == "complete_work_item" and confirm.params == {}
    assert confirm.target_id == "wi3"


def test_proposal_and_capture_response_defaults() -> None:
    p = ProposalRead(name="set_due_date", action_summary="Set a due date")
    assert p.params == {} and p.detail_lines == [] and p.target_ref is None
    assert p.target_id is None
    resp = CaptureResponse(proposals=[p])
    assert resp.item is None and resp.debug is None
    assert resp.proposals[0].action_summary == "Set a due date"


# --- repository DTOs (AWS_LLD §2.2) ----------------------------------------


def test_board_columns_match_status_enum_order() -> None:
    assert BOARD_COLUMNS == ("todo", "on_deck", "doing", "done")
    assert BOARD_COLUMNS == tuple(s.value for s in WorkItemStatus)


def test_work_item_dto_defaults_and_nesting() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    wi = WorkItem(
        id="wi1",
        family_id="fam1",
        title="Taxes",
        created_at=now,
        updated_at=now,
        updates=[
            WorkItemUpdate(update_id="u1", source="human", body="note", created_at=now)
        ],
        checklist=[ChecklistEntry(text="W2", position=1)],
    )
    assert wi.status == WorkItemStatus.TODO
    assert wi.position == 0 and wi.archived_at is None and wi.log_segments == []
    assert wi.updates[0].update_id == "u1" and wi.checklist[0].checked is False


def test_event_dto_standalone_has_no_provenance() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    ev = Event(
        id="ev1",
        family_id="fam1",
        title="Standalone",
        start_at=now,
        end_at=now,
        created_at=now,
        updated_at=now,
    )
    assert ev.provenance is None and ev.source_update_id is None


def test_event_dto_with_provenance() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    prov = EventProvenance(
        work_item_id="wi1",
        member_id="mem1",
        member_name="Alex",
        note_snippet="plan party",
        at=now,
    )
    ev = Event(
        id="ev1",
        family_id="fam1",
        title="Party",
        start_at=now,
        end_at=now,
        provenance=prov,
        source_update_id="u9",
        created_at=now,
        updated_at=now,
    )
    assert ev.provenance is not None and ev.provenance.work_item_id == "wi1"
    assert ev.source_update_id == "u9"


def test_member_and_family_dtos() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    fam = Family(
        id="fam1", name="Household", timezone="America/New_York", created_at=now
    )
    mem = Member(id="mem1", family_id="fam1", display_name="Alex", created_at=now)
    assert fam.tag_colors == {} and fam.timezone == "America/New_York"
    assert mem.role == "adult" and mem.phone_number is None


def test_calendar_row_dto() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    row = CalendarRow(id="ev1", kind=CalendarKind.EVENT, title="X", sort_ts=now)
    assert row.kind == "event" and row.sort_ts == now

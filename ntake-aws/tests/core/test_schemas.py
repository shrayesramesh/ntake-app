"""API DTOs (core/schemas.py) — Pydantic validation/serialization boundary.

Lifted from the self-hosted app; still int-id in Session 1 (the ULID-string
ripple is applied in Session 2 alongside the repository/DTO work — AWS_LLD §1/§2).
These tests pin the field contracts the handlers and the frontend rely on.
"""

from __future__ import annotations

from datetime import date, datetime

from core.schemas import (
    CaptureCreate,
    CaptureResponse,
    ConfirmAction,
    EventRead,
    ProposalRead,
    WorkItemCreate,
    WorkItemRead,
    WorkItemUpdateCreate,
    WorkItemUpdateRead,
)


def test_event_read_maps_start_at_alias_to_local_start_at() -> None:
    ev = EventRead.model_validate(
        {
            "id": 1,
            "family_id": 1,
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
            "id": 2,
            "family_id": 1,
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
            "id": 5,
            "family_id": 1,
            "title": "Taxes",
            "status": "todo",
            "position": 0,
            "due_at": datetime(2025, 4, 15, 0, 0),
            "created_at": datetime(2025, 1, 1),
            "updated_at": datetime(2025, 1, 1),
            "updates": [
                {
                    "id": 1,
                    "work_item_id": 5,
                    "source": "human",
                    "body": "started",
                    "created_at": datetime(2025, 1, 1),
                }
            ],
            "checklist": [{"id": 1, "text": "W2", "checked": False, "position": 1}],
        }
    )
    assert wi.local_due_at == datetime(2025, 4, 15, 0, 0)
    assert wi.updates[0].body == "started" and wi.checklist[0].text == "W2"


def test_work_item_update_dtos() -> None:
    assert WorkItemUpdateCreate(body="note").body == "note"
    read = WorkItemUpdateRead.model_validate(
        {
            "id": 1,
            "work_item_id": 2,
            "source": "assistant",
            "body": "did it",
            "created_at": datetime(2025, 1, 1),
        }
    )
    assert read.author_id is None and read.source == "assistant"


def test_capture_create_and_confirm_action() -> None:
    assert CaptureCreate(text="buy milk").text == "buy milk"
    confirm = ConfirmAction(
        name="complete_work_item", target_id=3, target_type="work_item"
    )
    assert confirm.name == "complete_work_item" and confirm.params == {}


def test_proposal_and_capture_response_defaults() -> None:
    p = ProposalRead(name="set_due_date", action_summary="Set a due date")
    assert p.params == {} and p.detail_lines == [] and p.target_ref is None
    resp = CaptureResponse(proposals=[p])
    assert resp.item is None and resp.debug is None
    assert resp.proposals[0].action_summary == "Set a due date"

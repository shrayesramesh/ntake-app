"""DTO serialization round trips (``core/serde.py``) — the stdlib replacement for
Pydantic's ``model_dump`` / ``model_validate``.

Each stored DTO is written with ``to_item`` and read back with its explicit
reader **through the shapes DynamoDB actually returns**: numbers as ``Decimal``,
extra storage keys (``PK``/``SK``/``GSI*``/``_type``) alongside the DTO fields,
and older rows whose UTC timestamps were serialized with a ``Z`` suffix. The read
DTO must equal the original — the contract both Dynamo adapters rely on.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from core.schemas import (
    CaptureResponse,
    ChecklistEntry,
    DeviceToken,
    Event,
    EventProvenance,
    Family,
    LogSegment,
    Member,
    PairingCode,
    ProposalRead,
    WorkItem,
    WorkItemStatus,
    WorkItemUpdate,
)
from core.serde import (
    confirm_action_from_body,
    device_token_from_item,
    event_from_item,
    family_from_item,
    member_from_item,
    pairing_code_from_item,
    to_item,
    work_item_from_item,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 4, 9, 30, tzinfo=UTC)


def _as_dynamo(item: dict[str, Any]) -> dict[str, Any]:
    """Mimic a boto3 resource read: ints → Decimal (recursively) + storage keys."""

    def conv(v: Any) -> Any:
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return Decimal(v)
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v

    return {
        "PK": "FAM#x",
        "SK": "WI#y",
        "GSI1PK": "FAM#x#BOARD",
        "_type": "work_item",
        **conv(item),
    }


# --- writing ----------------------------------------------------------------


def test_to_item_is_json_safe_with_iso_datetimes_and_enum_values() -> None:
    wi = WorkItem(
        id="w1",
        family_id="f1",
        title="Taxes",
        status=WorkItemStatus.DOING,
        due_at=LATER,
        created_at=NOW,
        updated_at=NOW,
        updates=[
            WorkItemUpdate(update_id="u1", source="human", body="b", created_at=NOW)
        ],
    )
    item = to_item(wi)
    json.dumps(item)  # must not raise: everything is a JSON primitive
    assert item["status"] == "doing"
    assert item["due_at"] == LATER.isoformat()
    assert item["updates"][0]["created_at"] == NOW.isoformat()


def test_to_item_serializes_dates() -> None:
    ev = Event(
        id="e1",
        family_id="f1",
        title="Trip",
        all_day=True,
        start_date=date(2026, 7, 4),
        end_date=date(2026, 7, 6),
        created_at=NOW,
        updated_at=NOW,
    )
    item = to_item(ev)
    assert item["start_date"] == "2026-07-04" and item["start_at"] is None


def test_to_item_on_api_response_dtos() -> None:
    resp = CaptureResponse(
        proposals=[ProposalRead(name="no_action", action_summary="No action")]
    )
    body = json.loads(json.dumps(to_item(resp)))
    assert body["item"] is None
    assert body["proposals"][0]["name"] == "no_action"


# --- reading: round trips through DynamoDB shapes ---------------------------


def test_work_item_round_trip_with_nesting_and_decimals() -> None:
    wi = WorkItem(
        id="w1",
        family_id="f1",
        title="Taxes",
        description="forms",
        status="doing",
        position=3,
        assigned_to="m1",
        due_at=LATER,
        tags=["home"],
        created_at=NOW,
        updated_at=LATER,
        completed_at=None,
        archived_at=None,
        updates=[
            WorkItemUpdate(
                update_id="u1",
                author_id="m1",
                source="assistant",
                body="Set due",
                created_at=NOW,
            )
        ],
        checklist=[
            ChecklistEntry(text="W-2", checked=True, position=1),
            ChecklistEntry(text="1099", position=2),
        ],
        log_segments=[LogSegment(s3_key="k", from_ts=NOW, to_ts=LATER)],
    )
    back = work_item_from_item(_as_dynamo(to_item(wi)))
    assert back == wi
    # Decimal -> int (board_sort_key formats position with :06d).
    assert isinstance(back.position, int) and isinstance(
        back.checklist[0].position, int
    )


def test_event_round_trip_timed_with_provenance() -> None:
    ev = Event(
        id="e1",
        family_id="f1",
        title="Party",
        location="home",
        start_at=NOW,
        end_at=LATER,
        participants=["Alex"],
        tags=["fun"],
        provenance=EventProvenance(
            work_item_id="w1",
            member_id="m1",
            member_name="Alex",
            note_snippet="plan party",
            at=NOW,
        ),
        source_update_id="u9",
        created_at=NOW,
        updated_at=NOW,
    )
    assert event_from_item(_as_dynamo(to_item(ev))) == ev


def test_event_round_trip_all_day_no_provenance() -> None:
    ev = Event(
        id="e2",
        family_id="f1",
        title="Trip",
        all_day=True,
        start_date=date(2026, 7, 4),
        end_date=date(2026, 7, 6),
        created_at=NOW,
        updated_at=NOW,
    )
    assert event_from_item(_as_dynamo(to_item(ev))) == ev


def test_member_family_token_pairing_round_trips() -> None:
    mem = Member(
        id="m1", family_id="f1", display_name="Alex", phone_number="555", created_at=NOW
    )
    fam = Family(
        id="f1",
        name="T",
        timezone="America/New_York",
        tag_colors={"a": "b"},
        created_at=NOW,
    )
    tok = DeviceToken(
        token_hash="h",
        family_id="f1",
        member_id="m1",
        label="phone",
        created_at=NOW,
        revoked_at=LATER,
    )
    pc = PairingCode(
        code="012345",
        family_id="f1",
        member_id="m1",
        role="child",
        created_at=NOW,
        expires_at=LATER,
        attempts=2,
    )
    assert member_from_item(_as_dynamo(to_item(mem))) == mem
    assert family_from_item(_as_dynamo(to_item(fam))) == fam
    assert device_token_from_item(_as_dynamo(to_item(tok))) == tok
    back = pairing_code_from_item(_as_dynamo(to_item(pc)))
    assert back == pc and isinstance(back.attempts, int)


def test_reads_legacy_z_suffixed_timestamps() -> None:
    # Rows written before the dataclass switch serialized UTC with a "Z" suffix.
    item = {
        "id": "m1",
        "family_id": "f1",
        "display_name": "Alex",
        "created_at": "2026-09-03T12:00:00Z",
    }
    assert member_from_item(item).created_at == NOW


def test_reader_rejects_missing_required_field() -> None:
    with pytest.raises((KeyError, ValueError)):
        member_from_item({"id": "m1", "family_id": "f1", "display_name": "Alex"})


# --- reading: request bodies ------------------------------------------------


def test_confirm_action_from_body() -> None:
    action = confirm_action_from_body(
        {"name": "complete_work_item", "target_id": "w2", "target_type": "work_item"}
    )
    assert action.name == "complete_work_item" and action.params == {}
    assert action.target_id == "w2" and action.target_type == "work_item"


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": 5}, {"name": "x", "params": "nope"}],
)
def test_confirm_action_from_body_rejects_malformed(body: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        confirm_action_from_body(body)

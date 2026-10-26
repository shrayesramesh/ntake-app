"""DTO serialization — dataclass <-> DynamoDB item / JSON body (stdlib only).

Replaces Pydantic's ``model_dump`` / ``model_validate`` so the Lambda code needs
nothing beyond the stdlib + the runtime's ``boto3`` (no dependency bundling).

* **Writing** is ``dataclasses.asdict`` (which already recurses nested
  dataclasses + lists) with a leaf converter that makes the remaining values
  JSON/DynamoDB-safe: ``datetime``/``date`` → ISO-8601 strings, enums → their
  values. Every datetime in the DTOs sits directly on a dataclass field, so the
  leaf converter sees them all.
* **Reading** is explicit, one small function per stored DTO. DynamoDB returns
  plain dicts — ISO strings for datetimes, ``Decimal`` for numbers, plus storage
  keys (``PK``/``GSI1PK``/``_type``…) — so each reader names its fields, parses
  datetimes/dates, coerces ``Decimal`` → ``int``, rebuilds the four nested fields
  (``WorkItem.updates``/``checklist``/``log_segments``, ``Event.provenance``), and
  ignores any key it doesn't name. Explicit beats a reflective type-walker here:
  only six DTOs are ever parsed, and mypy checks every field.

Pure + stdlib-only (the boundary test keeps ``boto3``/``pydantic`` out of
``core``), so it is unit-tested at Tier 1 and reused by both Dynamo adapters and
the handlers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from typing import Any

from core.schemas import (
    ChecklistEntry,
    ConfirmAction,
    DeviceToken,
    Event,
    EventProvenance,
    Family,
    LogSegment,
    Member,
    PairingCode,
    WorkItem,
    WorkItemCreate,
    WorkItemUpdate,
    WorkItemUpdateCreate,
)

# --- writing ----------------------------------------------------------------


def _leaf(value: Any) -> Any:
    """Make one field value JSON/DynamoDB-safe (datetime/date → ISO, enum → value)."""
    if isinstance(value, datetime | date):  # datetime is a date subclass: one check
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _factory(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    return {key: _leaf(value) for key, value in pairs}


def to_item(obj: Any) -> dict[str, Any]:
    """A dataclass DTO as a plain JSON/DynamoDB-safe dict (nested included)."""
    return asdict(obj, dict_factory=_factory)


# --- reading: primitive coercions -------------------------------------------

Data = Mapping[str, Any]


def _dt(value: Any) -> datetime | None:
    """An optional datetime from an ISO string (or a datetime already)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _req_dt(value: Any) -> datetime:
    """A required datetime; a missing value is a malformed record."""
    parsed = _dt(value)
    if parsed is None:
        raise ValueError("required datetime is missing")
    return parsed


def _date(value: Any) -> date | None:
    """An optional calendar date from an ISO ``YYYY-MM-DD`` string."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _str_list(value: Any) -> list[str]:
    return [str(v) for v in value] if value else []


# --- reading: one function per stored DTO -----------------------------------


def member_from_item(d: Data) -> Member:
    return Member(
        id=d["id"],
        family_id=d["family_id"],
        display_name=d["display_name"],
        role=d.get("role", "adult"),
        phone_number=_opt_str(d.get("phone_number")),
        created_at=_req_dt(d["created_at"]),
    )


def family_from_item(d: Data) -> Family:
    return Family(
        id=d["id"],
        name=d["name"],
        timezone=d["timezone"],
        tag_colors={str(k): str(v) for k, v in (d.get("tag_colors") or {}).items()},
        created_at=_req_dt(d["created_at"]),
    )


def device_token_from_item(d: Data) -> DeviceToken:
    return DeviceToken(
        token_hash=d["token_hash"],
        family_id=d["family_id"],
        member_id=d["member_id"],
        role=d.get("role", "adult"),
        label=d.get("label", ""),
        created_at=_req_dt(d["created_at"]),
        revoked_at=_dt(d.get("revoked_at")),
    )


def pairing_code_from_item(d: Data) -> PairingCode:
    return PairingCode(
        code=d["code"],
        family_id=d["family_id"],
        member_id=d["member_id"],
        role=d.get("role", "adult"),
        label=d.get("label", ""),
        created_at=_req_dt(d["created_at"]),
        expires_at=_req_dt(d["expires_at"]),
        consumed_at=_dt(d.get("consumed_at")),
        attempts=int(d.get("attempts", 0)),
    )


def work_item_update_from_item(d: Data) -> WorkItemUpdate:
    return WorkItemUpdate(
        update_id=d["update_id"],
        author_id=_opt_str(d.get("author_id")),
        source=d["source"],
        body=d["body"],
        created_at=_req_dt(d["created_at"]),
    )


def checklist_entry_from_item(d: Data) -> ChecklistEntry:
    return ChecklistEntry(
        text=d["text"],
        checked=bool(d.get("checked", False)),
        position=int(d["position"]),
    )


def log_segment_from_item(d: Data) -> LogSegment:
    return LogSegment(
        s3_key=d["s3_key"],
        from_ts=_req_dt(d["from_ts"]),
        to_ts=_req_dt(d["to_ts"]),
    )


def work_item_from_item(d: Data) -> WorkItem:
    return WorkItem(
        id=d["id"],
        family_id=d["family_id"],
        title=d["title"],
        description=_opt_str(d.get("description")),
        status=d.get("status", "todo"),
        position=int(d.get("position", 0)),
        assigned_to=_opt_str(d.get("assigned_to")),
        due_at=_dt(d.get("due_at")),
        tags=_str_list(d.get("tags")),
        created_at=_req_dt(d["created_at"]),
        updated_at=_req_dt(d["updated_at"]),
        completed_at=_dt(d.get("completed_at")),
        archived_at=_dt(d.get("archived_at")),
        updates=[work_item_update_from_item(u) for u in d.get("updates") or []],
        checklist=[checklist_entry_from_item(c) for c in d.get("checklist") or []],
        log_segments=[log_segment_from_item(s) for s in d.get("log_segments") or []],
    )


def event_provenance_from_item(d: Data) -> EventProvenance:
    return EventProvenance(
        work_item_id=d["work_item_id"],
        member_id=d["member_id"],
        member_name=d["member_name"],
        note_snippet=d["note_snippet"],
        at=_req_dt(d["at"]),
    )


def event_from_item(d: Data) -> Event:
    provenance = d.get("provenance")
    return Event(
        id=d["id"],
        family_id=d["family_id"],
        title=d["title"],
        description=_opt_str(d.get("description")),
        location=_opt_str(d.get("location")),
        all_day=bool(d.get("all_day", False)),
        start_at=_dt(d.get("start_at")),
        end_at=_dt(d.get("end_at")),
        start_date=_date(d.get("start_date")),
        end_date=_date(d.get("end_date")),
        participants=_str_list(d.get("participants")),
        tags=_str_list(d.get("tags")),
        provenance=event_provenance_from_item(provenance) if provenance else None,
        source_update_id=_opt_str(d.get("source_update_id")),
        created_at=_req_dt(d["created_at"]),
        updated_at=_req_dt(d["updated_at"]),
    )


# --- reading: request bodies -------------------------------------------------


def confirm_action_from_body(d: Data) -> ConfirmAction:
    """Parse ``POST /actions/confirm``; raise ``ValueError`` on a malformed body."""
    name = d.get("name")
    params = d.get("params", {})
    if not isinstance(name, str) or not name:
        raise ValueError("confirm body requires a non-empty 'name'")
    if not isinstance(params, dict):
        raise ValueError("confirm body 'params' must be an object")
    target_id = d.get("target_id")
    target_type = d.get("target_type")
    return ConfirmAction(
        name=name,
        params=params,
        target_id=_opt_str(target_id),
        target_type=_opt_str(target_type),
    )


def _nonempty_str(d: Data, key: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"body requires a non-empty string '{key}'")
    return value


def work_item_create_from_body(d: Data) -> WorkItemCreate:
    """Parse ``POST /work-items``; raise ``ValueError`` on a malformed body."""
    tags = d.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("'tags' must be a list of strings")
    description = d.get("description")
    assigned_to = d.get("assigned_to")
    if description is not None and not isinstance(description, str):
        raise ValueError("'description' must be a string")
    if assigned_to is not None and not isinstance(assigned_to, str):
        raise ValueError("'assigned_to' must be a string")
    return WorkItemCreate(
        title=_nonempty_str(d, "title"),
        description=description,
        tags=list(tags),
        assigned_to=assigned_to,
    )


def work_item_update_create_from_body(d: Data) -> WorkItemUpdateCreate:
    """Parse ``POST /work-items/{id}/updates``; ``ValueError`` if malformed."""
    return WorkItemUpdateCreate(body=_nonempty_str(d, "body"))

"""Pydantic DTOs — the two id-bearing data contracts of the app.

Two layers, deliberately separate:

* **API DTOs** (``EventRead``/``WorkItemRead``/… — the lower half of this file):
  the JSON <-> Python boundary the handlers and frontend speak. Shapes carried
  over from the self-hosted app.
* **Repository DTOs** (``WorkItem``/``Event``/``Member``/``Family``/
  ``CalendarRow`` — the upper half): the storage-domain aggregates the
  :class:`core.repository.Repository` seam reads and writes (AWS_LLD §2.2). A
  work item is the **co-located aggregate** (item fields + nested ``updates`` log
  + ``checklist``); an event is flat with denormalized ``provenance``;
  ``CalendarRow`` unifies an event or a due-dated work item for the calendar
  Query (AWS_LLD §1.2).

**ULID ripple (AWS_LLD §1):** ids are **ULID strings**, server/Lambda-generated
at write time — not relational autoincrement ints. Every id field on both layers
is ``str``. The repository DTOs carry prefix-free ULIDs (``family_id``,
``work_item_id``, …); key composition (``FAM#``/``WI#``/… prefixes, the two
GSIs) is the repository's job, never the DTO's.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ===========================================================================
# Repository DTOs (AWS_LLD §2.2) — the storage-domain aggregates the Repository
# seam exchanges. ULID-string ids throughout (AWS_LLD §1).
# ===========================================================================


class WorkItemStatus(StrEnum):
    """The four board columns a work item moves through (AWS_LLD §1.2)."""

    TODO = "todo"
    ON_DECK = "on_deck"
    DOING = "doing"
    DONE = "done"


# The board's column order (left -> right). The single source of truth for how
# ``Repository.list_board`` groups and orders its columns.
BOARD_COLUMNS: tuple[str, ...] = tuple(s.value for s in WorkItemStatus)


class CalendarKind(StrEnum):
    """What a :class:`CalendarRow` represents in the unified calendar Query."""

    EVENT = "event"
    WORK_ITEM = "work_item"


class Member(BaseModel):
    """A family member (AWS_LLD §1.2: ``FAM#<fam>`` / ``MEM#<member>``)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    display_name: str
    role: str = "adult"  # "adult" | "child"
    phone_number: str | None = None
    created_at: datetime


class Family(BaseModel):
    """A household (AWS_LLD §1.2: ``FAM#<fam>`` / ``#META``)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    timezone: str  # IANA, e.g. "America/New_York"
    tag_colors: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class WorkItemUpdate(BaseModel):
    """One entry in a work item's append-only log (nested; AWS_LLD §1.2)."""

    model_config = ConfigDict(from_attributes=True)

    update_id: str
    author_id: str | None = None
    source: str  # "human" | "assistant"
    body: str
    created_at: datetime


class ChecklistEntry(BaseModel):
    """One nested checklist row on a work item (AWS_LLD §1.2)."""

    model_config = ConfigDict(from_attributes=True)

    text: str
    checked: bool = False
    position: int


class LogSegment(BaseModel):
    """Reserved S3-spill pointer slot — empty in v1 (AWS_LLD §1.5)."""

    model_config = ConfigDict(from_attributes=True)

    s3_key: str
    from_ts: datetime
    to_ts: datetime


class WorkItem(BaseModel):
    """The co-located work-item aggregate: fields + nested log + checklist.

    One DynamoDB item (AWS_LLD §1.2). ``updates`` is the ordered recent log,
    ``checklist`` the ordered checklist, ``log_segments`` the reserved spill slot
    (empty in v1). ``position`` orders the item within its board column.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    title: str
    description: str | None = None
    status: str = WorkItemStatus.TODO
    position: int = 0
    assigned_to: str | None = None
    due_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    updates: list[WorkItemUpdate] = Field(default_factory=list)
    checklist: list[ChecklistEntry] = Field(default_factory=list)
    log_segments: list[LogSegment] = Field(default_factory=list)


class EventProvenance(BaseModel):
    """Denormalized who/when/why written onto a co-created event (AWS_LLD §1.2).

    Self-describing (survives source deletion); the precise backlink is the
    event's ``source_update_id`` (resolve-on-read).
    """

    model_config = ConfigDict(from_attributes=True)

    work_item_id: str
    member_id: str
    member_name: str
    note_snippet: str
    at: datetime


class Event(BaseModel):
    """A flat calendar event (AWS_LLD §1.2).

    Timed events carry ``start_at``/``end_at`` (UTC); all-day events carry
    ``start_date``/``end_date``. ``provenance`` + ``source_update_id`` are set
    only on an event co-created from a work-item update (both ``None`` for a
    standalone event).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    title: str
    description: str | None = None
    location: str | None = None
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    participants: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    provenance: EventProvenance | None = None
    source_update_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CalendarRow(BaseModel):
    """A unified calendar entry — an event or a due-dated work item (AWS_LLD §1.2).

    The calendar Query (GSI2) returns events + due items in one time-ordered pass;
    ``CalendarRow`` is the small DTO that unifies them for rendering. ``sort_ts``
    is the UTC instant the row sorts by (the event's start for timed, family-
    midnight UTC for all-day, the due instant for a work item).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str  # CalendarKind value: "event" | "work_item"
    title: str
    sort_ts: datetime


# ===========================================================================
# API DTOs — the JSON <-> Python boundary (carried over from the self-hosted
# app). ULID-string ids (AWS_LLD §1). Separate from the repository DTOs above:
# these validate/serialize the HTTP surface; those are the storage aggregates.
# ===========================================================================


class EventRead(BaseModel):
    """Event as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    title: str
    description: str | None = None
    location: str | None = None
    all_day: bool = False
    local_start_at: datetime | None = Field(default=None, validation_alias="start_at")
    local_end_at: datetime | None = Field(default=None, validation_alias="end_at")
    start_date: date | None = None
    end_date: date | None = None
    participants: list[str] = []
    tags: list[str] = []


class WorkItemCreate(BaseModel):
    """Payload to create a work item (title required; rest optional)."""

    title: str
    description: str | None = None
    tags: list[str] = []
    assigned_to: str | None = None


class WorkItemUpdateCreate(BaseModel):
    """Payload to append a human update to a work item."""

    body: str


class WorkItemUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_item_id: str
    author_id: str | None = None
    source: str
    body: str
    created_at: datetime


class ChecklistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    text: str
    checked: bool
    position: int


class WorkItemRead(BaseModel):
    """A work item; the detail view also carries its update log + checklist."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    assigned_to: str | None = None
    title: str
    description: str | None = None
    status: str
    position: int
    local_due_at: datetime | None = Field(default=None, validation_alias="due_at")
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    updates: list[WorkItemUpdateRead] = []
    checklist: list[ChecklistItemRead] = []


class CaptureCreate(BaseModel):
    """Free-text capture payload. Always a NEW capture in v1 — the target (if
    any) lives in the text and is resolved by stage 1 (focus()), which resolves
    none yet. Explicit note-append to an item is POST /work-items/{id}/updates."""

    text: str


class ProposalRead(BaseModel):
    """A proposed (unconfirmed) action returned to the author's device.

    Two distinct texts (task 8): ``action_summary`` is deterministic and
    registry-derived (what the action WILL do, from params) — ground truth shown
    prominently; ``llm_rationale`` is the model's own narration (why it proposed
    this) — may be wrong/empty, shown as secondary context.
    """

    name: str
    params: dict = {}
    action_summary: str
    llm_rationale: str = ""
    target_id: str | None = None
    target_type: str | None = None  # "work_item" | "event" | None (task 12)
    proposal_id: str = ""  # batch-local handle, assigned by the engine seam
    target_ref: str | None = None  # v2 dependency hook; always None in v1
    target_label: str | None = None  # the target item's title, for card context
    detail_lines: list[str] = []  # verbose, id-resolved card body (per-action)


class CaptureResponse(BaseModel):
    """The assistant's transient proposals, plus the target item if one exists.

    ``item`` is the existing work item a capture targeted (with its freshly
    appended human note). For a NEW-item capture it is ``None`` — nothing is saved
    until the human confirms a ``create_work_item`` / ``create_timed_event`` or
    ``create_all_day_event`` proposal (propose-only; bare text no longer
    auto-creates a work item).

    ``debug`` is a DEBUGGING-ONLY trace of the live-LLM pipeline (prompts sent,
    raw model replies, resolved ids, deep context). Populated only when the local
    backend is active; ``None`` otherwise. Not committed behavior — a testing aid.
    """

    item: WorkItemRead | None = None
    proposals: list[ProposalRead] = []
    debug: dict | None = None


class ConfirmAction(BaseModel):
    """A proposed action the client sends back to confirm & apply."""

    name: str
    params: dict = {}
    target_id: str | None = None
    target_type: str | None = None  # "work_item" | "event" | None (task 12)


__all__ = [
    "BOARD_COLUMNS",
    "CalendarKind",
    "CalendarRow",
    "CaptureCreate",
    "CaptureResponse",
    "ChecklistEntry",
    "ChecklistItemRead",
    "ConfirmAction",
    "Event",
    "EventProvenance",
    "EventRead",
    "Family",
    "LogSegment",
    "Member",
    "ProposalRead",
    "WorkItem",
    "WorkItemCreate",
    "WorkItemRead",
    "WorkItemStatus",
    "WorkItemUpdate",
    "WorkItemUpdateCreate",
    "WorkItemUpdateRead",
]

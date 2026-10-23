"""DTOs — the two id-bearing data contracts of the app (stdlib dataclasses).

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

**Plain dataclasses, not Pydantic.** The Lambda bundle is our source only — the
Python 3.12 Lambda runtime provides ``boto3`` but not third-party packages — so the
app depends on the stdlib alone (plus the runtime's ``boto3``), with no
dependency-bundling step. Serialization to/from DynamoDB items + JSON bodies lives
in :mod:`core.serde` (``to_item`` + explicit per-type ``*_from_item``).
``kw_only=True`` lets required fields follow defaulted ones, matching the old
keyword-only construction style.

**ULID ripple (AWS_LLD §1):** ids are **ULID strings**, server/Lambda-generated
at write time. Every id field on both layers is ``str``. The repository DTOs carry
prefix-free ULIDs; key composition (``FAM#``/``WI#``/… prefixes, the two GSIs) is
the repository's job, never the DTO's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

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


class TargetType(StrEnum):
    """The kinds of existing entity an assistant action can target.

    Lives with the DTOs because it names concrete domain entities — the
    domain-agnostic engine must not know these, so the engine keeps
    ``target_type`` an opaque ``str | None`` and the app (these specs) supplies
    the members. A ``StrEnum`` so its members ARE their wire strings
    (``"work_item"`` / ``"event"``).
    """

    WORK_ITEM = "work_item"
    EVENT = "event"


@dataclass(kw_only=True)
class Member:
    """A family member (AWS_LLD §1.2: ``FAM#<fam>`` / ``MEM#<member>``)."""

    id: str
    family_id: str
    display_name: str
    role: str = "adult"  # "adult" | "child"
    phone_number: str | None = None
    created_at: datetime


@dataclass(kw_only=True)
class DeviceToken:
    """A device credential record (AWS_LLD §1.2 / §5: ``TOK#<hash>`` / ``#META``).

    Only the HMAC **hash** of the plaintext token is stored (``token_hash``);
    the plaintext is shown once at mint time and never persisted. The authorizer
    resolves a presented token by hashing it and looking up this record, then
    hands the handlers the resolved ``member_id``/``family_id``/``role``. A
    non-null ``revoked_at`` makes the token invalid.
    """

    token_hash: str
    family_id: str
    member_id: str
    role: str = "adult"  # "adult" | "child" — mirrors the member's role
    label: str = ""  # human label for the device, e.g. "Mom's phone"
    created_at: datetime
    revoked_at: datetime | None = None


@dataclass(kw_only=True)
class PairingCode:
    """A short-lived device-enrollment code (AWS_LLD §5.4: ``PAIR#<code>``).

    A 6-digit numeric code an already-enrolled member creates to onboard a new
    device without copying a long token: the new device exchanges the code at
    ``POST /pair`` for a full-entropy device token. Single-use (``consumed_at``),
    short-lived (``expires_at``), and attempt-capped (``attempts``) — cheap
    correctness/accident guards (a private family app, not a public high-traffic
    service). The code grants the stored ``member_id``/``role`` to the device that
    redeems it.
    """

    code: str  # 6-digit numeric string
    family_id: str
    member_id: str
    role: str = "adult"
    label: str = ""
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    attempts: int = 0


@dataclass(kw_only=True)
class Family:
    """A household (AWS_LLD §1.2: ``FAM#<fam>`` / ``#META``)."""

    id: str
    name: str
    timezone: str  # IANA, e.g. "America/New_York"
    tag_colors: dict[str, str] = field(default_factory=dict)
    created_at: datetime


@dataclass(kw_only=True)
class WorkItemUpdate:
    """One entry in a work item's append-only log (nested; AWS_LLD §1.2)."""

    update_id: str
    author_id: str | None = None
    source: str  # "human" | "assistant"
    body: str
    created_at: datetime


@dataclass(kw_only=True)
class ChecklistEntry:
    """One nested checklist row on a work item (AWS_LLD §1.2)."""

    text: str
    checked: bool = False
    position: int


@dataclass(kw_only=True)
class LogSegment:
    """Reserved S3-spill pointer slot — empty in v1 (AWS_LLD §1.5)."""

    s3_key: str
    from_ts: datetime
    to_ts: datetime


@dataclass(kw_only=True)
class WorkItem:
    """The co-located work-item aggregate: fields + nested log + checklist.

    One DynamoDB item (AWS_LLD §1.2). ``updates`` is the ordered recent log,
    ``checklist`` the ordered checklist, ``log_segments`` the reserved spill slot
    (empty in v1). ``position`` orders the item within its board column.
    """

    id: str
    family_id: str
    title: str
    description: str | None = None
    status: str = WorkItemStatus.TODO
    position: int = 0
    assigned_to: str | None = None
    due_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    updates: list[WorkItemUpdate] = field(default_factory=list)
    checklist: list[ChecklistEntry] = field(default_factory=list)
    log_segments: list[LogSegment] = field(default_factory=list)


@dataclass(kw_only=True)
class EventProvenance:
    """Denormalized who/when/why written onto a co-created event (AWS_LLD §1.2).

    Self-describing (survives source deletion); the precise backlink is the
    event's ``source_update_id`` (resolve-on-read).
    """

    work_item_id: str
    member_id: str
    member_name: str
    note_snippet: str
    at: datetime


@dataclass(kw_only=True)
class Event:
    """A flat calendar event (AWS_LLD §1.2).

    Timed events carry ``start_at``/``end_at`` (UTC); all-day events carry
    ``start_date``/``end_date``. ``provenance`` + ``source_update_id`` are set
    only on an event co-created from a work-item update (both ``None`` for a
    standalone event).
    """

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
    participants: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    provenance: EventProvenance | None = None
    source_update_id: str | None = None
    created_at: datetime
    updated_at: datetime


@dataclass(kw_only=True)
class CalendarRow:
    """A unified calendar entry — an event or a due-dated work item (AWS_LLD §1.2).

    The calendar Query (GSI2) returns events + due items in one time-ordered pass;
    ``CalendarRow`` is the small DTO that unifies them for rendering. ``sort_ts``
    is the UTC instant the row sorts by (the event's start for timed, family-
    midnight UTC for all-day, the due instant for a work item).
    """

    id: str
    kind: str  # CalendarKind value: "event" | "work_item"
    title: str
    sort_ts: datetime


# ===========================================================================
# API DTOs — the JSON <-> Python boundary (carried over from the self-hosted
# app). ULID-string ids (AWS_LLD §1). Separate from the repository DTOs above:
# these shape the HTTP surface; those are the storage aggregates. The read DTOs
# are built explicitly from repository DTOs (``handlers._support``), which does
# the stored-UTC -> family-local conversion into the ``local_*`` fields.
# ===========================================================================


@dataclass(kw_only=True)
class EventRead:
    """Event as returned by the API (timing in family-local wall time)."""

    id: str
    family_id: str
    title: str
    description: str | None = None
    location: str | None = None
    all_day: bool = False
    local_start_at: datetime | None = None
    local_end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    participants: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class WorkItemCreate:
    """Payload to create a work item (title required; rest optional)."""

    title: str
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    assigned_to: str | None = None


@dataclass(kw_only=True)
class WorkItemUpdateCreate:
    """Payload to append a human update to a work item."""

    body: str


@dataclass(kw_only=True)
class WorkItemUpdateRead:
    """One log entry as returned by the API (carries its parent work item id)."""

    id: str
    work_item_id: str
    author_id: str | None = None
    source: str
    body: str
    created_at: datetime


@dataclass(kw_only=True)
class ChecklistItemRead:
    """One checklist row as returned by the API (with a synthesized stable id)."""

    id: str
    text: str
    checked: bool
    position: int


@dataclass(kw_only=True)
class WorkItemRead:
    """A work item; the detail view also carries its update log + checklist."""

    id: str
    family_id: str
    assigned_to: str | None = None
    title: str
    description: str | None = None
    status: str
    position: int
    local_due_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    updates: list[WorkItemUpdateRead] = field(default_factory=list)
    checklist: list[ChecklistItemRead] = field(default_factory=list)


@dataclass(kw_only=True)
class CaptureCreate:
    """Free-text capture payload. Always a NEW capture in v1 — the target (if
    any) lives in the text and is resolved by stage 1 (focus()). Explicit
    note-append to an item is POST /work-items/{id}/updates."""

    text: str


@dataclass(kw_only=True)
class ProposalRead:
    """A proposed (unconfirmed) action returned to the author's device.

    Two distinct texts: ``action_summary`` is deterministic and registry-derived
    (what the action WILL do, from params) — ground truth shown prominently;
    ``llm_rationale`` is the model's own narration (why it proposed this) — may be
    wrong/empty, shown as secondary context.
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    action_summary: str
    llm_rationale: str = ""
    target_id: str | None = None
    target_type: str | None = None  # "work_item" | "event" | None
    proposal_id: str = ""  # batch-local handle, assigned by the engine seam
    target_ref: str | None = None  # v2 dependency hook; always None in v1
    target_label: str | None = None  # the target item's title, for card context
    detail_lines: list[str] = field(default_factory=list)  # id-resolved card body


@dataclass(kw_only=True)
class CaptureResponse:
    """The assistant's transient proposals, plus the target item if one exists.

    ``item`` is the existing work item a capture targeted. For a NEW-item capture
    it is ``None`` — nothing is saved until the human confirms a create proposal
    (propose-only). ``debug`` is a DEBUGGING-ONLY trace slot; ``None`` otherwise.
    """

    item: WorkItemRead | None = None
    proposals: list[ProposalRead] = field(default_factory=list)
    debug: dict[str, Any] | None = None


@dataclass(kw_only=True)
class ConfirmAction:
    """A proposed action the client sends back to confirm & apply."""

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    target_id: str | None = None
    target_type: str | None = None  # "work_item" | "event" | None


__all__ = [
    "BOARD_COLUMNS",
    "CalendarKind",
    "CalendarRow",
    "CaptureCreate",
    "CaptureResponse",
    "ChecklistEntry",
    "ChecklistItemRead",
    "ConfirmAction",
    "DeviceToken",
    "Event",
    "EventProvenance",
    "EventRead",
    "Family",
    "LogSegment",
    "Member",
    "PairingCode",
    "ProposalRead",
    "TargetType",
    "WorkItem",
    "WorkItemCreate",
    "WorkItemRead",
    "WorkItemStatus",
    "WorkItemUpdate",
    "WorkItemUpdateCreate",
    "WorkItemUpdateRead",
]

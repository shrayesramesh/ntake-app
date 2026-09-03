"""Pydantic DTOs for the API boundary (JSON <-> Python).

Separate from the ORM models (research/04-data-layer.md decision 2): ORM classes
handle persistence, these handle API validation/serialization.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EventRead(BaseModel):
    """Event as returned by the API."""

    # Allow constructing directly from an ORM object (obj.attr access).
    model_config = ConfigDict(from_attributes=True)

    id: int
    family_id: int
    title: str
    description: str | None = None
    location: str | None = None
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None


class WorkItemCreate(BaseModel):
    """Payload to create a work item (title required; rest optional)."""

    title: str
    description: str | None = None
    tags: list[str] = []
    assigned_to: int | None = None


class WorkItemUpdateCreate(BaseModel):
    """Payload to append a human update to a work item."""

    body: str


class WorkItemUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_item_id: int
    author_id: int | None = None
    source: str
    body: str
    created_at: datetime


class ChecklistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    checked: bool
    position: int


class WorkItemRead(BaseModel):
    """A work item; the detail view also carries its update log + checklist."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    family_id: int
    assigned_to: int | None = None
    title: str
    description: str | None = None
    status: str
    position: int
    due_at: datetime | None = None
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    updates: list[WorkItemUpdateRead] = []
    checklist: list[ChecklistItemRead] = []


class CaptureCreate(BaseModel):
    """Free-text capture payload. ``work_item_id`` targets an existing item;
    omitted/None means create a new item from the text."""

    text: str
    work_item_id: int | None = None


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
    target_id: int | None = None
    target_label: str | None = None  # the target item's title, for card context


class CaptureResponse(BaseModel):
    """The assistant's transient proposals, plus the target item if one exists.

    ``item`` is the existing work item a capture targeted (with its freshly
    appended human note). For a NEW-item capture it is ``None`` — nothing is saved
    until the human confirms a ``create_work_item`` / ``create_event`` proposal
    (propose-only; bare text no longer auto-creates a work item)."""

    item: WorkItemRead | None = None
    proposals: list[ProposalRead] = []


class ConfirmAction(BaseModel):
    """A proposed action the client sends back to confirm & apply."""

    name: str
    params: dict = {}
    target_id: int | None = None

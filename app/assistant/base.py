"""The swappable assistant boundary (Phase 4, task 3).

The rest of the app depends only on ``AssistantClient``; implementations
(FakeAssistant here, OllamaAssistant on the host, NullAssistant for "off") are
chosen by config. See spec/PHASE4_ASSISTANT.md §1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CaptureContext:
    """Everything the assistant needs to propose — and nothing it shouldn't.

    Read-only inputs; no Session (the assistant must not mutate). ``work_item_id``
    is the capture target (None = a "new item" capture).
    """

    text: str
    work_item_id: int | None
    timezone: str
    now: datetime
    # Optional lean context the OllamaAssistant will use (kept small = fast):
    item_log: list[str] = field(default_factory=list)  # recent update bodies
    calendar_window: list[str] = field(default_factory=list)  # nearby event summaries


@dataclass
class ProposedAction:
    """A single proposed, unconfirmed action — exactly what the assistant returns.

    ``name`` is a key in the action registry; ``params`` a plain dict;
    ``target_id`` the work item it applies to (echoed back on Confirm so the
    server needn't re-derive it). ``llm_rationale`` is the model's OWN narration —
    why it proposed this. It may be wrong, and is canned/empty for the fake.

    Note there is deliberately NO ``action_summary`` here: what the action WILL do
    is derived server-side from the registry (``describe(params)``), NOT carried by
    the model. The assistant supplies intent (name + params) and its rationale;
    the ground-truth summary is the engine's, so a fallible model can't misstate
    what the human is confirming.
    """

    name: str
    params: dict
    llm_rationale: str = ""
    target_id: int | None = None
    # What the action targets: "work_item", "event", or None (targets nothing —
    # e.g. create_work_item / create_event of a brand-new thing). Drives the
    # conditional log rule: a source=assistant work_item_update is appended only
    # when the action targets a work item (WORKITEM-3).
    target_type: str | None = None


class AssistantClient(ABC):
    """Proposes zero or more actions for a capture. MUST NOT mutate anything and
    MUST return [] on any failure (never raise into the request path)."""

    @abstractmethod
    def propose(self, ctx: CaptureContext) -> list[ProposedAction]: ...


class NullAssistant(AssistantClient):
    """The 'off' client — never proposes anything."""

    def propose(self, ctx: CaptureContext) -> list[ProposedAction]:
        return []

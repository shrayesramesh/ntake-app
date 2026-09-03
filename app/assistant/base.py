"""The swappable assistant boundary (Phase 4, task 3).

The rest of the app depends only on ``AssistantClient``; implementations
(FakeAssistant here, OllamaAssistant on the host, NullAssistant for "off") are
chosen by config. See spec/PHASE4_ASSISTANT.md §1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class CaptureRequest:
    """Stage-1 input: the raw capture, before any DB lookup or resolution.

    What the endpoint hands to ``focus()``. Deliberately minimal — the target
    (if any) lives in ``text`` and is resolved by stage 1, not passed as a
    structured id (that resolution is a v2/Ollama capability; v1 treats every
    capture as new).
    """

    text: str
    timezone: str
    now: datetime


@dataclass
class EventSummary:
    """A focused calendar event — carries the real ``id`` so stage 2 can emit an
    executable action against it (e.g. deconflict_events targeting this event).

    A plain value object (primitives only) — NOT an ORM Event — so the assistant
    boundary stays app-agnostic. Timed events use ``start`` (UTC); all-day events
    use ``start_date``.
    """

    id: int
    title: str
    start: datetime | None = None
    start_date: date | None = None
    all_day: bool = False


@dataclass
class FocusedContext:
    """Stage-2 input: the *focused world* the assistant reasons over.

    Produced by ``focus()`` (stage 1) from a CaptureRequest + DB lookups. Holds
    the resolved entities WITH ids and grounded params, so the proposals stage 2
    emits are executable by construction. Read-only; no Session (the assistant
    must not mutate). ``work_item_id`` is the resolved target (None in v1 — no
    text-based resolution yet).
    """

    text: str
    work_item_id: int | None
    timezone: str
    now: datetime
    # Lean, id-bearing context (kept small = fast for the model):
    item_log: list[str] = field(default_factory=list)  # target item's recent updates
    calendar_window: list[EventSummary] = field(default_factory=list)  # nearby events


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
    # Batch-local handle (e.g. "p1"), assigned by the engine seam so a proposal
    # has a stable identity within one capture response. NOT a DB id.
    proposal_id: str = ""
    # Reserved for v2 dependency chaining: a target_ref points at another
    # proposal's proposal_id when this action targets that proposal's
    # to-be-created entity. In v1 this MUST be None — every proposal fully
    # defines its own operation (executable in isolation, no dangling reference).
    target_ref: str | None = None


class AssistantClient(ABC):
    """Proposes zero or more actions for a focused capture. MUST NOT mutate
    anything and MUST return [] on any failure (never raise into the request
    path). Engine-clean: no Session, no ORM — reasons only over FocusedContext."""

    @abstractmethod
    def propose(self, ctx: FocusedContext) -> list[ProposedAction]: ...


class NullAssistant(AssistantClient):
    """The 'off' client — never proposes anything."""

    def propose(self, ctx: FocusedContext) -> list[ProposedAction]:
        return []

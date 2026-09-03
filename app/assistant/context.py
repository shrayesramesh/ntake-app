"""The ntake assistant boundary — app-specific capture context + the engine
contract it reuses.

The generic propose contract (``AssistantClient`` / ``ProposedAction`` /
``NullAssistant``) lives in the domain-agnostic engine (``app.routing``) and is
re-exported here so the plugin (FakeAssistant, endpoints, tests) can import it
from one place. The **app-specific** capture types (``CaptureRequest``,
``EventSummary``, ``FocusedContext``) stay here — they are ntake's domain shape,
NOT part of the reusable engine. ntake assistants consume a ``FocusedContext``;
the engine treats that as the opaque ``ctx`` it never inspects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Re-export the domain-agnostic contract from the engine.
from app.routing.engine import (
    ActionContext,
    AssistantClient,
    NullAssistant,
    ProposedAction,
)

__all__ = [
    "AssistantClient",
    "CaptureRequest",
    "EventSummary",
    "FocusedContext",
    "NullAssistant",
    "ProposedAction",
    "render_focus",
]


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
class FocusedContext(ActionContext):
    """Stage-2 input: the *focused world* the assistant reasons over.

    Produced by ``focus()`` (stage 1) from a CaptureRequest + DB lookups. Holds
    the resolved entities WITH ids and grounded params, so the proposals stage 2
    emits are executable by construction. Read-only; no Session (the assistant
    must not mutate). ``work_item_id`` is the resolved target (None in v1 — no
    text-based resolution yet). To the engine this is the opaque ``ctx``.
    """

    text: str
    work_item_id: int | None
    timezone: str
    now: datetime
    # Lean, id-bearing context (kept small = fast for the model):
    item_log: list[str] = field(default_factory=list)  # target item's recent updates
    calendar_window: list[EventSummary] = field(default_factory=list)  # nearby events


def render_focus(ctx: FocusedContext) -> str:
    """A readable print of what the assistant is focused on (the FocusedContext).

    Used to describe back to the user what the assistant understood. The
    FakeAssistant stamps this verbatim onto each proposal's ``llm_rationale``
    (pass-through — no intelligence); a real assistant (Ollama) will instead
    write a genuine natural-language description in that slot.
    """
    parts = [f"Understood: “{ctx.text}”"]
    if ctx.calendar_window:
        titles = ", ".join(ev.title for ev in ctx.calendar_window)
        parts.append(f"events in view: {titles}")
    if ctx.work_item_id is not None:
        parts.append(f"on work item #{ctx.work_item_id}")
    return " · ".join(parts)

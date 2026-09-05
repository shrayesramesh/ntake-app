"""The capture pipeline's stage data + the engine contract it reuses.

The two value objects that flow through the two-stage capture pipeline:
``CaptureRequest`` (stage-1 input) and ``FocusedContext`` (stage-2 input). Both
are plain, **session-free** data (the DB ``Session`` lives on the resolver seam,
not on these) — ``FocusedContext`` is the engine's opaque, read-only ``ctx``.

``CaptureRequest`` (``{text, timezone, now}``) is itself domain-agnostic; what
pins this file to the ntake plugin is ``FocusedContext``, which names ntake's
entity types (``resolved_work_item_ids`` / ``resolved_event_ids``) and so cannot
live in the domain-agnostic engine.

The generic propose contract (``AssistantClient`` / ``ProposedAction`` /
``NullAssistant``) lives in the engine (``app.routing``) and is re-exported here
so the plugin (FakeAssistant, endpoints, tests) can import it from one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
    "FocusedContext",
    "NullAssistant",
    "ProposedAction",
]


@dataclass
class CaptureRequest:
    """Stage-1 input: the raw capture, before any DB lookup or resolution.

    What the endpoint hands to ``focus()``. Deliberately minimal — the target
    (if any) lives in ``text`` and is resolved by stage 1 (the LINK call), not
    passed as a structured id.
    """

    text: str
    timezone: str
    now: datetime


@dataclass
class FocusedContext(ActionContext):
    """Stage-2 input: the *focused world* the assistant reasons over.

    Produced by ``focus()`` (stage 1) as the two-call pipeline's hand-off: it
    carries the ids the LINK call resolved (``resolved_work_item_ids`` /
    ``resolved_event_ids`` — validated to the family) plus ``deep_context``, the
    fully-rendered records string ``deep_context`` builds for those ids
    (target item(s) + full update history + linked/participated events). Stage 2
    proposes over this; the server attaches the concrete target from the resolved
    ids (see ``primary_work_item_id`` / ``primary_event_id``).

    Read-only; holds NO Session — the propose seam must not mutate. To the engine
    this is the opaque ``ctx``.
    """

    text: str
    timezone: str
    now: datetime
    capture_author: str = ""
    deep_context: str = ""
    resolved_work_item_ids: list[int] = field(default_factory=list)
    resolved_event_ids: list[int] = field(default_factory=list)
    resolved_member_ids: list[int] = field(default_factory=list)

    @property
    def primary_work_item_id(self) -> int | None:
        """The work-item target to attach, or None. v1 resolves ≤1 per type, so
        "primary" = the first resolved id; a readable accessor for stage 2."""
        return self.resolved_work_item_ids[0] if self.resolved_work_item_ids else None

    @property
    def primary_event_id(self) -> int | None:
        """The event target to attach, or None (first resolved event id)."""
        return self.resolved_event_ids[0] if self.resolved_event_ids else None

    @property
    def primary_member_id(self) -> int | None:
        """The member the note is about, or None (first resolved member id).

        Used to attribute an action to a named person (e.g. attach a participant
        on a created event) — the member-linking counterpart to the work-item/
        event primaries."""
        return self.resolved_member_ids[0] if self.resolved_member_ids else None

    def render(self) -> str:
        """A readable print of what the assistant is focused on.

        Describes back to the user what the assistant understood (text + resolved
        ids). The FakeAssistant stamps this verbatim onto each proposal's
        ``llm_rationale`` (pass-through — no intelligence); a real assistant
        (the local LLM) will instead write a genuine natural-language description
        there.
        """
        parts = [f"Understood: “{self.text}”"]
        if self.resolved_work_item_ids:
            ids = ", ".join(f"#{i}" for i in self.resolved_work_item_ids)
            parts.append(f"work items: {ids}")
        if self.resolved_event_ids:
            ids = ", ".join(f"e{i}" for i in self.resolved_event_ids)
            parts.append(f"events: {ids}")
        return " · ".join(parts)

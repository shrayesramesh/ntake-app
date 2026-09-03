"""Stage 1 of capture — ``focus()`` (the app-coupled resolver).

Turns a raw :class:`CaptureRequest` into the *focused world* the assistant
reasons over (:class:`FocusedContext`). This is the ONLY capture stage that
touches the database: it resolves the relevant entities (with their real ids) so
that the actions stage 2 proposes are executable against real rows.

**v1 scope.** Resolution is deterministic — no LLM, no text parsing to find a
target work item — so ``work_item_id`` is always ``None`` (every capture is
new). It DOES populate ``calendar_window`` from the family's events. When the
Ollama resolver lands (task 7) it can parse the text to resolve a target and
plan richer lookups, promoted behind a ``Resolver`` interface then; for now this
is a plain function (no premature abstraction).

Stage 2 (``AssistantClient.propose``) stays engine-clean (no Session/ORM); all
the app coupling lives here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.context import CaptureRequest, EventSummary, FocusedContext
from app.models import Event, Member


def _event_summaries(session: Session, family_id: int) -> list[EventSummary]:
    """The family's events as id-bearing summaries, ordered by start.

     id-bearing on purpose: stage 2 needs the real event id to emit an executable
    action (e.g. deconflict_events targeting a specific event).
    """
    stmt = (
        select(Event)
        .where(Event.family_id == family_id)
        .order_by(Event.start_at, Event.start_date, Event.id)
    )
    return [
        EventSummary(
            id=ev.id,
            title=ev.title,
            start=ev.start_at,
            start_date=ev.start_date,
            all_day=ev.all_day,
        )
        for ev in session.scalars(stmt).all()
    ]


def focus(request: CaptureRequest, session: Session, member: Member) -> FocusedContext:
    """Resolve a raw capture into a FocusedContext (stage 1).

    v1: no text-based target resolution (``work_item_id=None``); populates the
    calendar window from the member's family events.
    """
    return FocusedContext(
        text=request.text,
        work_item_id=None,  # v1: no text-based resolution yet
        timezone=request.timezone,
        now=request.now,
        item_log=[],  # populated once a target is resolved (v2)
        calendar_window=_event_summaries(session, member.family_id),
    )

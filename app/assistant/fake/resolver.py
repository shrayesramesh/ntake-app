"""``FakeCaptureResolver`` — the deterministic v1 stage-1 resolver (no LLM).

Stage-1 sibling of ``FakeAssistant``: it builds the ``FocusedContext`` the
assistant reasons over. It is the ONLY capture stage that touches the DB — it
queries the family's events so the ids it puts in ``calendar_window`` make
stage-2 proposals executable against real rows.

v1 does NOT resolve a target work item from free text (``work_item_id=None``;
every capture is new) — that is the Ollama resolver's job (task 7). Selected via
``NTAKE_ASSISTANT`` through ``app.assistant.factory.get_capture_resolver``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.base import (
    CaptureRequest,
    CaptureResolver,
    EventSummary,
    FocusedContext,
)
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


class FakeCaptureResolver(CaptureResolver):
    """Deterministic v1 resolver (no LLM).

    Passes the raw fields through and populates the calendar window from the
    member's family events. Does NOT resolve a target from text
    (``work_item_id=None``; every capture is new) — that is the Ollama resolver's
    job (task 7).
    """

    def focus(
        self, request: CaptureRequest, session: Session, member: Member
    ) -> FocusedContext:
        return FocusedContext(
            text=request.text,
            work_item_id=None,  # v1: no text-based resolution yet
            timezone=request.timezone,
            now=request.now,
            item_log=[],  # populated once a target is resolved (v2/Ollama)
            calendar_window=_event_summaries(session, member.family_id),
        )

"""Stage 1 of capture — the ``CaptureResolver`` seam (the app-coupled resolver).

Turns a raw :class:`CaptureRequest` into the *focused world* the assistant
reasons over (:class:`FocusedContext`) via ``focus()``. This is the ONLY capture
stage that touches the database: it resolves the relevant entities (with their
real ids) so that the actions stage 2 proposes are executable against real rows.

``CaptureResolver`` is the stage-1 sibling of the stage-2 ``AssistantClient``
seam: a config-selected, stateless strategy (see ``factory.get_capture_resolver``)
that the request-scoped DB ``session`` flows *into* per call. It is deliberately
**app-coupled** (holds the DB coupling) — unlike the domain-agnostic engine
(``app.routing``), so taking a ``Session`` here costs no generic purity. The
``FocusedContext`` it produces is the plain, session-free value object that
crosses into the generic (stage-2) world.

**v1 scope (``FakeCaptureResolver``).** Resolution is deterministic — no LLM, no
text parsing to find a target work item — so ``work_item_id`` is always ``None``
(every capture is new). It DOES populate ``calendar_window`` from the family's
events. The Ollama resolver (task 7) will parse the text to resolve a target and
plan richer lookups, selected via the same ``NTAKE_ASSISTANT`` switch.

Stage 2 (``AssistantClient.propose``) stays engine-clean (no Session/ORM); all
the app coupling lives here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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


class CaptureResolver(ABC):
    """Stage-1 seam: resolve a raw ``CaptureRequest`` into a ``FocusedContext``.

    A stateless, config-selected strategy (like ``AssistantClient``). The
    request-scoped DB ``session`` and the ``member`` flow in per call — they are
    NOT held on the resolver, so the resolver stays a singleton and the
    request-scoped session is never captured by a long-lived object. Concrete
    resolvers: ``FakeCaptureResolver`` (v1, deterministic) and (task 7)
    ``OllamaCaptureResolver`` (LLM-backed).
    """

    @abstractmethod
    def focus(
        self, request: CaptureRequest, session: Session, member: Member
    ) -> FocusedContext: ...


class FakeCaptureResolver(CaptureResolver):
    """Deterministic v1 resolver (no LLM).

    Passes the raw fields through and populates the calendar window from the
    member's family events. Does NOT resolve a target from text
    (``work_item_id=None``; every capture is new) — that is the Ollama
    resolver's job (task 7).
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

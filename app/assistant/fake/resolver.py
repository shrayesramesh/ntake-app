"""``FakeCaptureResolver`` + its deterministic LINK — the v1 stage-1 resolver.

Stage-1 sibling of ``FakeAssistant``: it builds the ``FocusedContext`` the
assistant reasons over, running the real two-call *shape* with a deterministic,
model-free LINK (``fake_link``, below) → ``deep_context`` (render the full
records for the resolved ids). It is the app-coupled capture stage (it touches
the DB); the ``FocusedContext`` it returns is the session-free value object that
crosses into stage 2.

``fake_link`` is the fake analog of the pipeline's LINK call
(spec/LLD-assistant-pipeline.md): map a capture note to the existing entities it
refers to, with a deterministic rule instead of an LLM. Matching rule
(intentionally an MVP — a real LINK matches on meaning):

* Take the family's **non-archived work items** and its **events**.
* An entity matches the note if any *significant word* of its title appears as a
  whole word in the note, case-insensitively. "Significant" = alphanumeric tokens
  of length ≥ 3 that are not common stopwords, so shared filler ("the", "is",
  "and") never triggers a match.
* Return matched ids deduped + id-ordered (work items and events separately) —
  the ``(work_item_ids, event_ids)`` shape ``deep_context`` consumes.

Selected via ``AssistantConfig.kind`` through
``app.assistant.factory.get_capture_resolver``. The LLM-backed sibling
(``LocalLlmCaptureResolver`` — task 7, built) additionally calls ``build_world_view``
to feed its LINK *prompt*; the fake link matches the DB directly and needs no
rendered world view, so it is not built here.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.base import CaptureRequest, CaptureResolver, FocusedContext
from app.assistant.context.deep import deep_context
from app.persistence.models import Event, Member, WorkItem


class FakeCaptureResolver(CaptureResolver):
    """Deterministic v1 resolver (no LLM).

    Resolves target ids from the note deterministically (``fake_link``) and
    renders the deep context for them (the real ``deep_context``, which also
    always unions in the capturing member's own footprint). No model anywhere.
    """

    def focus(
        self, request: CaptureRequest, session: Session, member: Member
    ) -> FocusedContext:
        wi_ids, ev_ids = fake_link(
            session, member.family_id, request.text, request.now, request.timezone
        )
        dc = deep_context(session, member, wi_ids, ev_ids)
        return FocusedContext(
            text=request.text,
            timezone=request.timezone,
            now=request.now,
            deep_context=dc,
            resolved_work_item_ids=wi_ids,
            resolved_event_ids=ev_ids,
        )


# --- the deterministic, model-free LINK -----------------------------------

# Common filler words that must never, on their own, link a note to an entity.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "is",
        "are",
        "was",
        "were",
        "be",
        "with",
        "we",
        "it",
        "this",
        "that",
        "my",
        "our",
        "his",
        "her",
        "their",
    }
)
_MIN_WORD_LEN = 3

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens of ``text``."""
    return set(_TOKEN_RE.findall(text.lower()))


def _significant(title: str) -> set[str]:
    """The significant words of a title: length ≥ 3, not a stopword."""
    return {
        w for w in _tokens(title) if len(w) >= _MIN_WORD_LEN and w not in _STOPWORDS
    }


def fake_link(
    session: Session,
    family_id: int,
    note: str,
    now: datetime,
    tz: str,
) -> tuple[list[int], list[int]]:
    """Deterministically link ``note`` to the family's items/events by title.

    Returns ``(work_item_ids, event_ids)`` — the ids whose title shares a
    significant word with the note. ``now``/``tz`` are accepted for parity with
    the real LINK signature (relative-date resolution) but unused by this MVP
    title match.
    """
    note_tokens = _tokens(note)

    wi_ids = [
        wi.id
        for wi in _non_archived_items(session, family_id)
        if _significant(wi.title) & note_tokens
    ]
    ev_ids = [
        ev.id
        for ev in _events(session, family_id)
        if _significant(ev.title) & note_tokens
    ]
    return wi_ids, ev_ids


def _non_archived_items(session: Session, family_id: int) -> list[WorkItem]:
    stmt = (
        select(WorkItem)
        .where(WorkItem.family_id == family_id, WorkItem.archived_at.is_(None))
        .order_by(WorkItem.id)
    )
    return list(session.scalars(stmt).all())


def _events(session: Session, family_id: int) -> list[Event]:
    stmt = select(Event).where(Event.family_id == family_id).order_by(Event.id)
    return list(session.scalars(stmt).all())

"""``fake_link`` — the deterministic, model-free LINK call.

The fake analog of the pipeline's LINK call (spec/LLD-assistant-pipeline.md): map
a capture note to the existing entities it refers to, but with a deterministic
rule instead of an LLM. It lets the fake path run the real
``build_world_view → LINK → deep_context → propose`` shape end to end with no
model.

Matching rule (intentionally an MVP — a real LINK matches on meaning):

* Take the family's **non-archived work items** and its **events**.
* An entity matches the note if any *significant word* of its title appears as a
  whole word in the note, case-insensitively. "Significant" = alphanumeric tokens
  of length ≥ 3 that are not common stopwords, so shared filler ("the", "is",
  "and") never triggers a match.
* Return the matched ids, deduped and id-ordered (work items and events
  separately) — the ``(work_item_ids, event_ids)`` shape ``resolve.deep_context``
  consumes.

App-coupled (takes a Session), like ``world.py`` / ``resolve.py``.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, WorkItem

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

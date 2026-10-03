"""Shared loading, time parsing, and log-append helpers for action domains.

Session 3 port (AWS_LLD §2): rewired off the SQLAlchemy ``Session`` +
``app.persistence.models`` onto the :class:`core.repository.Repository` seam and
the lifted DTOs, and off ``app.persistence.temporal`` onto :mod:`core.temporal`.

Two fidelity rules from the Session-2 hand-off:

* **Miss translation.** The repository raises ``KeyError`` (or returns ``None``)
  on a missing target; the old handlers raised :class:`ActionError`. The loaders
  below translate, so handler-visible behavior is unchanged.
* **Log-append shape.** ``_append_assistant_update`` builds a
  :class:`WorkItemUpdate` DTO (minting its ``update_id`` server-side), persists it
  via ``repo.append_update``, and **returns** it — so the event-creation path can
  read ``update.update_id`` for ``source_update_id`` (the old code read the
  flushed row's id).
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.engine.engine import ActionError
from core.ids import new_ulid
from core.repository import Repository
from core.schemas import Event, Member, WorkItem, WorkItemUpdate
from core.temporal import family_local_to_utc


def _parse_local_dt(value: str, timezone: str) -> datetime:
    """Map one model-facing family-local time to the UTC storage representation."""
    return family_local_to_utc(value, timezone)


def _load_item(repo: Repository, family_id: str, target_id: str | None) -> WorkItem:
    """Load a work item or raise ActionError (translating the repo miss)."""
    wi = repo.get_work_item(family_id, target_id) if target_id is not None else None
    if wi is None:
        raise ActionError(f"work item not found: {target_id}")
    return wi


def _load_event(repo: Repository, family_id: str, target_id: str | None) -> Event:
    """Load an event or raise ActionError (translating the repo miss)."""
    ev = repo.get_event(family_id, target_id) if target_id is not None else None
    if ev is None:
        raise ActionError(f"event not found: {target_id}")
    return ev


def _append_assistant_update(
    repo: Repository, member: Member, family_id: str, work_item_id: str, body: str
) -> WorkItemUpdate:
    """Append the source=assistant narration; author is the confirming member.

    Mints the ``update_id`` server-side (AWS_LLD §1), persists via the repo, and
    returns the DTO so a co-created event can set ``source_update_id`` to it.
    """
    upd = WorkItemUpdate(
        update_id=new_ulid(),
        author_id=member.id,
        source="assistant",
        body=body,
        created_at=datetime.now(UTC),
    )
    repo.append_update(family_id, work_item_id, upd)
    return upd


def _normalized_tags(value: object) -> list[str]:
    """Normalize optional shared-vocabulary tags into unique display strings."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ActionError("tags must be a list of strings")

    tags: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            raise ActionError("each tag must be a non-empty string")
        tag = raw.strip()
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags

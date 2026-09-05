"""Shared loading, time parsing, and log-append helpers for action domains."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.persistence.models import Event, Member, WorkItem, WorkItemUpdate
from app.routing.engine import ActionError


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ActionError(f"invalid datetime: {value!r}") from e


def _load_item(session: Session, target_id: int | None) -> WorkItem:
    wi = session.get(WorkItem, target_id) if target_id is not None else None
    if wi is None:
        raise ActionError(f"work item not found: {target_id}")
    return wi


def _load_event(session: Session, target_id: int | None) -> Event:
    ev = session.get(Event, target_id) if target_id is not None else None
    if ev is None:
        raise ActionError(f"event not found: {target_id}")
    return ev


def _append_assistant_update(
    session: Session, member: Member, work_item_id: int, body: str
) -> WorkItemUpdate:
    """Append the source=assistant narration; author is the confirming member."""
    upd = WorkItemUpdate(
        work_item_id=work_item_id,
        author_id=member.id,
        source="assistant",
        body=body,
        created_at=datetime.now(UTC),
    )
    session.add(upd)
    session.flush()  # assign id (create_event links to it)
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

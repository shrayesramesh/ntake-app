"""Normalize event participants to name-only strings.

Revision ID: 7f6a4d2b9e31
Revises: 32cf7ce43767
Create Date: 2026-09-04
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "7f6a4d2b9e31"
down_revision = "32cf7ce43767"
branch_labels = None
depends_on = None


def _normalized_names(raw: object, member_names: dict[int, str]) -> list[str]:
    """Convert legacy participant JSON to unique, trimmed display names."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    if not isinstance(raw, list):
        return []

    names: list[str] = []
    seen: set[str] = set()
    for participant in raw:
        if isinstance(participant, str):
            name = participant
        elif isinstance(participant, dict):
            name = participant.get("name")
            if not isinstance(name, str):
                member_id = participant.get("member_id")
                name = member_names.get(member_id) if isinstance(member_id, int) else None
        else:
            name = None
        if isinstance(name, str) and name.strip():
            normalized = name.strip()
            key = normalized.casefold()
            if key not in seen:
                seen.add(key)
                names.append(normalized)
    return names


def upgrade() -> None:
    bind = op.get_bind()
    member_names = {
        row.id: row.display_name
        for row in bind.execute(sa.text("SELECT id, display_name FROM members"))
    }
    events = bind.execute(sa.text("SELECT id, participants FROM events")).all()
    for event in events:
        participants = _normalized_names(event.participants, member_names)
        bind.execute(
            sa.text("UPDATE events SET participants = :participants WHERE id = :id"),
            {"id": event.id, "participants": json.dumps(participants)},
        )


def downgrade() -> None:
    # Name-only participants intentionally cannot be losslessly restored to IDs.
    pass

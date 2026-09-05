"""A deterministic Alex-and-Sam household used by config and database tests."""

from __future__ import annotations

import tomllib
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import FamilyConfig, seed_from_config
from app.persistence.models import (
    ChecklistItem,
    Event,
    Member,
    WorkItem,
    WorkItemUpdate,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TIMEZONE = "America/New_York"

ALEX_SAM_TOML = """
[family]
name = "Alex and Sam Household"
timezone = "America/New_York"

[[members]]
display_name = "Alex"
role = "adult"

[[members]]
display_name = "Sam"
role = "child"
"""

ALEX_SAM_CONFIG = FamilyConfig.model_validate(tomllib.loads(ALEX_SAM_TOML))


def seed_alex_sam_household(session: Session) -> SimpleNamespace:
    """Seed a household-shaped DB from the shared Alex-and-Sam config.

    Identity rows come through the production ``seed_from_config`` path. The
    additional rows deliberately cover every active product surface: board
    status/assignment/due date, ordered checklists, human and assistant update
    history, linked event provenance, participant workload, all-day timing, and
    an archived/out-of-window history case.
    """
    family = seed_from_config(session, ALEX_SAM_CONFIG)
    members = {
        member.display_name: member
        for member in session.scalars(
            select(Member).where(Member.family_id == family.id).order_by(Member.id)
        ).all()
    }
    alex = members["Alex"]
    sam = members["Sam"]

    groceries = WorkItem(
        family_id=family.id,
        assigned_to=alex.id,
        title="Groceries",
        description="Weekly grocery list",
        status="todo",
        position=1,
        tags=["household"],
        created_at=NOW,
        updated_at=NOW,
    )
    plumber = WorkItem(
        family_id=family.id,
        assigned_to=alex.id,
        title="Call plumber",
        description="Kitchen tap drips",
        status="doing",
        position=1,
        due_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        tags=["household", "urgent"],
        created_at=NOW - timedelta(days=2),
        updated_at=NOW - timedelta(days=1),
    )
    school_forms = WorkItem(
        family_id=family.id,
        assigned_to=sam.id,
        title="School forms",
        description="Return permission slip",
        status="on_deck",
        position=1,
        tags=["school", "Sam"],
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )
    taxes = WorkItem(
        family_id=family.id,
        assigned_to=alex.id,
        title="File taxes",
        status="done",
        position=1,
        tags=["household"],
        created_at=NOW - timedelta(days=30),
        updated_at=NOW - timedelta(days=2),
        completed_at=NOW - timedelta(days=2),
    )
    old_chore = WorkItem(
        family_id=family.id,
        title="Old chore",
        status="done",
        position=2,
        created_at=NOW - timedelta(days=60),
        updated_at=NOW - timedelta(days=40),
        completed_at=NOW - timedelta(days=40),
        archived_at=NOW - timedelta(days=30),
    )
    session.add_all([groceries, plumber, school_forms, taxes, old_chore])
    session.flush()

    grocery_checklist = [
        ChecklistItem(work_item_id=groceries.id, text="milk", position=1),
        ChecklistItem(
            work_item_id=groceries.id, text="bread", checked=True, position=2
        ),
        ChecklistItem(work_item_id=groceries.id, text="eggs", position=3),
    ]
    plumber_human = WorkItemUpdate(
        work_item_id=plumber.id,
        author_id=alex.id,
        source="human",
        body="Called the plumber; waiting for an appointment.",
        created_at=NOW - timedelta(days=1, hours=2),
    )
    plumber_assistant = WorkItemUpdate(
        work_item_id=plumber.id,
        author_id=alex.id,
        source="assistant",
        body="Set due date to 2026-09-05T19:00:00+00:00",
        created_at=NOW - timedelta(days=1, hours=1),
    )
    tax_update = WorkItemUpdate(
        work_item_id=taxes.id,
        author_id=alex.id,
        source="human",
        body="Filed and submitted the return.",
        created_at=NOW - timedelta(days=2),
    )
    session.add_all([*grocery_checklist, plumber_human, plumber_assistant, tax_update])
    session.flush()

    events = [
        Event(
            family_id=family.id,
            title="Soccer",
            location="North field",
            start_at=datetime(2026, 9, 1, 19, 0, tzinfo=UTC),
            end_at=datetime(2026, 9, 1, 20, 0, tzinfo=UTC),
            participants=["Sam", "Coach Lee"],
            tags=["school", "sports"],
            created_at=NOW,
            updated_at=NOW,
        ),
        Event(
            family_id=family.id,
            title="Plumber visit",
            start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
            end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
            participants=["Alex"],
            source_update_id=plumber_assistant.id,
            created_at=NOW,
            updated_at=NOW,
        ),
        Event(
            family_id=family.id,
            title="Dentist",
            start_at=datetime(2026, 12, 1, 19, 0, tzinfo=UTC),
            end_at=datetime(2026, 12, 1, 20, 0, tzinfo=UTC),
            participants=["Alex"],
            created_at=NOW,
            updated_at=NOW,
        ),
        Event(
            family_id=family.id,
            title="Holiday",
            all_day=True,
            start_date=date(2026, 9, 5),
            end_date=date(2026, 9, 5),
            participants=["Sam"],
            created_at=NOW,
            updated_at=NOW,
        ),
        Event(
            family_id=family.id,
            title="Old picnic",
            start_at=datetime(2026, 8, 4, 19, 0, tzinfo=UTC),
            end_at=datetime(2026, 8, 4, 20, 0, tzinfo=UTC),
            created_at=NOW,
            updated_at=NOW,
        ),
    ]
    session.add_all(events)
    session.commit()

    return SimpleNamespace(
        family=family,
        now=NOW,
        tz=TIMEZONE,
        members={name: member.id for name, member in members.items()},
        items={
            "groceries": groceries.id,
            "plumber": plumber.id,
            "school_forms": school_forms.id,
            "taxes": taxes.id,
            "old_chore": old_chore.id,
        },
        events={
            "soccer": events[0].id,
            "plumber_visit": events[1].id,
            "dentist": events[2].id,
            "holiday": events[3].id,
            "old_picnic": events[4].id,
        },
        updates={
            "plumber_human": plumber_human.id,
            "plumber_assistant": plumber_assistant.id,
            "taxes": tax_update.id,
        },
        checklists={"groceries": [item.id for item in grocery_checklist]},
    )

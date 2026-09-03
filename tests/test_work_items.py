"""Phase 3, checkpoint 1 — work-item data model.

WorkItem + append-only WorkItemUpdate (source human|assistant, author -> members)
+ ChecklistItem, per DESIGN §3 / §3.1. Status is a fixed code set; tags are a
JSON list (portable, no SQLite array type). FKs: work_item children CASCADE;
assigned_to/author/source_update_id SET NULL.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import (
    ChecklistItem,
    Event,
    Family,
    Member,
    WorkItem,
    WorkItemUpdate,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _fam_member(session) -> tuple[Family, Member]:
    fam = Family(name="Fam", timezone="America/New_York")
    session.add(fam)
    session.commit()
    m = Member(family_id=fam.id, display_name="Adult", role="adult", created_at=NOW)
    session.add(m)
    session.commit()
    return fam, m


def test_work_item_roundtrip_and_defaults(session):
    fam, m = _fam_member(session)
    wi = WorkItem(
        family_id=fam.id,
        title="Fix the sink",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(wi)
    session.commit()

    got = session.get(WorkItem, wi.id)
    assert got.title == "Fix the sink"
    assert got.status == "todo"  # default column
    assert got.description is None
    assert got.assigned_to is None
    assert got.due_at is None
    assert got.tags == []  # default empty list
    assert got.completed_at is None
    assert got.archived_at is None


def test_work_item_tags_persist_as_list(session):
    fam, _ = _fam_member(session)
    wi = WorkItem(
        family_id=fam.id,
        title="Groceries",
        tags=["household", "Kid1"],
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(wi)
    session.commit()
    session.expire_all()
    assert session.get(WorkItem, wi.id).tags == ["household", "Kid1"]


def test_update_log_appends_with_source_and_author(session):
    fam, m = _fam_member(session)
    wi = WorkItem(family_id=fam.id, title="Task", created_at=NOW, updated_at=NOW)
    session.add(wi)
    session.commit()

    u = WorkItemUpdate(
        work_item_id=wi.id,
        author_id=m.id,
        source="human",
        body="called the plumber, waiting to hear back",
        created_at=NOW,
    )
    session.add(u)
    session.commit()

    got = session.get(WorkItemUpdate, u.id)
    assert got.work_item_id == wi.id
    assert got.author_id == m.id
    assert got.source == "human"
    assert "plumber" in got.body


def test_deleting_work_item_cascades_updates_and_checklist(session):
    fam, m = _fam_member(session)
    wi = WorkItem(family_id=fam.id, title="Task", created_at=NOW, updated_at=NOW)
    session.add(wi)
    session.commit()
    session.add(
        WorkItemUpdate(work_item_id=wi.id, source="human", body="note", created_at=NOW)
    )
    session.add(ChecklistItem(work_item_id=wi.id, text="milk", position=0))
    session.commit()

    session.delete(wi)
    session.commit()

    assert session.query(WorkItemUpdate).count() == 0
    assert session.query(ChecklistItem).count() == 0


def test_checklist_item_defaults(session):
    fam, _ = _fam_member(session)
    wi = WorkItem(family_id=fam.id, title="Shop", created_at=NOW, updated_at=NOW)
    session.add(wi)
    session.commit()
    ci = ChecklistItem(work_item_id=wi.id, text="eggs", position=0)
    session.add(ci)
    session.commit()
    got = session.get(ChecklistItem, ci.id)
    assert got.text == "eggs"
    assert got.checked is False
    assert got.position == 0


def test_event_source_update_id_is_fk_to_update(session):
    """events.source_update_id now references work_item_updates.id (SET NULL)."""
    fam, m = _fam_member(session)
    wi = WorkItem(family_id=fam.id, title="Task", created_at=NOW, updated_at=NOW)
    session.add(wi)
    session.commit()
    u = WorkItemUpdate(
        work_item_id=wi.id, author_id=m.id, source="human", body="b", created_at=NOW
    )
    session.add(u)
    session.commit()

    ev = Event(
        family_id=fam.id,
        title="Plumber visit",
        source_update_id=u.id,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(ev)
    session.commit()
    assert session.get(Event, ev.id).source_update_id == u.id


def test_member_delete_sets_author_and_assignee_null(session):
    """Removing a member unlinks (SET NULL), doesn't delete their work rows.

    Relies on PRAGMA foreign_keys=ON (enabled on the app + test engines).
    """
    fam, m = _fam_member(session)
    wi = WorkItem(
        family_id=fam.id,
        assigned_to=m.id,
        title="T",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(wi)
    session.commit()
    u = WorkItemUpdate(
        work_item_id=wi.id, author_id=m.id, source="human", body="b", created_at=NOW
    )
    session.add(u)
    session.commit()

    session.delete(m)
    session.commit()
    session.expire_all()  # factory uses expire_on_commit=False; reload from DB

    assert session.get(WorkItem, wi.id).assigned_to is None
    assert session.get(WorkItemUpdate, u.id).author_id is None

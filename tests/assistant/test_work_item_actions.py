"""Work-item assistant action handlers and proposal-card behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.assistant.actions.registry import ACTIONS, apply_action
from app.persistence.models import Family, Member, WorkItem, WorkItemUpdate
from app.routing.engine import ActionError

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_set_due_date_sets_field_and_logs(session, fam_member_item):
    fam, m, wi = fam_member_item
    due = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)

    apply_action(session, m, "set_due_date", wi.id, {"due_at": due.isoformat()})

    session.expire_all()
    got = session.get(WorkItem, wi.id)
    assert got.due_at is not None
    # An assistant-sourced update was appended, authored by the confirmer.
    upd = session.query(WorkItemUpdate).one()
    assert upd.work_item_id == wi.id
    assert upd.source == "assistant"
    assert upd.author_id == m.id


def test_complete_work_item_sets_status_and_completed_at(session, fam_member_item):
    fam, m, wi = fam_member_item

    apply_action(session, m, "complete_work_item", wi.id, {})

    session.expire_all()
    got = session.get(WorkItem, wi.id)
    assert got.status == "done"
    assert got.completed_at is not None
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1


def test_start_work_item_sets_doing_and_logs(session, fam_member_item):
    fam, m, wi = fam_member_item
    apply_action(session, m, "start_work_item", wi.id, {})
    session.expire_all()
    assert session.get(WorkItem, wi.id).status == "doing"
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1


def test_move_to_on_deck_sets_status(session, fam_member_item):
    fam, m, wi = fam_member_item
    apply_action(session, m, "move_to_on_deck", wi.id, {})
    session.expire_all()
    assert session.get(WorkItem, wi.id).status == "on_deck"


def test_move_to_todo_sets_status(session, fam_member_item):
    fam, m, wi = fam_member_item
    wi.status = "doing"
    session.commit()
    apply_action(session, m, "move_to_todo", wi.id, {})
    session.expire_all()
    assert session.get(WorkItem, wi.id).status == "todo"


def test_reopen_work_item_clears_completed_at(session, fam_member_item):
    fam, m, wi = fam_member_item
    # first complete it, then reopen.
    apply_action(session, m, "complete_work_item", wi.id, {})
    apply_action(session, m, "reopen_work_item", wi.id, {})
    session.expire_all()
    got = session.get(WorkItem, wi.id)
    assert got.status == "todo"
    assert got.completed_at is None


def test_create_work_item_inserts_new_item(session, fam_member_item):
    fam, m, wi = fam_member_item

    # create_work_item ignores target_id; it makes a NEW item.
    apply_action(
        session,
        m,
        "create_work_item",
        None,
        {"title": "buy stamps", "tags": ["errand"]},
    )

    session.expire_all()
    items = {w.title for w in session.query(WorkItem).all()}
    assert "buy stamps" in items
    new = session.query(WorkItem).filter_by(title="buy stamps").one()
    assert new.family_id == m.family_id
    assert new.status == "todo"
    assert new.tags == ["errand"]


def test_create_work_item_can_atomically_seed_a_checklist(session, fam_member):
    from app.persistence.models import ChecklistItem

    _fam, m = fam_member
    apply_action(
        session,
        m,
        "create_work_item",
        None,
        {
            "title": "Grocery list",
            "checklist_items": ["milk", "eggs", "bread"],
        },
    )

    session.expire_all()
    work_item = session.query(WorkItem).filter_by(title="Grocery list").one()
    checklist = (
        session.query(ChecklistItem)
        .filter_by(work_item_id=work_item.id)
        .order_by(ChecklistItem.position)
        .all()
    )
    assert [item.text for item in checklist] == ["milk", "eggs", "bread"]
    assert [item.position for item in checklist] == [1, 2, 3]


def test_create_work_item_rejects_an_empty_checklist(session, fam_member):
    _fam, m = fam_member

    with pytest.raises(ActionError):
        apply_action(
            session,
            m,
            "create_work_item",
            None,
            {"title": "Grocery list", "checklist_items": []},
        )


def test_append_update_writes_assistant_context_without_other_mutation(
    session, fam_member_item
):
    _fam, m, wi = fam_member_item
    original_status = wi.status
    original_due_at = wi.due_at

    apply_action(
        session,
        m,
        "append_update",
        wi.id,
        {"body": "Vendor confirmed delivery is delayed until Friday."},
    )

    session.expire_all()
    updated = session.get(WorkItem, wi.id)
    entry = session.query(WorkItemUpdate).one()
    assert updated.status == original_status and updated.due_at == original_due_at
    assert entry.source == "assistant" and entry.author_id == m.id
    assert entry.body == "Vendor confirmed delivery is delayed until Friday."


def test_unknown_action_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "frobnicate", wi.id, {})


def test_missing_required_param_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "set_due_date", wi.id, {})


def test_apply_to_missing_work_item_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "complete_work_item", 9999, {})


def test_invalid_datetime_param_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "set_due_date", wi.id, {"due_at": "not-a-date"})


def test_assign_work_item_sets_assignee_and_logs(session, fam_member_item):
    fam, m, wi = fam_member_item
    sam = Member(family_id=fam.id, display_name="Sam", role="child", created_at=NOW)
    session.add(sam)
    session.commit()

    apply_action(session, m, "assign_work_item", wi.id, {"member_id": sam.id})

    session.expire_all()
    assert session.get(WorkItem, wi.id).assigned_to == sam.id
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1


def test_assign_work_item_rejects_member_from_another_family(session, fam_member_item):
    fam, m, wi = fam_member_item
    other_fam = Family(name="Other", timezone="UTC")
    session.add(other_fam)
    session.commit()
    outsider = Member(
        family_id=other_fam.id, display_name="Outsider", role="adult", created_at=NOW
    )
    session.add(outsider)
    session.commit()

    with pytest.raises(ActionError):
        apply_action(session, m, "assign_work_item", wi.id, {"member_id": outsider.id})
    session.expire_all()
    assert session.get(WorkItem, wi.id).assigned_to is None


def test_assign_work_item_rejects_unknown_member(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "assign_work_item", wi.id, {"member_id": 9999})


def test_archive_work_item_requires_done(session, fam_member_item):
    fam, m, wi = fam_member_item  # status defaults to "todo"
    with pytest.raises(ActionError):
        apply_action(session, m, "archive_work_item", wi.id, {})
    session.expire_all()
    assert session.get(WorkItem, wi.id).archived_at is None


def test_archive_work_item_archives_a_done_item(session, fam_member_item):
    fam, m, wi = fam_member_item
    apply_action(session, m, "complete_work_item", wi.id, {})
    apply_action(session, m, "archive_work_item", wi.id, {})
    session.expire_all()
    assert session.get(WorkItem, wi.id).archived_at is not None


def test_add_checklist_items_inserts_rows(session, fam_member_item):
    from app.persistence.models import ChecklistItem

    fam, m, wi = fam_member_item
    apply_action(
        session, m, "add_checklist_items", wi.id, {"items": ["milk", "eggs", "bread"]}
    )
    session.expire_all()
    rows = (
        session.query(ChecklistItem)
        .filter_by(work_item_id=wi.id)
        .order_by(ChecklistItem.position)
        .all()
    )
    assert [r.text for r in rows] == ["milk", "eggs", "bread"]
    assert [r.position for r in rows] == [1, 2, 3]


def test_add_checklist_items_appends_after_existing(session, fam_member_item):
    from app.persistence.models import ChecklistItem

    fam, m, wi = fam_member_item
    session.add(ChecklistItem(work_item_id=wi.id, text="existing", position=1))
    session.commit()
    apply_action(session, m, "add_checklist_items", wi.id, {"items": ["new"]})
    session.expire_all()
    new = session.query(ChecklistItem).filter_by(text="new").one()
    assert new.position == 2


def test_add_checklist_items_requires_nonempty_list(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "add_checklist_items", wi.id, {"items": []})


def _card(name: str, params: dict, resolved: dict | None = None) -> list[str]:
    spec = ACTIONS[name]
    assert spec.render_card is not None, f"{name} has no render_card"
    return spec.render_card(params, resolved or {})


def test_render_card_assign_resolves_member_name():
    lines = _card("assign_work_item", {"member_id": 2}, {"member_names": {2: "Sam"}})
    assert any("Sam" in ln for ln in lines)
    assert not any("member 2" in ln for ln in lines)


def test_render_card_assign_falls_back_to_id_without_map():
    lines = _card("assign_work_item", {"member_id": 2}, {})
    assert any("2" in ln for ln in lines)


def test_render_card_set_due_date_shows_the_date():
    lines = _card("set_due_date", {"due_at": "2026-09-10T14:00:00Z"})
    assert any("2026-09-10" in ln for ln in lines)


def test_render_card_create_work_item_shows_seed_checklist_items():
    lines = _card(
        "create_work_item",
        {"title": "Grocery list", "checklist_items": ["milk", "eggs"]},
    )

    assert "Grocery list" in " ".join(lines)
    assert "milk, eggs" in " ".join(lines)


def test_render_card_append_update_shows_body():
    lines = _card("append_update", {"body": "Vendor confirmed the delay."})

    assert "Vendor confirmed the delay." in " ".join(lines)


def test_archive_all_done_archives_only_current_family_open_done_items(
    session, fam_member_item
):
    family, member, todo = fam_member_item
    done_one = WorkItem(
        family_id=family.id,
        title="Done one",
        status="done",
        created_at=NOW,
        updated_at=NOW,
    )
    done_two = WorkItem(
        family_id=family.id,
        title="Done two",
        status="done",
        created_at=NOW,
        updated_at=NOW,
    )
    already_archived = WorkItem(
        family_id=family.id,
        title="Already archived",
        status="done",
        created_at=NOW,
        updated_at=NOW,
        archived_at=NOW,
    )
    other_family = Family(name="Other", timezone="UTC")
    session.add_all([done_one, done_two, already_archived, other_family])
    session.flush()
    foreign_done = WorkItem(
        family_id=other_family.id,
        title="Foreign done",
        status="done",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(foreign_done)
    session.commit()

    summary = apply_action(session, member, "archive_all_done", None, {})

    session.expire_all()
    assert summary == "Archived 2 done work items"
    assert session.get(WorkItem, done_one.id).archived_at is not None
    assert session.get(WorkItem, done_two.id).archived_at is not None
    assert session.get(WorkItem, todo.id).archived_at is None
    assert session.get(WorkItem, already_archived.id).archived_at == NOW.replace(
        tzinfo=None
    )
    assert session.get(WorkItem, foreign_done.id).archived_at is None
    assert session.query(WorkItemUpdate).count() == 0


def test_check_off_items_marks_named_checklist_items_and_logs(session, fam_member_item):
    from app.persistence.models import ChecklistItem

    _family, member, work_item = fam_member_item
    milk = ChecklistItem(work_item_id=work_item.id, text="milk", position=1)
    bread = ChecklistItem(work_item_id=work_item.id, text="bread", position=2)
    session.add_all([milk, bread])
    session.commit()

    summary = apply_action(
        session,
        member,
        "check_off_items",
        work_item.id,
        {"items": [" Milk "]},
    )

    session.expire_all()
    assert summary == "Checked off 1 checklist item"
    assert session.get(ChecklistItem, milk.id).checked is True
    assert session.get(ChecklistItem, bread.id).checked is False
    assert session.query(WorkItemUpdate).one().body == "Checked off 1 checklist item"


def test_check_off_items_rejects_unknown_checklist_names(session, fam_member_item):
    _family, member, work_item = fam_member_item

    with pytest.raises(ActionError):
        apply_action(
            session,
            member,
            "check_off_items",
            work_item.id,
            {"items": ["not on this list"]},
        )


def test_set_work_item_tags_replaces_and_clears_tags(session, fam_member_item):
    _family, member, work_item = fam_member_item
    work_item.tags = ["old"]
    session.commit()

    apply_action(
        session,
        member,
        "set_work_item_tags",
        work_item.id,
        {"tags": [" Household ", "household", "urgent"]},
    )
    apply_action(session, member, "set_work_item_tags", work_item.id, {"tags": []})

    session.expire_all()
    assert session.get(WorkItem, work_item.id).tags == []
    updates = session.query(WorkItemUpdate).filter_by(work_item_id=work_item.id).all()
    assert [update.body for update in updates] == [
        "Set tags: Household, urgent",
        "Set tags: (none)",
    ]

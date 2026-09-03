"""Phase 4, task 2 — action registry + apply-handlers (v1).

The registry is a plain dict ``ACTIONS: name -> ActionSpec``. Each spec's
``apply(session, member, target_id, params)`` performs the mutation AND (except
``no_action``) appends a ``source=assistant`` work_item_updates row authored by
the confirming member (the universal on-confirm rule). Light param validation;
missing required params raise ActionError (the caller drops the action).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.assistant.actions import ACTIONS, ActionError, apply_action
from app.models import Event, Family, Member, WorkItem, WorkItemUpdate

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_registry_has_v1_actions():
    assert set(ACTIONS) == {
        "set_due_date",
        "create_event",
        "complete_work_item",
        "start_work_item",
        "move_to_on_deck",
        "move_to_todo",
        "reopen_work_item",
        "assign_work_item",
        "archive_work_item",
        "add_checklist_items",
        "create_work_item",
        "reschedule_event",
        "no_action",
        "deconflict_events",
    }


def test_every_action_has_a_describe():
    # describe(params) -> the deterministic, registry-derived action_summary
    # (ground truth: what the action WILL do), separate from any LLM narration.
    for name, spec in ACTIONS.items():
        assert callable(spec.describe), name


def test_all_actions_are_wellformed():
    """Registry-wide contract guard: every action (including any added later) is
    well-formed, so a new entry can't silently break the propose/confirm flow.

    Each spec must have a callable apply + describe, a describe that returns a
    non-empty str on empty params (it runs on unconfirmed proposals), and
    boolean needs_target/logs flags. no_action is the sole logs=False entry.
    """
    for name, spec in ACTIONS.items():
        assert callable(spec.apply), f"{name}: apply not callable"
        assert callable(spec.describe), f"{name}: describe not callable"
        assert isinstance(spec.describe({}), str) and spec.describe({}), name
        assert isinstance(spec.needs_target, bool), name
        assert isinstance(spec.logs, bool), name
        assert isinstance(spec.required, list), name
    # Exactly the actions that don't operate on an existing item skip a target.
    assert ACTIONS["create_work_item"].needs_target is False
    assert ACTIONS["no_action"].needs_target is False
    # Non-logging actions: no_action (meta) and event-only actions (no work item
    # to log against, e.g. deconflict_events / reschedule_event).
    assert {n for n, s in ACTIONS.items() if not s.logs} == {
        "no_action",
        "deconflict_events",
        "reschedule_event",
    }


def test_describe_set_due_date_uses_param():
    text = ACTIONS["set_due_date"].describe({"due_at": "2026-09-05T19:00:00+00:00"})
    assert "2026-09-05" in text
    assert "due" in text.lower()


def test_describe_create_event_uses_title():
    text = ACTIONS["create_event"].describe(
        {"title": "Plumber visit", "start_at": "2026-09-05T19:00:00+00:00"}
    )
    assert "Plumber visit" in text
    assert "event" in text.lower()


def test_describe_complete_work_item():
    text = ACTIONS["complete_work_item"].describe({})
    assert "done" in text.lower() or "complete" in text.lower()


def test_describe_create_work_item_uses_title():
    text = ACTIONS["create_work_item"].describe({"title": "buy stamps"})
    assert "buy stamps" in text


def test_describe_no_action():
    text = ACTIONS["no_action"].describe({})
    assert isinstance(text, str) and text


def test_describe_is_deterministic():
    params = {"due_at": "2026-09-05T19:00:00+00:00"}
    a = ACTIONS["set_due_date"].describe(params)
    b = ACTIONS["set_due_date"].describe(params)
    assert a == b


def test_describe_create_event_title_only():
    # Title but no timing yet: still a meaningful, deterministic summary with no
    # dangling "at <when>" clause.
    text = ACTIONS["create_event"].describe({"title": "Plumber visit"})
    assert "Plumber visit" in text
    assert " at " not in text


def test_describe_action_seam_resolves_and_falls_back():
    from app.assistant.actions import REGISTRY

    # Known action -> the registry-derived summary.
    got = REGISTRY.describe("create_work_item", {"title": "buy stamps"})
    assert "buy stamps" in got
    # Unknown action -> the name itself (display-only; never raises).
    assert REGISTRY.describe("frobnicate", {}) == "frobnicate"


def test_describe_tolerates_missing_params():
    # describe runs on unconfirmed proposals; it must not raise on absent keys
    # (validation happens at apply time, not describe time).
    for spec in ACTIONS.values():
        assert isinstance(spec.describe({}), str)


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


def test_create_event_inserts_and_links_source_update(session, fam_member_item):
    fam, m, wi = fam_member_item
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC)

    apply_action(
        session,
        m,
        "create_event",
        wi.id,
        {
            "title": "Plumber visit",
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )

    session.expire_all()
    ev = session.query(Event).one()
    assert ev.title == "Plumber visit"
    assert ev.family_id == fam.id
    # The event links back to the assistant update that drove it (EVENT-7).
    upd = session.query(WorkItemUpdate).filter_by(source="assistant").one()
    assert ev.source_update_id == upd.id


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


def test_no_action_does_nothing(session, fam_member_item):
    fam, m, wi = fam_member_item

    apply_action(session, m, "no_action", wi.id, {})

    session.expire_all()
    assert session.query(WorkItemUpdate).count() == 0  # no update appended
    assert session.query(Event).count() == 0


def test_unknown_action_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "frobnicate", wi.id, {})


def test_missing_required_param_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "set_due_date", wi.id, {})  # no due_at


def test_apply_to_missing_work_item_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "complete_work_item", 9999, {})


def test_invalid_datetime_param_raises(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "set_due_date", wi.id, {"due_at": "not-a-date"})


# --- Group B: assign / reschedule / archive / checklist -------------------


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
    assert session.get(WorkItem, wi.id).assigned_to is None  # not assigned


def test_assign_work_item_rejects_unknown_member(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "assign_work_item", wi.id, {"member_id": 9999})


def test_reschedule_event_updates_timing_only(session, fam_member_item):
    fam, m, wi = fam_member_item
    ev = Event(
        family_id=fam.id,
        title="Dentist",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(ev)
    session.commit()

    new_start = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)
    apply_action(
        session,
        m,
        "reschedule_event",
        ev.id,
        {"start_at": new_start.isoformat(), "end_at": new_start.isoformat()},
        target_type="event",
    )

    session.expire_all()
    got = session.get(Event, ev.id)
    assert got.start_at.replace(tzinfo=UTC) == new_start
    assert got.title == "Dentist"  # only timing changed
    # Event-only: no work-item update appended.
    assert session.query(WorkItemUpdate).count() == 0


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
    from app.models import ChecklistItem

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
    from app.models import ChecklistItem

    fam, m, wi = fam_member_item
    session.add(ChecklistItem(work_item_id=wi.id, text="existing", position=1))
    session.commit()
    apply_action(session, m, "add_checklist_items", wi.id, {"items": ["new"]})
    session.expire_all()
    new = session.query(ChecklistItem).filter_by(text="new").one()
    assert new.position == 2  # appended after the existing max


def test_add_checklist_items_requires_nonempty_list(session, fam_member_item):
    fam, m, wi = fam_member_item
    with pytest.raises(ActionError):
        apply_action(session, m, "add_checklist_items", wi.id, {"items": []})

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


def _fam_member_item(session):
    fam = Family(name="F", timezone="America/New_York")
    session.add(fam)
    session.commit()
    m = Member(family_id=fam.id, display_name="A", role="adult", created_at=NOW)
    session.add(m)
    session.commit()
    wi = WorkItem(
        family_id=fam.id, title="call plumber", created_at=NOW, updated_at=NOW
    )
    session.add(wi)
    session.commit()
    return fam, m, wi


def test_registry_has_v1_actions():
    assert set(ACTIONS) == {
        "set_due_date",
        "create_event",
        "complete_work_item",
        "create_work_item",
        "no_action",
    }


def test_every_action_has_a_describe():
    # describe(params) -> the deterministic, registry-derived action_summary
    # (ground truth: what the action WILL do), separate from any LLM narration.
    for name, spec in ACTIONS.items():
        assert callable(spec.describe), name


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
    from app.assistant.actions import describe_action

    # Known action -> the registry-derived summary.
    assert "buy stamps" in describe_action("create_work_item", {"title": "buy stamps"})
    # Unknown action -> the name itself (display-only; never raises).
    assert describe_action("frobnicate", {}) == "frobnicate"


def test_describe_tolerates_missing_params():
    # describe runs on unconfirmed proposals; it must not raise on absent keys
    # (validation happens at apply time, not describe time).
    for spec in ACTIONS.values():
        assert isinstance(spec.describe({}), str)


def test_set_due_date_sets_field_and_logs(session):
    fam, m, wi = _fam_member_item(session)
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


def test_complete_work_item_sets_status_and_completed_at(session):
    fam, m, wi = _fam_member_item(session)

    apply_action(session, m, "complete_work_item", wi.id, {})

    session.expire_all()
    got = session.get(WorkItem, wi.id)
    assert got.status == "done"
    assert got.completed_at is not None
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1


def test_create_event_inserts_and_links_source_update(session):
    fam, m, wi = _fam_member_item(session)
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


def test_create_work_item_inserts_new_item(session):
    fam, m, wi = _fam_member_item(session)

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


def test_no_action_does_nothing(session):
    fam, m, wi = _fam_member_item(session)

    apply_action(session, m, "no_action", wi.id, {})

    session.expire_all()
    assert session.query(WorkItemUpdate).count() == 0  # no update appended
    assert session.query(Event).count() == 0


def test_unknown_action_raises(session):
    fam, m, wi = _fam_member_item(session)
    with pytest.raises(ActionError):
        apply_action(session, m, "frobnicate", wi.id, {})


def test_missing_required_param_raises(session):
    fam, m, wi = _fam_member_item(session)
    with pytest.raises(ActionError):
        apply_action(session, m, "set_due_date", wi.id, {})  # no due_at


def test_apply_to_missing_work_item_raises(session):
    fam, m, wi = _fam_member_item(session)
    with pytest.raises(ActionError):
        apply_action(session, m, "complete_work_item", 9999, {})


def test_invalid_datetime_param_raises(session):
    fam, m, wi = _fam_member_item(session)
    with pytest.raises(ActionError):
        apply_action(session, m, "set_due_date", wi.id, {"due_at": "not-a-date"})

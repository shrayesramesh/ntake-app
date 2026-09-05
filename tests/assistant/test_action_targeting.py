"""Cross-domain target and labor-log semantics for assistant actions."""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.actions.registry import apply_action
from app.persistence.models import Event, WorkItem, WorkItemUpdate

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _event_params():
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC)
    return {
        "title": "Plumber visit",
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
    }


def test_create_timed_event_standalone_creates_event_without_work_item_update(
    session, fam_member
):
    fam, m = fam_member

    apply_action(
        session,
        m,
        "create_timed_event",
        target_id=None,
        params=_event_params(),
        target_type=None,
    )

    session.expire_all()
    ev = session.query(Event).one()
    assert ev.title == "Plumber visit"
    assert ev.family_id == fam.id
    # Standalone: it is NOT linked to a work_item_update...
    assert ev.source_update_id is None
    # ...and NO work-item update row was appended (events aren't labor log).
    assert session.query(WorkItemUpdate).count() == 0


def test_create_timed_event_explicit_event_target_type_also_standalone(
    session, fam_member
):
    fam, m = fam_member

    apply_action(
        session,
        m,
        "create_timed_event",
        target_id=None,
        params=_event_params(),
        target_type="event",
    )

    session.expire_all()
    assert session.query(Event).count() == 1
    assert session.query(WorkItemUpdate).count() == 0


def test_create_timed_event_from_work_item_links_and_logs(session, fam_member_item):
    fam, m, wi = fam_member_item

    apply_action(
        session,
        m,
        "create_timed_event",
        target_id=wi.id,
        params=_event_params(),
        target_type="work_item",
    )

    session.expire_all()
    ev = session.query(Event).one()
    upd = session.query(WorkItemUpdate).filter_by(source="assistant").one()
    # Work-item-targeted: the event links back to the driving update (EVENT-7)...
    assert ev.source_update_id == upd.id
    # ...and the update is on that work item, authored by the confirmer.
    assert upd.work_item_id == wi.id
    assert upd.author_id == m.id


def test_set_due_date_still_logs_a_work_item_update(session, fam_member_item):
    fam, m, wi = fam_member_item
    due = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)

    apply_action(
        session,
        m,
        "set_due_date",
        target_id=wi.id,
        params={"due_at": due.isoformat()},
        target_type="work_item",
    )

    session.expire_all()
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1


def test_complete_work_item_still_logs(session, fam_member_item):
    fam, m, wi = fam_member_item

    apply_action(
        session,
        m,
        "complete_work_item",
        target_id=wi.id,
        params={},
        target_type="work_item",
    )

    session.expire_all()
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1


def test_create_work_item_logs_on_the_new_item(session, fam_member):
    fam, m = fam_member

    apply_action(
        session,
        m,
        "create_work_item",
        target_id=None,
        params={"title": "buy stamps"},
        target_type=None,
    )

    session.expire_all()
    wi = session.query(WorkItem).filter_by(title="buy stamps").one()
    assert (
        session.query(WorkItemUpdate)
        .filter_by(work_item_id=wi.id, source="assistant")
        .count()
        == 1
    )


def test_apply_action_target_type_defaults_to_work_item_semantics(
    session, fam_member_item
):
    """Omitting target_type with a work-item target_id still logs (default path)."""
    fam, m, wi = fam_member_item

    apply_action(session, m, "complete_work_item", target_id=wi.id, params={})

    session.expire_all()
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1

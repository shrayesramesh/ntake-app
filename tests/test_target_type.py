"""Task 12 — generalize the action target (work item | event | None).

An action may target a work item, an event, or nothing. The universal
"append a source=assistant work_item_update on confirm" rule is CONDITIONAL:
it fires only when the action targets a WORK ITEM. Event-only actions mutate the
event and append NO work-item update (events aren't part of the labor log,
WORKITEM-3). A standalone event create just inserts the event.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.actions import apply_action
from app.models import Event, Family, Member, WorkItem, WorkItemUpdate

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _fam_member(session):
    fam = Family(name="F", timezone="America/New_York")
    session.add(fam)
    session.commit()
    m = Member(family_id=fam.id, display_name="A", role="adult", created_at=NOW)
    session.add(m)
    session.commit()
    return fam, m


def _fam_member_item(session):
    fam, m = _fam_member(session)
    wi = WorkItem(
        family_id=fam.id, title="call plumber", created_at=NOW, updated_at=NOW
    )
    session.add(wi)
    session.commit()
    return fam, m, wi


def _event_params():
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC)
    return {
        "title": "Plumber visit",
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
    }


# --- standalone event: no work item, no work-item update ------------------


def test_create_event_standalone_creates_event_without_work_item_update(session):
    fam, m = _fam_member(session)

    apply_action(
        session,
        m,
        "create_event",
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


def test_create_event_explicit_event_target_type_also_standalone(session):
    fam, m = _fam_member(session)

    apply_action(
        session,
        m,
        "create_event",
        target_id=None,
        params=_event_params(),
        target_type="event",
    )

    session.expire_all()
    assert session.query(Event).count() == 1
    assert session.query(WorkItemUpdate).count() == 0


# --- event FROM a work item: link + log -----------------------------------


def test_create_event_from_work_item_links_and_logs(session):
    fam, m, wi = _fam_member_item(session)

    apply_action(
        session,
        m,
        "create_event",
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


# --- work-item actions still log (conditional rule unchanged for them) -----


def test_set_due_date_still_logs_a_work_item_update(session):
    fam, m, wi = _fam_member_item(session)
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


def test_complete_work_item_still_logs(session):
    fam, m, wi = _fam_member_item(session)

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


def test_create_work_item_logs_on_the_new_item(session):
    fam, m = _fam_member(session)

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


# --- target_type defaults (backwards compatible) --------------------------


def test_apply_action_target_type_defaults_to_work_item_semantics(session):
    """Omitting target_type with a work-item target_id still logs (default path)."""
    fam, m, wi = _fam_member_item(session)

    apply_action(session, m, "complete_work_item", target_id=wi.id, params={})

    session.expire_all()
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 1

"""Phase 4, task 5 — confirm endpoint.

The client sends back a chosen proposed action; the server looks it up in the
registry, validates, applies (mutation + source=assistant update), and commits
(publishing via the seam -> SSE). Dismiss is purely client-side (no call here).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Event, Family, Member, WorkItem, WorkItemUpdate

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _create(session) -> int:
    fam = session.query(Family).first()
    if fam is None:
        fam = Family(name="F", timezone="America/New_York")
        session.add(fam)
        session.commit()
    wi = WorkItem(
        family_id=fam.id, title="call plumber", created_at=NOW, updated_at=NOW
    )
    session.add(wi)
    session.commit()
    return wi.id


def test_confirm_requires_auth(client):
    r = client.post(
        "/actions/confirm",
        json={"name": "complete_work_item", "params": {}, "target_id": 1},
    )
    assert r.status_code == 401


def test_confirm_complete_applies_and_logs(client, session, auth_headers):
    wid = _create(session)
    r = client.post(
        "/actions/confirm",
        json={"name": "complete_work_item", "params": {}, "target_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 200

    session.expire_all()
    wi = session.get(WorkItem, wid)
    assert wi.status == "done" and wi.completed_at is not None
    # A source=assistant update was appended, authored by the confirming member.
    upd = session.query(WorkItemUpdate).filter_by(source="assistant").one()
    member = session.query(Member).one()
    assert upd.author_id == member.id


def test_confirm_set_due_date_applies(client, session, auth_headers):
    wid = _create(session)
    due = datetime(2026, 9, 5, 19, 0, tzinfo=UTC).isoformat()
    r = client.post(
        "/actions/confirm",
        json={"name": "set_due_date", "params": {"due_at": due}, "target_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    assert session.get(WorkItem, wid).due_at is not None


def test_confirm_create_event_applies(client, session, auth_headers):
    wid = _create(session)
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC).isoformat()
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC).isoformat()
    r = client.post(
        "/actions/confirm",
        json={
            "name": "create_event",
            "params": {"title": "Plumber visit", "start_at": start, "end_at": end},
            "target_id": wid,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    ev = session.query(Event).one()
    assert ev.title == "Plumber visit"


def test_confirm_create_event_standalone_no_work_item_update(
    client, session, auth_headers
):
    """A standalone event (target_type=event, no target_id) is created with NO
    work-item update — task 12 generalized target."""
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC).isoformat()
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC).isoformat()
    r = client.post(
        "/actions/confirm",
        json={
            "name": "create_event",
            "params": {"title": "Standalone party", "start_at": start, "end_at": end},
            "target_type": "event",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    ev = session.query(Event).filter_by(title="Standalone party").one()
    assert ev.source_update_id is None
    assert session.query(WorkItemUpdate).count() == 0


def test_confirm_unknown_action_is_422(client, session, auth_headers):
    wid = _create(session)
    r = client.post(
        "/actions/confirm",
        json={"name": "frobnicate", "params": {}, "target_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_confirm_missing_param_is_422(client, session, auth_headers):
    wid = _create(session)
    r = client.post(
        "/actions/confirm",
        json={"name": "set_due_date", "params": {}, "target_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_confirm_no_action_is_noop(client, session, auth_headers):
    wid = _create(session)
    r = client.post(
        "/actions/confirm",
        json={"name": "no_action", "params": {}, "target_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    assert session.query(WorkItemUpdate).count() == 0

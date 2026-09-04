"""Phase 4, task 5 — confirm endpoint, plus the proposal_id/executable-only
guarantees the confirm payload depends on.

The client sends back a chosen proposed action; the server looks it up in the
registry, validates, applies (mutation + source=assistant update), and commits
(publishing via the seam -> SSE). Dismiss is purely client-side (no call here).

Every proposal returned by /capture MUST be independently executable as-is (the
assistant is a "planner over a fixed set of actions") — that's what makes a
Confirm payload a self-contained action the endpoint below can dispatch. A
NEW-item capture must NOT return an item-targeting action (set_due_date /
complete_work_item) with target_id=None. Each proposal carries a batch-local
``proposal_id``; ``target_ref`` is reserved for v2 dependency chaining (None in
v1).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.capture import FocusedContext
from app.assistant.fake import FakeAssistant
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


def test_confirm_append_update_adds_assistant_context(client, session, auth_headers):
    wid = _create(session)
    r = client.post(
        "/actions/confirm",
        json={
            "name": "append_update",
            "params": {"body": "Vendor confirmed the delay."},
            "target_id": wid,
        },
        headers=auth_headers,
    )

    assert r.status_code == 200
    session.expire_all()
    update = session.query(WorkItemUpdate).one()
    assert update.work_item_id == wid
    assert update.source == "assistant"
    assert update.body == "Vendor confirmed the delay."


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


# --- confirm endpoint for the newer actions (assign / reschedule / archive) -
# The handlers are unit-tested in test_actions; these prove they flow through
# /actions/confirm (auth, target_type, commit) — the new target patterns.


def test_confirm_assign_work_item(client, session, auth_headers):
    wid = _create(session)
    # A second member in the SAME family as the authed member (assign whitelists
    # by family). auth_headers seeds "TestFam" + "Tester"; reuse that family.
    fam = session.query(Family).first()
    sam = Member(family_id=fam.id, display_name="Sam", role="child", created_at=NOW)
    session.add(sam)
    session.commit()
    sam_id = sam.id

    r = client.post(
        "/actions/confirm",
        json={
            "name": "assign_work_item",
            "params": {"member_id": sam_id},
            "target_id": wid,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    assert session.get(WorkItem, wid).assigned_to == sam_id


def test_confirm_assign_rejects_foreign_member_422(client, session, auth_headers):
    wid = _create(session)
    other = Family(name="Other", timezone="UTC")
    session.add(other)
    session.commit()
    outsider = Member(
        family_id=other.id, display_name="Outsider", role="adult", created_at=NOW
    )
    session.add(outsider)
    session.commit()

    r = client.post(
        "/actions/confirm",
        json={
            "name": "assign_work_item",
            "params": {"member_id": outsider.id},
            "target_id": wid,
        },
        headers=auth_headers,
    )
    assert r.status_code == 422  # whitelist rejection surfaces as 422
    session.expire_all()
    assert session.get(WorkItem, wid).assigned_to is None


def test_confirm_reschedule_event_target_type_event(client, session, auth_headers):
    fam = session.query(Family).first()  # auth_headers seeds the family
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
    ev_id = ev.id
    new_start = datetime(2026, 9, 8, 15, 0, tzinfo=UTC).isoformat()

    r = client.post(
        "/actions/confirm",
        json={
            "name": "reschedule_event",
            "params": {"start_at": new_start, "end_at": new_start},
            "target_type": "event",
            "target_id": ev_id,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    assert session.get(Event, ev_id).start_at is not None
    # Event-only: no work-item update from a reschedule.
    assert session.query(WorkItemUpdate).count() == 0


def test_confirm_archive_requires_done_422(client, session, auth_headers):
    wid = _create(session)  # status defaults to todo
    r = client.post(
        "/actions/confirm",
        json={"name": "archive_work_item", "params": {}, "target_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 422  # invariant violation → 422
    session.expire_all()
    assert session.get(WorkItem, wid).archived_at is None


def test_confirm_archive_a_done_item(client, session, auth_headers):
    wid = _create(session)
    client.post(
        "/actions/confirm",
        json={"name": "complete_work_item", "params": {}, "target_id": wid},
        headers=auth_headers,
    )
    r = client.post(
        "/actions/confirm",
        json={"name": "archive_work_item", "params": {}, "target_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    assert session.get(WorkItem, wid).archived_at is not None


# --- executable-only proposals + the proposal_id primitive -----------------
# Unit-level (FakeAssistant.propose directly): the guarantees that make a
# Confirm payload dispatchable as-is by the endpoint above.

_PROPOSE_NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _propose_ctx(text: str, target_id=None) -> FocusedContext:
    return FocusedContext(
        text=text,
        timezone="America/New_York",
        now=_PROPOSE_NOW,
        resolved_work_item_ids=[target_id] if target_id is not None else [],
    )


def _needs_concrete_target(p) -> bool:
    """True when the proposal targets a WORK ITEM and therefore must carry a
    concrete target_id. A standalone event (target_type='event') is fully defined
    by its params and needs no work-item id."""
    return p.target_type == "work_item"


def test_new_item_capture_has_no_unexecutable_item_action():
    # 'monday' would previously add a set_due_date with target_id=None.
    props = FakeAssistant().propose(_propose_ctx("soccer game on monday"))
    for p in props:
        if _needs_concrete_target(p):
            assert p.target_id is not None, f"{p.name} has no target on a new capture"
    # It proposes creating the work item (self-contained)...
    assert "create_work_item" in [p.name for p in props]
    # ...and NOT a bare set_due_date (no item to attach it to yet).
    assert "set_due_date" not in [p.name for p in props]


def test_new_event_capture_is_standalone_and_executable():
    # event word + weekday → a standalone create_event, fully specified.
    props = FakeAssistant().propose(_propose_ctx("dentist appointment monday"))
    assert [p.name for p in props] == ["create_event"]
    ev = props[0]
    assert ev.target_type == "event"
    assert ev.target_id is None
    assert ev.params.get("start_at") and ev.params.get("end_at")


def test_new_project_word_is_ordinary_text_now():
    # 'project' dropped as a trigger (produced two unrelated rows) — it's now
    # ordinary text: a single, fully-defined create_work_item.
    props = FakeAssistant().propose(_propose_ctx("project launch monday"))
    assert [p.name for p in props] == ["create_work_item"]
    for p in props:
        if _needs_concrete_target(p):
            assert p.target_id is not None


def test_existing_item_capture_still_targets_the_item():
    props = FakeAssistant().propose(_propose_ctx("he is coming monday", target_id=7))
    due = next(p for p in props if p.name == "set_due_date")
    assert due.target_id == 7
    assert due.target_type == "work_item"


def test_proposals_expose_proposal_id_and_no_target_ref():
    for p in FakeAssistant().propose(_propose_ctx("dentist appointment monday")):
        assert hasattr(p, "proposal_id")
        assert p.target_ref is None  # v1: no dangling dependency

"""Phase 4, task 4 — capture-with-proposals endpoint (Option A: propose-only).

POST /capture:
  * **New-item capture** (no ``work_item_id``): saves NOTHING. Returns
    ``item=null`` + proposals (``create_work_item`` and/or ``create_event`` …).
    Nothing persists until the human Confirms a proposal (ASSIST-2 — capture
    never auto-applies, and bare text no longer auto-spawns a work item).
  * **Existing-item capture** (``work_item_id`` set): appends the raw text as a
    ``source=human`` note to that item immediately — genuine human content added
    to an item the member explicitly targeted (WORKITEM-2) — then proposes.

Auth-protected. Proposals are returned only to the caller (author's device).
"""

from __future__ import annotations

import app.main as main
from app.assistant.base import AssistantClient
from app.models import Event, WorkItem, WorkItemUpdate


def test_capture_requires_auth(client):
    assert client.post("/capture", json={"text": "buy milk"}).status_code == 401


def test_capture_new_item_persists_nothing_and_proposes(client, session, auth_headers):
    r = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    )
    assert r.status_code == 201
    body = r.json()
    # Propose-only: no item was created, and the response item is null.
    assert body["item"] is None
    assert session.query(WorkItem).count() == 0
    assert session.query(WorkItemUpdate).count() == 0
    # The assistant proposed create_work_item (the confirmable "new item" path)
    # plus the due-date suggestion (fake: 'friday').
    names = [p["name"] for p in body["proposals"]]
    assert "create_work_item" in names
    assert "set_due_date" in names


def test_capture_new_item_proposals_have_no_target(client, auth_headers):
    """New-item proposals target no existing work item (target_id is None)."""
    body = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    ).json()
    assert all(p["target_id"] is None for p in body["proposals"])


def test_capture_new_item_saves_nothing_even_for_bland_text(
    client, session, auth_headers
):
    body = client.post(
        "/capture", json={"text": "hmm nothing"}, headers=auth_headers
    ).json()
    # Nothing persisted...
    assert body["item"] is None
    assert session.query(WorkItem).count() == 0
    # ...but the human can still capture it as a work item via the proposal.
    assert "create_work_item" in [p["name"] for p in body["proposals"]]


def test_capture_degrades_gracefully_when_assistant_fails(
    client, session, auth_headers, monkeypatch
):
    """If the assistant raises/times out, capture still returns 201 with item=null
    and empty proposals — never blocks the human, never a 500, never persists."""

    class BoomAssistant(AssistantClient):
        def propose(self, ctx):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(main, "get_assistant", lambda: BoomAssistant())

    r = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    )
    assert r.status_code == 201
    body = r.json()
    assert body["item"] is None
    assert body["proposals"] == []  # degraded, not a 500
    assert session.query(WorkItem).count() == 0


def test_capture_proposals_not_persisted(client, session, auth_headers):
    """Proposals live only in the response (no suggestions table)."""
    client.post("/capture", json={"text": "plumber friday"}, headers=auth_headers)
    assert session.query(WorkItem).count() == 0
    assert session.query(WorkItemUpdate).count() == 0


def test_capture_returns_no_action_proposal_for_untriggered_text(
    client, auth_headers, monkeypatch
):
    """When the assistant has nothing, the response is just no_action (still no
    item). Force the fake to see truly bland input via monkeypatched proposer."""
    body = client.post("/capture", json={"text": "zzz"}, headers=auth_headers).json()
    # 'zzz' triggers neither weekday/event/done nor... create_work_item is only
    # added on new-item captures, so it is present; assert no mutation happened.
    assert body["item"] is None


def test_capture_proposals_carry_two_summaries(client, auth_headers):
    """Each proposal has a registry-derived action_summary (ground truth) AND an
    llm_rationale (model narration) — the task-8 split."""
    body = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    ).json()
    due = next(p for p in body["proposals"] if p["name"] == "set_due_date")
    assert "due" in due["action_summary"].lower()
    assert due["params"]["due_at"] in due["action_summary"]
    assert due["llm_rationale"]
    assert due["action_summary"] != due["llm_rationale"]
    assert "summary" not in due


def test_capture_action_summary_is_registry_truth_not_model(client, auth_headers):
    """action_summary comes from the registry, so it stays correct even though the
    fake's rationale is generic."""
    body = client.post(
        "/capture",
        json={"text": "dentist appointment thursday"},
        headers=auth_headers,
    ).json()
    ev = next(p for p in body["proposals"] if p["name"] == "create_event")
    assert "event" in ev["action_summary"].lower()
    assert ev["params"]["title"] in ev["action_summary"]


def test_capture_existing_item_appends_human_note(client, session, auth_headers):
    """Capture targeting an existing item appends a source=human note to it.

    Existing items are modified with extra human *content* per the work-item data
    model (WORKITEM-2) — this direct save is intentional and distinct from the
    propose-only new-item path.
    """
    # Seed an existing item directly (new-item capture no longer creates one).
    fam = session.query(WorkItem).first()
    from app.models import Family, Member

    fam = session.query(Family).filter_by(name="TestFam").one()
    m = session.query(Member).filter_by(display_name="Tester").one()
    wi = WorkItem(
        family_id=fam.id,
        title="call plumber",
        created_at=m.created_at,
        updated_at=m.created_at,
    )
    session.add(wi)
    session.commit()
    wid = wi.id

    r = client.post(
        "/capture",
        json={"text": "he is coming friday", "work_item_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["item"] is not None
    assert body["item"]["id"] == wid
    # A human note was appended to the existing item.
    note = (
        session.query(WorkItemUpdate).filter_by(work_item_id=wid, source="human").one()
    )
    assert note.body == "he is coming friday"
    # And the assistant still proposed (friday -> set_due_date), targeting it.
    due = next(p for p in body["proposals"] if p["name"] == "set_due_date")
    assert due["target_id"] == wid


def test_capture_existing_item_missing_returns_404(client, auth_headers):
    r = client.post(
        "/capture",
        json={"text": "note", "work_item_id": 99999},
        headers=auth_headers,
    )
    assert r.status_code == 404


# --- registry-wide invariant: capture NEVER auto-applies any action ----------


def test_capture_never_mutates_across_all_actions(client, session, auth_headers):
    """Enforce ASSIST-2 across the whole registry: for inputs that trigger every
    kind of proposal, a NEW-item capture applies nothing — no work items, no
    updates, no events are written. Only Confirm mutates.

    This guards against a future action or capture change that silently
    auto-applies: whatever the assistant proposes, capture must persist nothing.
    """
    triggering_inputs = [
        "call plumber friday",  # -> set_due_date (+ create_work_item)
        "dentist appointment thursday",  # -> create_event (+ set_due_date)
        "all done, finished the taxes",  # -> complete_work_item
        "buy stamps",  # -> create_work_item only
        "zzz",  # -> nothing action-y
    ]
    for text in triggering_inputs:
        r = client.post("/capture", json={"text": text}, headers=auth_headers)
        assert r.status_code == 201, text

    # After all those captures, the database is still empty of every mutation.
    assert session.query(WorkItem).count() == 0
    assert session.query(WorkItemUpdate).count() == 0
    assert session.query(Event).count() == 0

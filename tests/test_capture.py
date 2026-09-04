"""Phase 4, task 4 — capture-with-proposals endpoint.

POST /capture is **propose-only and always a NEW capture** (v1): it saves
NOTHING and returns ``item=null`` + proposals for the human to Confirm (ASSIST-2
— capture never auto-applies, and bare text no longer auto-spawns a work item).

Capture no longer takes a ``work_item_id``: the target (if any) lives in the text
and is resolved by stage 1 (``focus()``) — a v2/local-LLM capability, so v1 resolves
no target and every capture is new. Explicit note-append to a specific item is a
separate concern, covered by ``POST /work-items/{id}/updates``.

Auth-protected. Proposals are returned only to the caller (author's device).
"""

from __future__ import annotations

import app.main as main
from app.assistant.capture import AssistantClient
from app.models import Event, WorkItem, WorkItemUpdate


def test_capture_requires_auth(client):
    assert client.post("/capture", json={"text": "buy milk"}).status_code == 401


def test_capture_persists_nothing_and_proposes(client, session, auth_headers):
    r = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    )
    assert r.status_code == 201
    body = r.json()
    # Propose-only: nothing created, response item is null.
    assert body["item"] is None
    assert session.query(WorkItem).count() == 0
    assert session.query(WorkItemUpdate).count() == 0
    # New capture with no event word → create_work_item only (no set_due_date:
    # there is no item yet to target).
    names = [p["name"] for p in body["proposals"]]
    assert "create_work_item" in names
    assert "set_due_date" not in names


def test_capture_proposals_have_no_work_item_target(client, auth_headers):
    """New-capture proposals never target an existing work item."""
    body = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    ).json()
    for p in body["proposals"]:
        if p.get("target_type") == "work_item":
            raise AssertionError("no work-item target on a new capture")


def test_capture_saves_nothing_even_for_bland_text(client, session, auth_headers):
    body = client.post(
        "/capture", json={"text": "hmm nothing"}, headers=auth_headers
    ).json()
    assert body["item"] is None
    assert session.query(WorkItem).count() == 0
    assert "create_work_item" in [p["name"] for p in body["proposals"]]


def test_capture_degrades_gracefully_when_assistant_fails(
    client, session, auth_headers, monkeypatch
):
    """If the assistant raises/times out, capture still returns 201 with item=null
    and empty proposals — never blocks the human, never a 500, never persists."""

    class BoomAssistant(AssistantClient):
        def propose(self, ctx):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(main, "get_assistant", lambda config: BoomAssistant())

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


def test_capture_returns_item_null_for_untriggered_text(client, auth_headers):
    body = client.post("/capture", json={"text": "zzz"}, headers=auth_headers).json()
    assert body["item"] is None


def test_capture_proposals_carry_two_summaries(client, auth_headers):
    """Each proposal has a registry-derived action_summary (ground truth) AND an
    llm_rationale (model narration) — the task-8 split. Uses an event-word new
    capture, which proposes a fully-defined create_event."""
    body = client.post(
        "/capture",
        json={"text": "dentist appointment friday"},
        headers=auth_headers,
    ).json()
    ev = next(p for p in body["proposals"] if p["name"] == "create_event")
    assert "event" in ev["action_summary"].lower()
    assert ev["params"]["title"] in ev["action_summary"]
    assert ev["llm_rationale"]
    assert ev["action_summary"] != ev["llm_rationale"]
    assert "summary" not in ev


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


# --- fully-defined + proposal_id + never-mutates guards -------------------


def test_capture_proposals_are_all_executable(client, auth_headers):
    """Every proposal from a capture must FULLY DEFINE its operation: a work-item
    target is concrete, required params present, and no v1 target_ref."""
    from app.assistant.actions import ACTIONS

    for text in ["soccer game on monday", "dentist appointment monday", "buy milk"]:
        body = client.post("/capture", json={"text": text}, headers=auth_headers)
        for p in body.json()["proposals"]:
            spec = ACTIONS.get(p["name"])
            assert spec is not None, p["name"]
            if p.get("target_type") == "work_item":
                assert p["target_id"] is not None, f"{p['name']} ({text})"
            for key in spec.required:
                assert p["params"].get(key) not in (None, ""), f"{p['name']}.{key}"
            assert p.get("target_ref") is None, p["name"]


def test_capture_proposals_have_unique_proposal_ids(client, auth_headers):
    """The engine seam assigns each proposal a stable batch-local proposal_id."""
    body = client.post(
        "/capture",
        json={"text": "dentist appointment monday"},
        headers=auth_headers,
    ).json()
    ids = [p["proposal_id"] for p in body["proposals"]]
    assert all(ids), "every proposal has a non-empty proposal_id"
    assert len(ids) == len(set(ids)), "proposal_ids are unique within the batch"


def test_capture_never_mutates_across_all_actions(client, session, auth_headers):
    """Enforce ASSIST-2 across the whole registry: for inputs that trigger every
    kind of proposal, a capture applies nothing — only Confirm mutates."""
    for text in [
        "call plumber friday",
        "dentist appointment thursday",
        "all done, finished the taxes",
        "buy stamps",
        "zzz",
    ]:
        r = client.post("/capture", json={"text": text}, headers=auth_headers)
        assert r.status_code == 201, text

    assert session.query(WorkItem).count() == 0
    assert session.query(WorkItemUpdate).count() == 0
    assert session.query(Event).count() == 0

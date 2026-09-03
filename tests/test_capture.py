"""Phase 4, task 4 — capture-with-proposals endpoint.

POST /capture: save the raw human input FIRST (source=human), then call the
assistant for proposals (bounded, graceful-degrade to [] on failure), and return
{item, proposals}. Auth-protected. The raw save publishes via the seam (SSE);
proposals are returned only to the caller (author's device).
"""

from __future__ import annotations

import app.main as main
from app.assistant.base import AssistantClient
from app.models import WorkItem, WorkItemUpdate


def test_capture_requires_auth(client):
    assert client.post("/capture", json={"text": "buy milk"}).status_code == 401


def test_capture_new_item_saves_human_and_returns_proposals(client, auth_headers):
    r = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    )
    assert r.status_code == 201
    body = r.json()
    # The raw item was created...
    assert body["item"]["title"] == "call plumber friday"
    # ...and the assistant proposed something (fake: friday -> set_due_date).
    names = [p["name"] for p in body["proposals"]]
    assert "set_due_date" in names
    # Each proposal carries the target work item id.
    assert all(p["target_id"] == body["item"]["id"] for p in body["proposals"])


def test_capture_saves_raw_before_proposing(client, session, auth_headers):
    client.post("/capture", json={"text": "hmm nothing"}, headers=auth_headers)
    # Raw item persisted regardless of proposals (source=human).
    item = session.query(WorkItem).filter_by(title="hmm nothing").one()
    assert item is not None
    # No assistant update yet — proposals are unconfirmed, nothing applied.
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 0


def test_capture_degrades_gracefully_when_assistant_fails(
    client, auth_headers, monkeypatch
):
    """If the assistant raises/times out, capture still returns the saved item
    with empty proposals — never blocks the human."""

    class BoomAssistant(AssistantClient):
        def propose(self, ctx):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(main, "get_assistant", lambda: BoomAssistant())

    r = client.post(
        "/capture", json={"text": "call plumber friday"}, headers=auth_headers
    )
    assert r.status_code == 201
    body = r.json()
    assert body["item"]["title"] == "call plumber friday"
    assert body["proposals"] == []  # degraded, not a 500


def test_capture_proposals_not_persisted(client, session, auth_headers):
    """Proposals live only in the response (no suggestions table)."""
    client.post("/capture", json={"text": "plumber friday"}, headers=auth_headers)
    # Nothing assistant-sourced was written (only the human raw item).
    assert session.query(WorkItemUpdate).filter_by(source="assistant").count() == 0


def test_capture_returns_no_action_proposal_for_bland_text(client, auth_headers):
    body = client.post("/capture", json={"text": "hmm"}, headers=auth_headers).json()
    assert [p["name"] for p in body["proposals"]] == ["no_action"]


def test_capture_existing_item_appends_human_note(client, session, auth_headers):
    """Capture targeting an existing item appends a source=human note to it."""
    from app.models import WorkItemUpdate

    wid = client.post(
        "/capture", json={"text": "call plumber"}, headers=auth_headers
    ).json()["item"]["id"]

    r = client.post(
        "/capture",
        json={"text": "he is coming friday", "work_item_id": wid},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["item"]["id"] == wid
    # A human note was appended to the existing item (not a new item).
    note = (
        session.query(WorkItemUpdate).filter_by(work_item_id=wid, source="human").one()
    )
    assert note.body == "he is coming friday"
    # And the assistant still proposed (friday -> set_due_date).
    assert "set_due_date" in [p["name"] for p in body["proposals"]]

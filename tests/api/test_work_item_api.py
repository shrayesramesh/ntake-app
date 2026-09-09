"""Phase 3, checkpoint 2 — work-item CRUD + append-update flow (WORKITEM, §4.1).

Create an item, append updates (the primary daily interaction), read the item
with its log, list items. Auth-protected; the author is the authenticated member.
Every write commits through the 1d seam, so it publishes a change event for SSE.
"""

from __future__ import annotations

from app.main import app_emitter


def test_create_work_item_requires_auth(client):
    r = client.post("/work-items", json={"title": "Fix sink"})
    assert r.status_code == 401


def test_create_and_read_work_item(client, auth_headers):
    r = client.post(
        "/work-items",
        json={"title": "Fix sink", "description": "downstairs", "tags": ["household"]},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Fix sink"
    assert body["status"] == "todo"
    assert body["tags"] == ["household"]
    wid = body["id"]

    got = client.get(f"/work-items/{wid}", headers=auth_headers)
    assert got.status_code == 200
    data = got.json()
    assert data["id"] == wid
    assert data["description"] == "downstairs"
    assert data["updates"] == []  # no updates yet
    assert data["checklist"] == []


def test_read_missing_work_item_404(client, auth_headers):
    assert client.get("/work-items/999", headers=auth_headers).status_code == 404


def test_append_update_sets_author_and_source_human(client, session, auth_headers):
    from app.persistence.models import Member

    wid = client.post(
        "/work-items", json={"title": "Task"}, headers=auth_headers
    ).json()["id"]

    r = client.post(
        f"/work-items/{wid}/updates",
        json={"body": "called the plumber"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    upd = r.json()
    assert upd["body"] == "called the plumber"
    assert upd["source"] == "human"
    # author is the authenticated member (the one auth_headers enrolled)
    member = session.query(Member).one()
    assert upd["author_id"] == member.id

    # The update shows up in the item's log.
    got = client.get(f"/work-items/{wid}", headers=auth_headers).json()
    assert [u["body"] for u in got["updates"]] == ["called the plumber"]


def test_append_update_to_missing_item_404(client, auth_headers):
    r = client.post("/work-items/999/updates", json={"body": "x"}, headers=auth_headers)
    assert r.status_code == 404


def test_list_work_items(client, auth_headers):
    client.post("/work-items", json={"title": "A"}, headers=auth_headers)
    client.post("/work-items", json={"title": "B"}, headers=auth_headers)
    r = client.get("/work-items", headers=auth_headers)
    assert r.status_code == 200
    titles = {wi["title"] for wi in r.json()}
    assert titles == {"A", "B"}


def test_writes_emit_change_events(client, auth_headers):
    """Creating an item and appending an update each publish via the 1d seam."""
    events: list[tuple[str, int, str]] = []

    async def listener(entity, id, op):
        events.append((entity, id, op))

    app_emitter.add_listener(listener)
    try:
        wid = client.post(
            "/work-items", json={"title": "T"}, headers=auth_headers
        ).json()["id"]
        client.post(
            f"/work-items/{wid}/updates", json={"body": "note"}, headers=auth_headers
        )
    finally:
        if listener in app_emitter.listeners:
            app_emitter.listeners.remove(listener)

    entities = {(e, o) for e, _id, o in events}
    assert ("work_items", "create") in entities
    assert ("work_item_updates", "create") in entities


def test_work_item_read_exposes_due_time_in_the_family_timezone(
    client, session, auth_headers
):
    from datetime import UTC, datetime

    from app.persistence.models import Family, Member, WorkItem

    member = session.query(Member).filter_by(display_name="Tester").one()
    family = session.get(Family, member.family_id)
    assert family is not None
    family.timezone = "America/Chicago"
    item = WorkItem(
        family_id=family.id,
        title="Schedule repair",
        due_at=datetime(2026, 9, 11, 1, 0, tzinfo=UTC),
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    session.add(item)
    session.commit()

    payload = client.get(f"/work-items/{item.id}", headers=auth_headers).json()
    assert payload["local_due_at"] == "2026-09-10T20:00:00"
    assert "due_at" not in payload

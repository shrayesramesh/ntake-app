"""Phase 3, task 6 — thin HTMX front end routes.

The shell page (/) is served without auth (it's the surface that then collects
the device token). The board fragment (/board/view) is auth-protected and renders
the read-only 4 columns as HTML. The capture form (client-side) is the only write
control; updates flow via the Phase 4 LLM loop, so there's no update UI here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Family, WorkItem

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_index_serves_shell_without_auth(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Shell has the capture control, proposals surface, board container + token JS.
    assert "Capture a note" in body
    assert "board-container" in body
    assert "calendar-container" in body  # skinny calendar list (task 11)
    assert "/calendar/view" in body
    assert "proposals" in body  # inline proposal cards render here
    assert "/capture" in body  # capture posts to the JSON capture endpoint
    assert "/actions/confirm" in body  # Confirm posts the action
    assert "action_summary" in body  # card shows the registry-derived truth
    assert "llm_rationale" in body  # ...and the model's narration as secondary
    assert "localStorage" in body


def test_board_view_requires_auth(client):
    assert client.get("/board/view").status_code == 401


def test_board_view_renders_columns_and_items(client, session, auth_headers):
    fam = session.query(Family).first()
    if fam is None:
        fam = Family(name="F", timezone="UTC")
        session.add(fam)
        session.commit()
    session.add(
        WorkItem(
            family_id=fam.id,
            title="Fix the sink",
            status="doing",
            tags=["household"],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()

    r = client.get("/board/view", headers=auth_headers)
    assert r.status_code == 200
    html = r.text
    assert "Todo" in html and "On deck" in html and "Doing" in html and "Done" in html
    assert "Fix the sink" in html
    assert "household" in html  # tag rendered


def test_board_view_escapes_html_in_titles(client, session, auth_headers):
    fam = Family(name="F", timezone="UTC")
    session.add(fam)
    session.commit()
    session.add(
        WorkItem(
            family_id=fam.id,
            title="<script>alert(1)</script>",
            status="todo",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()

    html = client.get("/board/view", headers=auth_headers).text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html  # escaped

"""PWA shell and board-fragment route contracts.

The unauthenticated shell handles one-time device onboarding, then exposes the
paired-device Board/Calendar selector and focused capture dialog. The board
fragment stays auth-protected and read-only; mutations remain propose-confirm.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.persistence.models import ChecklistItem, Family, Member, WorkItem

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_index_serves_shell_without_auth(client):
    # Minimal wiring tripwire: the shell renders unauthenticated and still wires
    # the core surfaces (capture, board, calendar, SSE). The BEHAVIOR of those
    # (capture->propose->confirm, calendar refresh, SSE reconnect re-sync) is
    # exercised over real HTTP by the host smoke, not asserted as strings here.
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "board-container" in body  # the shell (not some other page)
    assert "/capture" in body  # capture is wired
    assert "EventCalendar.create" in body  # calendar grid is wired
    assert "/static/event-calendar/event-calendar.min.js" in body
    assert "es.addEventListener('open'" in body  # SSE reconnect re-sync is wired


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


def test_board_view_loads_full_checklist_for_open_cards(client, session, auth_headers):
    family = session.query(Family).first()
    assert family is not None
    item = WorkItem(
        family_id=family.id,
        title="Groceries",
        status="todo",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(item)
    session.flush()
    session.add_all(
        [
            ChecklistItem(work_item_id=item.id, text="bread", checked=True, position=2),
            ChecklistItem(work_item_id=item.id, text="milk", position=1),
        ]
    )
    session.commit()

    html = client.get("/board/view", headers=auth_headers).text

    assert "☐ milk" in html
    assert "☑ bread" in html
    assert html.index("milk") < html.index("bread")


def test_shell_has_primary_view_navigation_and_focused_capture(client):
    html = client.get("/").text

    assert 'id="view-board"' in html
    assert 'id="view-calendar"' in html
    assert 'aria-pressed="true"' in html
    assert 'id="board-view"' in html
    assert 'id="calendar-view"' in html
    assert 'id="open-capture"' in html
    assert '<dialog id="capture-dialog">' in html
    assert '<form id="capture-form" onsubmit="return onCapture(event)">' in html
    assert 'id="capture-text"' in html
    assert 'enterkeyhint="done"' in html
    assert "Use your keyboard microphone to dictate" in html
    assert "function captureOnKeydown(event)" in html
    assert "requestSubmit()" in html
    assert "function setActiveView(view)" in html
    assert "ntake_active_view" in html


def test_board_view_resolves_assignee_name(client, session, auth_headers):
    family = session.query(Family).first()
    member = session.query(Member).filter_by(display_name="Tester").one()
    assert family is not None
    session.add(
        WorkItem(
            family_id=family.id,
            assigned_to=member.id,
            title="Assigned task",
            status="todo",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()

    html = client.get("/board/view", headers=auth_headers).text

    assert "assignee Tester" in html
    assert f"assignee m{member.id}" not in html

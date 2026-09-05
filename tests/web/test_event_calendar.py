"""EventCalendar first-slice integration contract.

The calendar remains read-only/propose-confirm, but the shell mounts locally
served EventCalendar assets with a month-default grid, week/day controls, an
authenticated custom /events source, correct all-day end conversion, and SSE
refetches. These tests intentionally inspect the emitted shell/static surface;
there is no JavaScript test runner in this Python project.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.persistence.models import Event, Member


def test_event_calendar_assets_are_served(client):
    css = client.get("/static/event-calendar/event-calendar.min.css")
    js = client.get("/static/event-calendar/event-calendar.min.js")

    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert "EventCalendar" in js.text


def test_static_tree_excludes_third_party_notices(client):
    """Attribution belongs in repository documentation, not a public asset URL."""
    response = client.get("/static/event-calendar/THIRD_PARTY_NOTICES.md")
    assert response.status_code == 404


def test_shell_mounts_read_only_event_calendar(client):
    html = client.get("/").text

    # Locally served, pinned third-party assets — never a public CDN.
    assert "/static/event-calendar/event-calendar.min.css" in html
    assert "/static/event-calendar/event-calendar.min.js" in html
    # Standard default + optional views.
    assert "view: 'dayGridMonth'" in html
    assert "timeGridWeek" in html
    assert "timeGridDay" in html
    assert "EventCalendar.create" in html
    # Existing auth transport and event API remain the source of truth.
    assert "fetch('/events'" in html
    assert "authHeaders(false)" in html
    # Title-first custom content restores useful context over the library default.
    assert "eventContent: calendarEventContent" in html
    assert "participants" in html
    assert "calendar-event-title" in html
    # Inclusive app all-day end -> exclusive calendar end adapter.
    assert "addOneDay" in html
    assert "allDay: true" in html
    # SSE refreshes the current grid instead of swapping an agenda fragment.
    assert "calendar.refetchEvents()" in html
    # Kiosk layout stays stable across month/week/day; the grid scrolls internally.
    assert "#calendar-container { height:" in html
    assert "height: '100%'" in html
    # First slice never offers direct mutation.
    assert "editable: false" in html
    assert "eventStartEditable: false" in html
    assert "eventDurationEditable: false" in html


def test_events_include_name_only_participants(client, session, auth_headers):
    """The browser calendar receives participant names directly from /events."""
    member = session.query(Member).filter_by(display_name="Tester").one()
    now = datetime(2026, 9, 4, 17, 0, tzinfo=UTC)
    event = Event(
        family_id=member.family_id,
        title="Soccer",
        start_at=now,
        end_at=now,
        participants=[member.display_name, "Coach Lee"],
        tags=["sports"],
        created_at=now,
        updated_at=now,
    )
    session.add(event)
    session.commit()

    payload = client.get("/events", headers=auth_headers).json()
    soccer = next(e for e in payload if e["title"] == "Soccer")
    assert soccer["participants"] == ["Tester", "Coach Lee"]
    assert soccer["tags"] == ["sports"]

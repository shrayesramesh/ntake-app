"""Task 11 — skinny calendar render.

A ``render_calendar(events)`` fragment + a ``GET /calendar/view`` HTML fragment
(auth-protected), wired into the shell + SSE reload like the board. For now this
is a simple long list of event cards for testing — the UI is improved later.

TDD: the fragment renders event titles + a time/date line, escapes HTML, and the
route requires auth. Uses the task-9 ``event_factory`` fixture to seed events.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.persistence.models import Family
from app.web import render_calendar

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


# --- render_calendar fragment (pure) --------------------------------------


def test_render_calendar_empty_shows_placeholder():
    html = render_calendar([])
    assert 'id="calendar"' in html
    # An empty calendar renders a visible empty-state, not a blank string.
    assert "empty" in html


def test_render_calendar_lists_timed_event(session):
    fam = Family(name="F", timezone="UTC")
    session.add(fam)
    session.commit()
    from app.manage import seed_event

    ev = seed_event(
        session,
        fam.id,
        title="Dentist",
        start_at=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
    )
    html = render_calendar([ev])
    assert "Dentist" in html
    # Timed events show the start datetime (skinny: ISO/readable UTC is fine).
    assert "2026-09-04" in html


def test_render_calendar_lists_all_day_event(session):
    fam = Family(name="F", timezone="UTC")
    session.add(fam)
    session.commit()
    from app.manage import seed_event

    ev = seed_event(
        session, fam.id, title="Holiday", all_day=True, start_date=date(2026, 12, 25)
    )
    html = render_calendar([ev])
    assert "Holiday" in html
    assert "2026-12-25" in html
    assert "all-day" in html.lower()


def test_render_calendar_escapes_html(session):
    fam = Family(name="F", timezone="UTC")
    session.add(fam)
    session.commit()
    from app.manage import seed_event

    ev = seed_event(
        session,
        fam.id,
        title="<script>alert(1)</script>",
        start_at=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
    )
    html = render_calendar([ev])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_calendar_shows_and_escapes_location(session):
    fam = Family(name="F", timezone="UTC")
    session.add(fam)
    session.commit()
    from app.manage import seed_event

    ev = seed_event(
        session,
        fam.id,
        title="Recital",
        start_at=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
        location="<b>Hall</b>",
    )
    html = render_calendar([ev])
    assert "Hall" in html
    assert "<b>Hall</b>" not in html  # escaped


def test_calendar_view_requires_auth(client):
    assert client.get("/calendar/view").status_code == 401


def test_calendar_view_renders_events(client, session, auth_headers, event_factory):
    fam = session.query(Family).filter_by(name="TestFam").one()
    event_factory(
        fam.id, title="soccer", start_at=datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
    )
    event_factory(fam.id, title="xmas", all_day=True, start_date=date(2026, 12, 25))

    r = client.get("/calendar/view", headers=auth_headers)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert "soccer" in html and "xmas" in html


def test_calendar_view_escapes_html(client, session, auth_headers, event_factory):
    fam = session.query(Family).filter_by(name="TestFam").one()
    event_factory(
        fam.id,
        title="<b>xss</b>",
        start_at=datetime(2026, 9, 5, 14, 0, tzinfo=UTC),
    )
    html = client.get("/calendar/view", headers=auth_headers).text
    assert "<b>xss</b>" not in html
    assert "&lt;b&gt;" in html


# --- shell wiring (minimal tripwire) --------------------------------------
# One assertion that the calendar surface is wired into the shell. The BEHAVIOR
# — capture/confirm refreshing the calendar, an event landing in /calendar/view —
# is exercised over real HTTP by the host smoke (assistant capture->confirm +
# standalone create_event checks), not asserted as JS strings here.


def test_shell_wires_calendar(client):
    body = client.get("/").text
    assert "calendar-container" in body
    assert "calendar-grid" in body
    assert "EventCalendar.create" in body
    assert "fetch('/events'" in body
    assert "calendar.refetchEvents()" in body

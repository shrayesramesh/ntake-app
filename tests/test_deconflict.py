"""Task 10 — MVP context-aware event action (deconflict).

Proves calendar context flows end-to-end: focus() populates the id-bearing
``calendar_window``; the FakeAssistant sees two events at the same start and
proposes ``deconflict_events`` targeting the later-created one; confirming moves
that event to the next day. A deliberate placeholder (context-in → action-out →
apply), NOT smart scheduling.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.assistant.actions import ACTIONS, ActionError, apply_action
from app.assistant.context import EventSummary, FocusedContext
from app.assistant.fake import FakeAssistant
from app.manage import seed_event
from app.models import Event, Family, WorkItemUpdate

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


# --- the deconflict_events action -----------------------------------------


def test_deconflict_registered_with_describe():
    spec = ACTIONS["deconflict_events"]
    assert callable(spec.apply) and callable(spec.describe)
    assert isinstance(spec.describe({}), str) and spec.describe({})


def test_deconflict_moves_timed_event_to_next_day(session, fam_member):
    fam, m = fam_member
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC)
    ev = seed_event(session, fam.id, title="Later", start_at=start, end_at=end)

    apply_action(
        session,
        m,
        "deconflict_events",
        target_id=ev.id,
        params={},
        target_type="event",
    )

    session.expire_all()
    moved = session.get(Event, ev.id)
    assert moved.start_at == (start + timedelta(days=1)).replace(tzinfo=None)
    assert moved.end_at == (end + timedelta(days=1)).replace(tzinfo=None)
    # Event-only action: NO work-item update (WORKITEM-3 / task 12 conditional).
    assert session.query(WorkItemUpdate).count() == 0


def test_deconflict_moves_all_day_event_to_next_day(session, fam_member):
    fam, m = fam_member
    day = date(2026, 12, 25)
    ev = seed_event(session, fam.id, title="Holiday", all_day=True, start_date=day)

    apply_action(
        session,
        m,
        "deconflict_events",
        target_id=ev.id,
        params={},
        target_type="event",
    )

    session.expire_all()
    moved = session.get(Event, ev.id)
    assert moved.start_date == day + timedelta(days=1)
    assert moved.end_date == day + timedelta(days=1)


def test_deconflict_missing_event_raises(session, fam_member):
    fam, m = fam_member
    with pytest.raises(ActionError):
        apply_action(
            session,
            m,
            "deconflict_events",
            target_id=9999,
            params={},
            target_type="event",
        )


# --- FakeAssistant proposes deconflict on an overlapping window -----------


def _ctx_with_window(window: list[EventSummary]) -> FocusedContext:
    return FocusedContext(
        text="what's on the calendar",
        work_item_id=None,
        timezone="America/New_York",
        now=NOW,
        calendar_window=window,
    )


def test_fake_proposes_deconflict_when_two_events_overlap():
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    window = [
        EventSummary(id=5, title="Soccer", start=start),
        EventSummary(id=8, title="Dentist", start=start),
    ]
    props = FakeAssistant().propose(_ctx_with_window(window))
    dc = next(p for p in props if p.name == "deconflict_events")
    assert dc.target_type == "event"
    assert dc.target_id == 8  # the later-created (higher id) of the overlap


def test_fake_no_deconflict_when_no_overlap():
    window = [
        EventSummary(id=5, title="Soccer", start=datetime(2026, 9, 5, 19, tzinfo=UTC)),
        EventSummary(id=8, title="Dentist", start=datetime(2026, 9, 6, 19, tzinfo=UTC)),
    ]
    props = FakeAssistant().propose(_ctx_with_window(window))
    assert "deconflict_events" not in [p.name for p in props]


def test_fake_deconflict_on_all_day_overlap():
    day = date(2026, 12, 25)
    window = [
        EventSummary(id=3, title="A", start_date=day, all_day=True),
        EventSummary(id=9, title="B", start_date=day, all_day=True),
    ]
    props = FakeAssistant().propose(_ctx_with_window(window))
    dc = next(p for p in props if p.name == "deconflict_events")
    assert dc.target_id == 9


# --- end-to-end: seed two conflicts -> capture -> confirm -> one moves -----


def test_end_to_end_deconflict(client, session, auth_headers):
    fam = session.query(Family).filter_by(name="TestFam").one()
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC)
    e1 = seed_event(session, fam.id, title="Soccer", start_at=start, end_at=end)
    e2 = seed_event(session, fam.id, title="Dentist", start_at=start, end_at=end)
    assert e2.id > e1.id  # e2 is later-created

    # Capture -> focus() puts both events in calendar_window -> fake proposes it.
    body = client.post(
        "/capture", json={"text": "check calendar"}, headers=auth_headers
    ).json()
    dc = next(p for p in body["proposals"] if p["name"] == "deconflict_events")
    assert dc["target_id"] == e2.id and dc["target_type"] == "event"

    # Confirm -> the later event moves to the next day.
    r = client.post(
        "/actions/confirm",
        json={
            "name": "deconflict_events",
            "params": dc["params"],
            "target_id": dc["target_id"],
            "target_type": "event",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    session.expire_all()
    assert session.get(Event, e2.id).start_at == (start + timedelta(days=1)).replace(
        tzinfo=None
    )
    # The other event is untouched.
    assert session.get(Event, e1.id).start_at == start.replace(tzinfo=None)

"""Task 10 — the deconflict_events action (apply path).

The ``deconflict_events`` action itself (move an overlapping event to the next
day) is unaffected by the WORKPLAN-A2 reshape and is still fully tested here.

The FakeAssistant no longer *proposes* deconflict from a ``calendar_window`` (that
context field was retired in the reshape). Whether the fake should re-derive and
propose deconflict at all is the open Step-4 decision (see
``spec/WORKPLAN-A2-focus-reshape.md``); the fake-proposal + end-to-end tests are
skipped until that decision lands.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.assistant.actions import ACTIONS, ActionError, apply_action
from app.manage import seed_event
from app.models import Event, WorkItemUpdate

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


# --- FakeAssistant proposes deconflict: PENDING Step-4 decision ------------

pytestmark_note = (
    "FakeAssistant deconflict-proposal behavior is the open Step-4 decision "
    "(WORKPLAN-A2); calendar_window was retired in the reshape."
)


@pytest.mark.skip(reason=pytestmark_note)
def test_fake_proposes_deconflict_when_two_events_overlap():  # pragma: no cover
    raise NotImplementedError


@pytest.mark.skip(reason=pytestmark_note)
def test_end_to_end_deconflict():  # pragma: no cover
    raise NotImplementedError

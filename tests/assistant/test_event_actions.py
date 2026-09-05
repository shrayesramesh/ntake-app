"""Calendar-event assistant action handlers, variants, and card behavior."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.assistant.actions.registry import ACTIONS, apply_action
from app.manage import seed_event
from app.persistence.models import Event, WorkItemUpdate
from app.routing.engine import ActionError

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _card(name: str, params: dict, resolved: dict | None = None) -> list[str]:
    spec = ACTIONS[name]
    assert spec.render_card is not None, f"{name} has no render_card"
    return spec.render_card(params, resolved or {})


def test_create_timed_event_inserts_and_links_source_update(session, fam_member_item):
    fam, m, wi = fam_member_item
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC)
    end = datetime(2026, 9, 5, 20, 0, tzinfo=UTC)

    apply_action(
        session,
        m,
        "create_timed_event",
        wi.id,
        {
            "title": "Plumber visit",
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )

    session.expire_all()
    ev = session.query(Event).one()
    assert ev.title == "Plumber visit"
    assert ev.family_id == fam.id
    # The event links back to the assistant update that drove it (EVENT-7).
    upd = session.query(WorkItemUpdate).filter_by(source="assistant").one()
    assert ev.source_update_id == upd.id


def test_reschedule_timed_event_updates_timing_only(session, fam_member_item):
    fam, m, wi = fam_member_item
    ev = Event(
        family_id=fam.id,
        title="Dentist",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(ev)
    session.commit()

    new_start = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)
    apply_action(
        session,
        m,
        "reschedule_timed_event",
        ev.id,
        {"start_at": new_start.isoformat(), "end_at": new_start.isoformat()},
        target_type="event",
    )

    session.expire_all()
    got = session.get(Event, ev.id)
    assert got.start_at.replace(tzinfo=UTC) == new_start
    assert got.title == "Dentist"  # only timing changed
    # Event-only: no work-item update appended.
    assert session.query(WorkItemUpdate).count() == 0


def test_create_timed_event_writes_participants(session, fam_member):
    fam, m = fam_member
    start = datetime(2026, 9, 5, 19, 0, tzinfo=UTC).isoformat()
    apply_action(
        session,
        m,
        "create_timed_event",
        None,
        {
            "title": "Soccer",
            "start_at": start,
            "end_at": start,
            "participants": [m.display_name, "Coach Lee"],
        },
        target_type="event",
    )
    session.expire_all()
    ev = session.query(Event).filter_by(title="Soccer").one()
    assert ev.participants == [m.display_name, "Coach Lee"]


def test_create_timed_event_requires_a_timing(session, fam_member):
    """create_timed_event with neither a timed (start_at) nor all-day (start_date)
    timing is rejected — the confirm path can't persist a timing-less junk row
    (mirrors the propose-side accepts() contract)."""
    _fam, m = fam_member
    with pytest.raises(ActionError):
        apply_action(
            session,
            m,
            "create_timed_event",
            None,
            {"title": "No when"},
            target_type="event",
        )


def test_delete_event_removes_the_event(session, fam_member):
    """delete_event removes the target event; event-only (no work-item update)."""
    fam, m = fam_member
    ev = Event(
        family_id=fam.id,
        title="Cancelled thing",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(ev)
    session.commit()
    ev_id = ev.id

    summary = apply_action(session, m, "delete_event", ev_id, {}, target_type="event")

    session.expire_all()
    assert session.get(Event, ev_id) is None
    assert "Deleted event" in summary
    assert session.query(WorkItemUpdate).count() == 0


def test_delete_event_missing_target_raises(session, fam_member):
    """A delete with no/absent target is an invalid action (ActionError -> 422)."""
    fam, m = fam_member
    with pytest.raises(ActionError):
        apply_action(session, m, "delete_event", 999999, {}, target_type="event")


def test_render_card_reschedule_shows_new_timing_and_target():
    lines = _card(
        "reschedule_timed_event",
        {"start_at": "2026-09-10T14:00:00Z"},
        {"target_label": "Dentist"},
    )
    text = " ".join(lines)
    assert "2026-09-10" in text
    assert "Dentist" in text


def test_render_card_create_timed_event_shows_title_and_when():
    lines = _card(
        "create_timed_event",
        {"title": "Soccer", "start_at": "2026-09-10T14:00:00Z"},
    )
    text = " ".join(lines)
    assert "Soccer" in text and "2026-09-10" in text


def test_registry_uses_explicit_event_timing_variants():
    assert {"create_event", "reschedule_event"}.isdisjoint(ACTIONS)
    assert {
        "create_timed_event",
        "create_all_day_event",
        "reschedule_timed_event",
        "reschedule_all_day_event",
    }.issubset(ACTIONS)
    assert all(not spec.exclusive_params for spec in ACTIONS.values())


def test_create_timed_event_requires_complete_timed_pair(session, fam_member):
    _fam, member = fam_member

    with pytest.raises(ActionError):
        apply_action(
            session,
            member,
            "create_timed_event",
            None,
            {"title": "Dentist", "start_at": "2026-09-05T19:00:00Z"},
            target_type="event",
        )


def test_create_all_day_event_defaults_end_date(session, fam_member):
    family, member = fam_member
    apply_action(
        session,
        member,
        "create_all_day_event",
        None,
        {"title": "School holiday", "start_date": "2026-09-12"},
        target_type="event",
    )

    session.expire_all()
    event = session.query(Event).one()
    assert event.family_id == family.id
    assert event.all_day is True
    assert event.start_date == event.end_date == date(2026, 9, 12)
    assert event.start_at is None and event.end_at is None


def test_reschedule_timed_event_requires_complete_timed_pair(session, fam_member):
    family, member = fam_member
    event = Event(
        family_id=family.id,
        title="Dentist",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    session.add(event)
    session.commit()

    with pytest.raises(ActionError):
        apply_action(
            session,
            member,
            "reschedule_timed_event",
            event.id,
            {"start_at": "2026-09-08T19:00:00Z"},
            target_type="event",
        )


def test_reschedule_all_day_event_defaults_end_date(session, fam_member):
    family, member = fam_member
    event = Event(
        family_id=family.id,
        title="School holiday",
        all_day=True,
        start_date=date(2026, 9, 5),
        end_date=date(2026, 9, 5),
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )
    session.add(event)
    session.commit()

    apply_action(
        session,
        member,
        "reschedule_all_day_event",
        event.id,
        {"start_date": "2026-09-10"},
        target_type="event",
    )

    session.expire_all()
    updated = session.get(Event, event.id)
    assert updated.all_day is True
    assert updated.start_date == updated.end_date == date(2026, 9, 10)


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


def test_set_event_location_updates_existing_event(session, fam_member):
    fam, member = fam_member
    event = seed_event(
        session,
        fam.id,
        title="Dentist",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        location="Old office",
    )

    apply_action(
        session,
        member,
        "set_event_location",
        event.id,
        {"location": " Downtown clinic "},
        target_type="event",
    )

    session.expire_all()
    assert session.get(Event, event.id).location == "Downtown clinic"
    assert session.query(WorkItemUpdate).count() == 0


def test_add_event_participants_merges_normalized_names(session, fam_member):
    fam, member = fam_member
    event = seed_event(
        session,
        fam.id,
        title="Soccer",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        participants=["Sam", "Coach Lee"],
    )

    apply_action(
        session,
        member,
        "add_event_participants",
        event.id,
        {"participants": [" Alex ", "sam", "Grandma"]},
        target_type="event",
    )

    session.expire_all()
    assert session.get(Event, event.id).participants == [
        "Sam",
        "Coach Lee",
        "Alex",
        "Grandma",
    ]
    assert session.query(WorkItemUpdate).count() == 0


@pytest.mark.parametrize("participants", [[], [""], ["  "], [42], [{"name": "Sam"}]])
def test_add_event_participants_rejects_non_name_values(
    session, fam_member, participants
):
    fam, member = fam_member
    event = seed_event(
        session,
        fam.id,
        title="Soccer",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
    )

    with pytest.raises(ActionError):
        apply_action(
            session,
            member,
            "add_event_participants",
            event.id,
            {"participants": participants},
            target_type="event",
        )


def test_render_card_event_metadata_actions_show_names_and_location():
    location = _card("set_event_location", {"location": "Downtown clinic"})
    participants = _card(
        "add_event_participants", {"participants": ["Alex", "Grandma"]}
    )

    assert location == ["Location: Downtown clinic"]
    assert participants == ["Participants: Alex, Grandma"]

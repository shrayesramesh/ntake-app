"""build_world_view — deterministic (no LLM) plain-text "state of the world".

The world view is the ambient family state the assistant reasons over: family
members, non-archived work items (done INCLUDED, archived EXCLUDED), and events
in a past window (default 7 days back, forward open-ended). It is rendered to a
compact text block with **ids inline** (ids matter for later whitelisted
targeting) and times in the **family timezone**, start + end.

Everything here is deterministic DB work — no model. These tests seed rows and
assert (a) scoping/filtering and (b) the rendered text, with zero stubbing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.assistant.world import build_world_view
from app.manage import seed_event
from app.models import Family, Member, WorkItem

# A fixed "now": Thu 2026-09-03 12:00 UTC = 08:00 America/New_York.
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _family(session, name="Fam", tz=TZ) -> Family:
    fam = Family(name=name, timezone=tz)
    session.add(fam)
    session.commit()
    return fam


def _member(session, family_id, name="Alex", role="adult") -> Member:
    m = Member(family_id=family_id, display_name=name, role=role, created_at=NOW)
    session.add(m)
    session.commit()
    return m


def _work_item(session, family_id, title, **kw) -> WorkItem:
    wi = WorkItem(
        family_id=family_id, title=title, created_at=NOW, updated_at=NOW, **kw
    )
    session.add(wi)
    session.commit()
    return wi


def _view(session, fam, **kw) -> str:
    return build_world_view(session, fam.id, NOW, fam.timezone, **kw)


# --- members --------------------------------------------------------------


def test_members_listed_with_id_and_role(session):
    fam = _family(session)
    _member(session, fam.id, "Alex", "adult")
    _member(session, fam.id, "Sam", "child")
    out = _view(session, fam)
    assert "Alex" in out and "Sam" in out
    assert "adult" in out and "child" in out


def test_scoped_to_the_family(session):
    fam = _family(session, "Mine")
    other = _family(session, "Other")
    _member(session, fam.id, "Mine")
    _member(session, other.id, "Theirs")
    out = _view(session, fam)
    assert "Mine" in out
    assert "Theirs" not in out


# --- work items: include done, exclude archived ---------------------------


def test_work_items_include_done_exclude_archived(session):
    fam = _family(session)
    _work_item(session, fam.id, "todo item", status="todo")
    _work_item(session, fam.id, "done item", status="done")
    _work_item(session, fam.id, "archived item", status="done", archived_at=NOW)
    out = _view(session, fam)
    assert "todo item" in out
    assert "done item" in out  # done is live board state, included
    assert "archived item" not in out  # archived excluded


def test_work_item_shows_id_and_status(session):
    fam = _family(session)
    wi = _work_item(session, fam.id, "call plumber", status="doing")
    out = _view(session, fam)
    assert str(wi.id) in out
    assert "call plumber" in out
    assert "doing" in out


# --- events: past window (default 7d) + forward open ----------------------


def test_event_within_window_included(session):
    fam = _family(session)
    # 2 days ago — inside the 7-day past window.
    seed_event(
        session, fam.id, title="Recent", start_at=datetime(2026, 9, 1, 15, tzinfo=UTC)
    )
    assert "Recent" in _view(session, fam)


def test_event_before_window_excluded(session):
    fam = _family(session)
    # 30 days ago — outside the default 7-day window.
    seed_event(
        session, fam.id, title="Old", start_at=datetime(2026, 8, 4, 15, tzinfo=UTC)
    )
    assert "Old" not in _view(session, fam)


def test_future_event_included(session):
    fam = _family(session)
    seed_event(
        session, fam.id, title="Future", start_at=datetime(2026, 12, 1, 15, tzinfo=UTC)
    )
    assert "Future" in _view(session, fam)


def test_window_days_is_adjustable(session):
    fam = _family(session)
    # 10 days ago: excluded at default 7, included at 14.
    seed_event(
        session, fam.id, title="TenAgo", start_at=datetime(2026, 8, 24, 15, tzinfo=UTC)
    )
    assert "TenAgo" not in _view(session, fam)
    assert "TenAgo" in _view(session, fam, window_days=14)


def test_all_day_event_in_window(session):
    fam = _family(session)
    seed_event(
        session, fam.id, title="Holiday", all_day=True, start_date=date(2026, 9, 5)
    )
    assert "Holiday" in _view(session, fam)


# --- rendering: family tz, date + time, start + end -----------------------


def test_timed_event_rendered_in_family_tz_with_start_and_end(session):
    fam = _family(session)
    # 19:00 UTC = 15:00 (3 PM) America/New_York; 20:00 UTC = 16:00 (4 PM).
    seed_event(
        session,
        fam.id,
        title="Soccer",
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
        end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
    )
    out = _view(session, fam)
    assert "Soccer" in out
    # Rendered in family tz (3–4 PM), not the UTC hour (19/20).
    assert "3:00" in out and "4:00" in out
    assert "19:00" not in out


def test_event_id_inline(session):
    fam = _family(session)
    ev = seed_event(
        session, fam.id, title="Dentist", start_at=datetime(2026, 9, 5, 19, tzinfo=UTC)
    )
    assert str(ev.id) in _view(session, fam)


# --- empty sections -------------------------------------------------------


def test_empty_world_is_a_string_with_no_crash(session):
    fam = _family(session)
    out = _view(session, fam)
    assert isinstance(out, str) and out  # non-empty (section headers present)

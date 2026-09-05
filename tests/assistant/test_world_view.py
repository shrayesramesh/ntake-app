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

from app.assistant.context.world import (
    _EventRow,
    _fmt_event,
    _MemberRow,
    _render,
    _WorkItemRow,
    build_world_view,
)
from app.manage import seed_event
from app.persistence.models import Family, Member, WorkItem

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


# --- _render / _fmt_event: pure formatting over rows (no DB, no session) --


def test_render_formats_members_items_and_events_with_inline_ids():
    out = _render(
        members=[_MemberRow(id=1, display_name="Alex", role="adult")],
        items=[_WorkItemRow(id=7, title="call plumber", status="doing")],
        events=[
            _EventRow(
                id=3,
                title="Soccer",
                all_day=False,
                start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),
                end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),
                start_date=None,
                end_date=None,
            )
        ],
        tz=TZ,
    )
    assert "[m1] Alex (adult)" in out
    assert "[w7] call plumber (doing)" in out
    assert "[e3] Soccer" in out
    # section headers present
    assert "FAMILY MEMBERS:" in out
    assert "OPEN WORK ITEMS:" in out
    assert "EVENTS:" in out


def test_render_shows_none_for_empty_sections():
    out = _render(members=[], items=[], events=[], tz=TZ)
    assert out.count("- (none)") == 3  # one per empty section


def test_fmt_event_timed_renders_family_tz_start_and_end():
    row = _EventRow(
        id=3,
        title="Soccer",
        all_day=False,
        start_at=datetime(2026, 9, 5, 19, 0, tzinfo=UTC),  # 3 PM ET
        end_at=datetime(2026, 9, 5, 20, 0, tzinfo=UTC),  # 4 PM ET
        start_date=None,
        end_date=None,
    )
    line = _fmt_event(row, TZ)
    assert "[e3] Soccer" in line
    assert "3:00" in line and "4:00" in line
    assert "19:00" not in line  # not the UTC hour


def test_fmt_event_all_day_renders_date_and_all_day_marker():
    row = _EventRow(
        id=9,
        title="Holiday",
        all_day=True,
        start_at=None,
        end_at=None,
        start_date=date(2026, 12, 25),
        end_date=date(2026, 12, 25),
    )
    line = _fmt_event(row, TZ)
    assert "[e9] Holiday" in line
    assert "Dec 25" in line
    assert "all day" in line


def test_fmt_event_naive_start_at_treated_as_utc():
    # DB datetimes come back tz-naive (UTC). The formatter must attach UTC before
    # converting, so a naive 19:00 still renders as 3 PM ET (not left ambiguous).
    row = _EventRow(
        id=5,
        title="Dentist",
        all_day=False,
        start_at=datetime(2026, 9, 5, 19, 0),  # naive, represents UTC
        end_at=datetime(2026, 9, 5, 20, 0),
        start_date=None,
        end_date=None,
    )
    line = _fmt_event(row, TZ)
    assert "3:00" in line and "4:00" in line


# --- the populated_family fixture: real seeded content -> real world view -


def test_populated_family_world_view_reflects_seeded_content(session, populated_family):
    p = populated_family
    out = build_world_view(session, p.family.id, p.now, p.tz)

    # Assert the ENTIRE rendered block, so the exact prompt context the model
    # will see is visible and pinned here. Notes captured by this snapshot:
    #  - done included ([w3] file taxes), archived excluded (no "old chore")
    #  - out-of-window event excluded (no "Old picnic")
    #  - all-day events sort first (start_at IS NULL sorts first), then by time
    #  - tz correctness across DST: Sep event is EDT (3 PM), Dec is EST (2 PM)
    expected = (
        "FAMILY MEMBERS:\n"
        "- [m1] Alex (adult)\n"
        "- [m2] Sam (child)\n"
        "\n"
        "OPEN WORK ITEMS:\n"
        "- [w1] buy stamps (todo)\n"
        "- [w2] call plumber (doing)\n"
        "- [w3] file taxes (done)\n"
        "\n"
        "EVENTS:\n"
        "- [e4] Holiday — Sat Sep 5 (all day)\n"
        "- [e1] Soccer — Tue Sep 1, 3:00 PM\n"
        "- [e3] Dentist — Tue Dec 1, 2:00 PM"
    )
    assert out == expected

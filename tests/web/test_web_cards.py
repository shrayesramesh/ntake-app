"""Rich card renderers (task 10) — full-record board + calendar cards.

Exercises the pure renderers over REAL ORM objects seeded via the shared
conftest factories (SKILL.md: use the factories, not copied helpers). Covers the
detail branches: work-item id/description/due/assignee/update-log/tags, and event
id/description/location/participants/tags plus the dateless all-day render.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.persistence.models import WorkItemUpdate
from app.web import render_board, render_calendar

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_board_card_shows_full_record(session, fam_member, work_item_factory):
    fam, m = fam_member
    wi = work_item_factory(
        fam.id,
        title="Fix sink",
        description="Kitchen tap drips",
        due_at=datetime(2026, 9, 10, 9, 0, tzinfo=UTC),
        assigned_to=m.id,
        tags=["household", "urgent"],
    )
    # board_view attaches the update log transiently before rendering — mirror it.
    upd = WorkItemUpdate(
        work_item_id=wi.id,
        author_id=m.id,
        source="assistant",
        body="Called the plumber",
        created_at=NOW,
    )
    session.add(upd)
    session.commit()
    wi.updates = [upd]  # type: ignore[attr-defined]

    html = render_board({"todo": [wi], "on_deck": [], "doing": [], "done": []})
    assert f"#{wi.id}" in html
    assert "Kitchen tap drips" in html
    assert "due 2026-09-10 09:00 UTC" in html
    assert f"assignee m{m.id}" in html
    assert "1 update(s); latest [assistant]: Called the plumber" in html
    assert "household" in html and "urgent" in html


def test_board_card_escapes_free_text(fam_member, work_item_factory):
    fam, _m = fam_member
    wi = work_item_factory(
        fam.id, title="<b>x</b>", description="<i>d</i>", tags=["<t>"]
    )
    html = render_board({"todo": [wi], "on_deck": [], "doing": [], "done": []})
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html
    assert "&lt;i&gt;" in html


def test_event_card_shows_full_record(fam_member, event_factory):
    fam, _m = fam_member
    ev = event_factory(
        fam.id,
        title="Soccer",
        description="Bring cleats",
        location="North field",
        participants=[{"member_id": 2}, {"name": "Coach Lee"}],
    )
    html = render_calendar([ev])
    assert f"e{ev.id}" in html
    assert "Bring cleats" in html
    assert "@ North field" in html
    assert "Coach Lee" in html and "m2" in html


def test_event_card_resolves_participant_member_names(fam_member, event_factory):
    fam, m = fam_member
    ev = event_factory(
        fam.id, title="Soccer", participants=[{"member_id": m.id}, {"name": "Coach"}]
    )
    # With a name map, member links render as names; explicit names pass through.
    html = render_calendar([ev], {m.id: m.display_name})
    assert m.display_name in html
    assert "Coach" in html
    assert f"m{m.id}" not in html  # resolved to a name, not the raw id token


def test_event_card_all_day_renders_date(fam_member, event_factory):
    fam, _m = fam_member
    ev = event_factory(
        fam.id, title="Holiday", all_day=True, start_date=date(2026, 9, 4)
    )
    html = render_calendar([ev])
    assert "all-day · 2026-09-04" in html

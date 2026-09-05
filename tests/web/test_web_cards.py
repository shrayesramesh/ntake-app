"""Rich card renderers (task 10) — full-record board + calendar cards.

Exercises the pure renderers over REAL ORM objects seeded via the shared
conftest factories (SKILL.md: use the factories, not copied helpers). Covers the
detail branches: work-item id/description/due/assignee/update-log/tags, and event
id/description/location/participants/tags plus the dateless all-day render.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.persistence.models import ChecklistItem, WorkItem, WorkItemUpdate
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


def test_board_card_shows_full_ordered_checklist(
    session, fam_member, work_item_factory
):
    fam, _member = fam_member
    wi = work_item_factory(fam.id, title="Groceries")
    later = ChecklistItem(work_item_id=wi.id, text="bread", checked=True, position=2)
    first = ChecklistItem(work_item_id=wi.id, text="milk <fresh>", position=1)
    session.add_all([later, first])
    session.commit()
    wi.checklist = [first, later]  # type: ignore[attr-defined]

    html = render_board({"todo": [wi], "on_deck": [], "doing": [], "done": []})

    assert '<ul class="card-checklist">' in html
    assert "☐ milk &lt;fresh&gt;" in html
    assert "☑ bread" in html
    assert html.index("milk &lt;fresh&gt;") < html.index("bread")


def test_board_collapses_done_items_without_card_details(
    session, fam_member, work_item_factory
):
    fam, _member = fam_member
    done = work_item_factory(fam.id, title="Finished groceries", status="done")
    session.add(ChecklistItem(work_item_id=done.id, text="hidden", position=1))
    session.commit()
    done.checklist = [ChecklistItem(work_item_id=done.id, text="hidden", position=1)]  # type: ignore[attr-defined]

    html = render_board({"todo": [], "on_deck": [], "doing": [], "done": [done]})

    assert "1 done item" in html
    assert "Finished groceries" not in html
    assert "hidden" not in html
    assert 'class="card-checklist"' not in html


def test_event_card_shows_full_record(fam_member, event_factory):
    fam, _m = fam_member
    ev = event_factory(
        fam.id,
        title="Soccer",
        description="Bring cleats",
        location="North field",
        participants=["Sam", "Coach Lee"],
    )
    html = render_calendar([ev])
    assert f"e{ev.id}" in html
    assert "Bring cleats" in html
    assert "@ North field" in html
    assert "Sam" in html and "Coach Lee" in html


def test_event_card_renders_participant_names_directly(fam_member, event_factory):
    fam, m = fam_member
    ev = event_factory(fam.id, title="Soccer", participants=[m.display_name, "Coach"])

    html = render_calendar([ev])
    assert m.display_name in html
    assert "Coach" in html


def test_event_card_all_day_renders_date(fam_member, event_factory):
    fam, _m = fam_member
    ev = event_factory(
        fam.id, title="Holiday", all_day=True, start_date=date(2026, 9, 4)
    )
    html = render_calendar([ev])
    assert "all-day · 2026-09-04" in html


def test_household_scenario_board_shows_open_checklist_and_collapsed_done(
    session, household_scenario
):
    scenario = household_scenario
    groceries = session.get(WorkItem, scenario.items["groceries"])
    plumber = session.get(WorkItem, scenario.items["plumber"])
    school_forms = session.get(WorkItem, scenario.items["school_forms"])
    taxes = session.get(WorkItem, scenario.items["taxes"])
    assert groceries is not None
    assert plumber is not None
    assert school_forms is not None
    assert taxes is not None
    groceries.checklist = (
        session.query(ChecklistItem)
        .filter_by(  # type: ignore[attr-defined]
            work_item_id=groceries.id
        )
        .order_by(ChecklistItem.position)
        .all()
    )

    html = render_board(
        {
            "todo": [groceries],
            "on_deck": [school_forms],
            "doing": [plumber],
            "done": [taxes],
        }
    )

    assert "☐ milk" in html and "☑ bread" in html
    assert "1 done item" in html
    assert "File taxes" not in html

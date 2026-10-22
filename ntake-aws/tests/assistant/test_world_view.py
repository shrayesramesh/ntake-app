"""``build_world_view`` — behaviour-faithful to the reference (AWS_LLD §3.1).

Pins the exact world-view string the LINK prompt consumes: the same sections,
ordering, ``- (none)`` placeholders, ``({role})``/``({status})`` suffixes, event
``— {when}``/`` (all day)`` formatting in the family timezone, the 7-day-back
window (done included, archived excluded) as the reference
(``git show main:app/assistant/context/world.py``) — adapted only where the
int→ULID id ripple forces it: the id token is ``[w:<id>]`` / ``[e:<id>]`` /
``[m:<id>]`` (type tag + colon + ULID, Option A), preserving the reference's
type-tagged bracket shape with an unambiguous separator.

Implementation is free (the directive: *match the observable string*); these
tests assert that string, built from the ``Repository`` reads. Fixed ids (not the
random-ULID factories) so the expected string is deterministic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from core.assistant.world import build_world_view
from core.repository_memory import InMemoryRepository
from core.schemas import Event, Family, Member, WorkItem

# A fixed "now" so the 7-day window and relative rendering are deterministic.
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)  # Thu Sep 3 2026, 08:00 America/New_York
TZ = "America/New_York"


def _family() -> Family:
    return Family(id="fam1", name="Test", timezone=TZ, created_at=NOW)


def _member(mid: str, name: str, role: str) -> Member:
    return Member(
        id=mid, family_id="fam1", display_name=name, role=role, created_at=NOW
    )


def _wi(wid: str, title: str, status: str) -> WorkItem:
    return WorkItem(
        id=wid,
        family_id="fam1",
        title=title,
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _timed(eid: str, title: str, start: datetime, end: datetime) -> Event:
    return Event(
        id=eid,
        family_id="fam1",
        title=title,
        all_day=False,
        start_at=start,
        end_at=end,
        created_at=NOW,
        updated_at=NOW,
    )


def _all_day(eid: str, title: str, start: date, end: date) -> Event:
    return Event(
        id=eid,
        family_id="fam1",
        title=title,
        all_day=True,
        start_date=start,
        end_date=end,
        created_at=NOW,
        updated_at=NOW,
    )


def _at(h: int) -> datetime:
    return datetime(2026, 9, 5, h, 0, tzinfo=UTC)


def _build() -> str:
    repo = InMemoryRepository()
    repo.seed_family(
        _family(),
        [_member("m1", "Alex", "adult"), _member("m2", "Sam", "child")],
    )
    # Work items: todo, doing, done (done INCLUDED), plus one archived (EXCLUDED).
    repo.put_work_item(_wi("w1", "buy stamps", "todo"))
    repo.put_work_item(_wi("w2", "call plumber", "doing"))
    repo.put_work_item(_wi("w3", "file taxes", "done"))
    repo.put_work_item(_wi("w9", "old thing", "todo"))
    repo.archive_work_item("fam1", "w9")
    # Events: in-window timed, in-window all-day, and one OUT of window (old).
    repo.put_event(_timed("e1", "Soccer", _at(19), _at(20)))
    repo.put_event(_all_day("e4", "Holiday", date(2026, 9, 5), date(2026, 9, 5)))
    repo.put_event(
        _timed(
            "e8",
            "Old thing",
            datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 8, 1, 13, 0, tzinfo=UTC),
        )
    )
    return build_world_view(repo, "fam1", NOW, TZ)


def test_world_view_exact_format() -> None:
    expected = (
        "FAMILY MEMBERS:\n"
        "- [m:m1] Alex (adult)\n"
        "- [m:m2] Sam (child)\n"
        "\n"
        "OPEN WORK ITEMS:\n"
        "- [w:w1] buy stamps (todo)\n"
        "- [w:w2] call plumber (doing)\n"
        "- [w:w3] file taxes (done)\n"
        "\n"
        "EVENTS:\n"
        "- [e:e4] Holiday — Sat Sep 5 (all day)\n"
        "- [e:e1] Soccer — Sat Sep 5, 3:00 PM – Sat Sep 5, 4:00 PM"
    )
    assert _build() == expected


def test_world_view_excludes_archived_work_item() -> None:
    assert "old thing" not in _build()


def test_world_view_excludes_out_of_window_event() -> None:
    assert "Old thing" not in _build()  # Aug 1 is > 7 days before Sep 3


def test_world_view_empty_sections_render_none() -> None:
    repo = InMemoryRepository()
    repo.seed_family(_family(), [])
    out = build_world_view(repo, "fam1", NOW, TZ)
    assert out == (
        "FAMILY MEMBERS:\n- (none)\n\nOPEN WORK ITEMS:\n- (none)\n\nEVENTS:\n- (none)"
    )


def test_world_view_timed_event_collapses_equal_start_end() -> None:
    repo = InMemoryRepository()
    repo.seed_family(_family(), [])
    repo.put_event(_timed("e1", "Point", _at(19), _at(19)))
    out = build_world_view(repo, "fam1", NOW, TZ)
    # When start == end, render a single time (no " – " range).
    assert "- [e:e1] Point — Sat Sep 5, 3:00 PM" in out
    assert "–" not in out

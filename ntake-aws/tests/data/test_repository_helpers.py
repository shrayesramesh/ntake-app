"""Unit tests for the pure key/sort-derivation helpers (AWS_LLD §1.2, §2).

These live in :mod:`core.repository` as the single source of table-key knowledge
(reused byte-for-byte by ``DynamoRepository`` in Session 3). Tested directly, in
isolation from any backend — the "supplement with unit tests for pure functions"
tier of the operating rules.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from core.repository import (
    board_sort_key,
    calendar_sort_ts,
    connection_sk,
    event_sk,
    family_pk,
    member_sk,
    work_item_due_sort_ts,
    work_item_sk,
)
from tests.harness.factories import make_all_day_event, make_timed_event

# --- key composers ---------------------------------------------------------


def test_key_composers_add_type_prefixes() -> None:
    assert family_pk("abc") == "FAM#abc"
    assert work_item_sk("w1") == "WI#w1"
    assert event_sk("e1") == "EV#e1"
    assert member_sk("m1") == "MEM#m1"
    assert connection_sk("c1") == "CONN#c1"


# --- board sort key --------------------------------------------------------


def test_board_sort_key_zero_pads_position() -> None:
    assert board_sort_key("todo", 0) == "STATUS#todo#POS#000000"
    assert board_sort_key("doing", 42) == "STATUS#doing#POS#000042"


def test_board_sort_key_lexical_order_matches_numeric_position() -> None:
    """Zero-padding makes a string sort reproduce numeric position order."""
    keys = [board_sort_key("todo", p) for p in (10, 2, 1, 100)]
    assert sorted(keys) == [
        board_sort_key("todo", 1),
        board_sort_key("todo", 2),
        board_sort_key("todo", 10),
        board_sort_key("todo", 100),
    ]


def test_board_sort_key_groups_by_status_then_position() -> None:
    """A lexical sort groups a column together, then orders within it."""
    unsorted = [
        board_sort_key("todo", 1),
        board_sort_key("doing", 0),
        board_sort_key("todo", 0),
        board_sort_key("doing", 1),
    ]
    assert sorted(unsorted) == [
        board_sort_key("doing", 0),
        board_sort_key("doing", 1),
        board_sort_key("todo", 0),
        board_sort_key("todo", 1),
    ]


# --- calendar sort_ts ------------------------------------------------------


def test_calendar_sort_ts_timed_event_uses_start_at() -> None:
    start = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    ev = make_timed_event("fam", start_at=start)
    assert calendar_sort_ts(ev, "America/New_York") == start


def test_calendar_sort_ts_normalizes_naive_start_at_to_utc() -> None:
    """A tz-naive stored start is treated as UTC (storage convention)."""
    ev = make_timed_event("fam", start_at=datetime(2026, 2, 1, 9, 0))
    assert calendar_sort_ts(ev, "UTC") == datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


def test_calendar_sort_ts_all_day_uses_family_midnight_utc() -> None:
    """All-day sorts by family-midnight expressed in UTC (not naive midnight)."""
    ev = make_all_day_event("fam", start_date=date(2026, 2, 2))
    tz = "America/New_York"  # UTC-5 in February
    got = calendar_sort_ts(ev, tz)
    # Local 2026-02-02 00:00 in New York == 2026-02-02 05:00 UTC.
    expected = datetime(2026, 2, 2, 0, 0, tzinfo=ZoneInfo(tz)).astimezone(UTC)
    assert got == expected
    assert got == datetime(2026, 2, 2, 5, 0, tzinfo=UTC)


def test_calendar_sort_ts_all_day_differs_by_timezone() -> None:
    ev = make_all_day_event("fam", start_date=date(2026, 6, 1))
    ny = calendar_sort_ts(ev, "America/New_York")
    tokyo = calendar_sort_ts(ev, "Asia/Tokyo")
    assert ny != tokyo  # same local day, different UTC instant


# --- work-item due sort_ts -------------------------------------------------


def test_work_item_due_sort_ts_present_and_absent() -> None:
    from tests.harness.factories import make_work_item

    with_due = make_work_item("fam", due_at=datetime(2026, 2, 5, 17, 0, tzinfo=UTC))
    without_due = make_work_item("fam", due_at=None)
    assert work_item_due_sort_ts(with_due) == datetime(2026, 2, 5, 17, 0, tzinfo=UTC)
    assert work_item_due_sort_ts(without_due) is None

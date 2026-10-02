"""UTC <-> family-local conversion at the timed boundary (core/temporal.py).

Pure, infra-agnostic time math (NFR-TIME). Re-expressed from the self-hosted
temporal suite against ``core.temporal`` (which now imports ``ActionError`` from
``core.engine.engine``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.engine.engine import ActionError
from core.temporal import (
    family_local_to_utc,
    stored_utc_to_family_local,
    validate_family_local_datetime,
)

NY = "America/New_York"


def test_family_local_to_utc_standard_time() -> None:
    # 2025-01-15 09:00 EST (UTC-5) -> 14:00 UTC, tz-naive storage value.
    out = family_local_to_utc("2025-01-15T09:00:00", NY)
    assert out == datetime(2025, 1, 15, 14, 0, 0)
    assert out.tzinfo is None


def test_family_local_to_utc_daylight_time() -> None:
    # 2025-07-15 09:00 EDT (UTC-4) -> 13:00 UTC.
    assert family_local_to_utc("2025-07-15T09:00:00", NY) == datetime(2025, 7, 15, 13)


def test_round_trip_utc_to_local_and_back() -> None:
    local = "2025-03-20T18:30:00"
    stored = family_local_to_utc(local, NY)
    back = stored_utc_to_family_local(stored, NY)
    assert back == datetime(2025, 3, 20, 18, 30, 0)
    assert back.tzinfo is None


def test_stored_utc_to_family_local_accepts_aware_input() -> None:
    aware = datetime(2025, 1, 15, 14, 0, 0, tzinfo=UTC)
    assert stored_utc_to_family_local(aware, NY) == datetime(2025, 1, 15, 9, 0, 0)


def test_validate_family_local_returns_naive_wall_time() -> None:
    out = validate_family_local_datetime("2025-01-15T09:00:00", NY)
    assert out == datetime(2025, 1, 15, 9, 0, 0)
    assert out.tzinfo is None


def test_rejects_offset_aware_value() -> None:
    with pytest.raises(ActionError):
        family_local_to_utc("2025-01-15T09:00:00+00:00", NY)


def test_rejects_unparseable_value() -> None:
    with pytest.raises(ActionError):
        family_local_to_utc("not-a-date", NY)


def test_rejects_non_string_timezone_as_action_error() -> None:
    # A non-string tz hits ZoneInfo's TypeError path, which _zone converts to
    # ActionError (temporal.py line 69). (An unknown *string* zone raises
    # ZoneInfoNotFoundError — a KeyError — which the lifted code does not wrap;
    # that quirk is left as-is in Session 1, see the module.)
    with pytest.raises(ActionError):
        family_local_to_utc("2025-01-15T09:00:00", 123)  # type: ignore[arg-type]


def test_rejects_nonexistent_spring_forward_time() -> None:
    # 2025-03-09 02:30 does not exist in NY (clocks jump 02:00 -> 03:00 EDT).
    with pytest.raises(ActionError):
        family_local_to_utc("2025-03-09T02:30:00", NY)


def test_rejects_ambiguous_fall_back_time() -> None:
    # 2025-11-02 01:30 occurs twice in NY (fall back) -> ambiguous.
    with pytest.raises(ActionError):
        family_local_to_utc("2025-11-02T01:30:00", NY)

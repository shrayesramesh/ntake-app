"""Family-local timed value persistence boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.persistence.temporal import family_local_to_utc, stored_utc_to_family_local
from app.routing.engine import ActionError

CHICAGO = "America/Chicago"


def test_chicago_thursday_8pm_round_trips_through_utc_storage():
    """A local model/action value is stored as UTC and read back locally."""
    local = "2026-09-10T20:00:00"

    stored = family_local_to_utc(local, CHICAGO)

    assert stored == datetime(2026, 9, 11, 1, 0)
    assert stored_utc_to_family_local(stored, CHICAGO) == datetime(2026, 9, 10, 20, 0)


def test_utc_storage_reads_as_family_local_not_utc():
    stored = datetime(2026, 9, 11, 1, 0, tzinfo=UTC)

    local = stored_utc_to_family_local(stored, CHICAGO)

    assert local == datetime(2026, 9, 10, 20, 0)
    assert local.tzinfo is None


@pytest.mark.parametrize(
    "value",
    [
        "2026-03-08T02:30:00",  # spring-forward gap in America/Chicago
        "2026-11-01T01:30:00",  # fall-back overlap in America/Chicago
    ],
)
def test_dst_nonexistent_or_ambiguous_local_wall_time_is_rejected(value: str):
    with pytest.raises(ActionError):
        family_local_to_utc(value, CHICAGO)


def test_model_values_must_not_supply_an_offset_or_timezone():
    with pytest.raises(ActionError, match="family-local"):
        family_local_to_utc("2026-09-10T20:00:00Z", CHICAGO)

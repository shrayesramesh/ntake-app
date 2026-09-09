"""Family-local <-> UTC conversion at the timed persistence boundary.

Timed values enter application code as ISO-8601 local wall times in the trusted
family timezone. SQLite returns stored UTC datetimes as tz-naive values, so this
module owns both explicit conversions. All-day values are dates and do not pass
through this mapper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.routing.engine import ActionError


def family_local_to_utc(value: str, timezone: str) -> datetime:
    """Validate one local wall time and return the UTC-naive storage value."""
    local, candidate = _validated_local_wall_time(value, timezone)
    return candidate.astimezone(UTC).replace(tzinfo=None)


def validate_family_local_datetime(value: str, timezone: str) -> datetime:
    """Validate an offset-free family-local value without crossing into storage."""
    local, _candidate = _validated_local_wall_time(value, timezone)
    return local


def _validated_local_wall_time(value: str, timezone: str) -> tuple[datetime, datetime]:
    try:
        local = datetime.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ActionError(f"invalid local datetime: {value!r}") from e
    if local.tzinfo is not None:
        raise ActionError("datetime must be an offset-free family-local value")

    zone = _zone(timezone)
    candidates = [
        local.replace(tzinfo=zone, fold=fold)
        for fold in (0, 1)
        if _round_trips(local, zone, fold)
    ]
    if not candidates:
        raise ActionError(f"nonexistent local time in {timezone}: {value!r}")
    if len(candidates) == 2 and candidates[0].utcoffset() != candidates[1].utcoffset():
        raise ActionError(f"ambiguous local time in {timezone}: {value!r}")

    return local, candidates[0]


def stored_utc_to_family_local(value: datetime, timezone: str) -> datetime:
    """Return the offset-free family-local wall time for a stored UTC value."""
    zone = _zone(timezone)
    stored_utc = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return stored_utc.astimezone(zone).replace(tzinfo=None)


def _round_trips(local: datetime, zone: ZoneInfo, fold: int) -> bool:
    candidate = local.replace(tzinfo=zone, fold=fold)
    return candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (TypeError, ValueError) as e:
        raise ActionError(f"invalid family timezone: {timezone!r}") from e

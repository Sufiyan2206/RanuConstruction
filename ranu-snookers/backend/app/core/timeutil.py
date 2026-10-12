"""Time helpers. The database always stores UTC; conversion to the branch's
local timezone happens only at the business/UI boundary (pricing windows,
reports grouped by local day, display)."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

_clock_override: datetime | None = None


def utcnow() -> datetime:
    """Timezone-aware 'now' in UTC. Tests may freeze it via `freeze()`."""
    return _clock_override or datetime.now(UTC)


def freeze(at: datetime | None) -> None:
    global _clock_override
    _clock_override = ensure_utc(at) if at else None


def ensure_utc(dt: datetime) -> datetime:
    """Treat naive datetimes (SQLite / MySQL round-trips) as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_local(dt: datetime, tz_name: str) -> datetime:
    return ensure_utc(dt).astimezone(ZoneInfo(tz_name))


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open interval overlap: [a_start, a_end) ∩ [b_start, b_end) ≠ ∅."""
    return ensure_utc(a_start) < ensure_utc(b_end) and ensure_utc(b_start) < ensure_utc(a_end)

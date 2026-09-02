"""Timezone helpers. The bot thinks in *local* days (``LOCAL_TZ``) but every
upstream API speaks UTC / RFC3339, so conversions live here in one place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import config


def _tz() -> ZoneInfo:
    return ZoneInfo(config.LOCAL_TZ)


def now_local() -> datetime:
    return datetime.now(_tz())


def today_local_iso() -> str:
    return now_local().date().isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO8601 / RFC3339 string, tolerating a trailing ``Z`` and
    naive values (assumed UTC)."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def local_date_of(value: str | datetime) -> str:
    dt = value if isinstance(value, datetime) else parse_iso(value)
    return dt.astimezone(_tz()).date().isoformat()


def utc_cutoff(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def day_bounds_utc(day_iso: str) -> tuple[str, str]:
    """RFC3339 UTC ``[start, end)`` covering one local calendar day."""
    start_local = datetime.fromisoformat(day_iso).replace(tzinfo=_tz())
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(UTC).isoformat(),
        end_local.astimezone(UTC).isoformat(),
    )

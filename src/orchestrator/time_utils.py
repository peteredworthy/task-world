"""Datetime helpers for UTC normalization and JSON serialization."""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    SQLite commonly returns naive datetimes; treat those as UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ensure_utc_optional(dt: datetime | None) -> datetime | None:
    """Like ``ensure_utc`` but preserves ``None``."""
    if dt is None:
        return None
    return ensure_utc(dt)


def format_utc_datetime(dt: datetime) -> str:
    """Serialize datetime as ISO-8601 in UTC with trailing Z."""
    return ensure_utc(dt).isoformat().replace("+00:00", "Z")

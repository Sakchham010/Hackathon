"""UTC time helpers.

MongoDB stores BSON datetimes; every timestamp written by this project must be
timezone-aware UTC so documents compare and sort correctly regardless of the
machine's local timezone.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

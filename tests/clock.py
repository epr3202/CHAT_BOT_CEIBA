"""Shared, explicit clock anchors for literal booking/payment scenarios."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo

BOOKING_NOW = datetime(2026, 9, 29, 15, tzinfo=UTC)
BALANCE_NOW = BOOKING_NOW + timedelta(days=3)


class FrozenDateTime(datetime):
    instant = BOOKING_NOW

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


FreezeAppClock = Callable[[datetime | type[FrozenDateTime]], type[FrozenDateTime]]

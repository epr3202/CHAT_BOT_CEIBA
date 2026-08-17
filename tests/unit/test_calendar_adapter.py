from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.calendar.adapter import (
    AlreadyExistsError,
    BusyInterval,
    CalendarUnavailableError,
    EventNotFoundError,
    FakeCalendarAdapter,
    get_calendar_adapter,
)
from app.config.settings import get_settings

BOGOTA = ZoneInfo("America/Bogota")


def dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BOGOTA)


async def test_fake_calendar_unions_busy_intervals_for_requested_calendars() -> None:
    adapter = FakeCalendarAdapter(
        busy_by_calendar={
            "write": [BusyInterval(dt(2026, 8, 18, 9), dt(2026, 8, 18, 9, 30))],
            "main": [BusyInterval(dt(2026, 8, 18, 10), dt(2026, 8, 18, 10, 30))],
            "ignored": [BusyInterval(dt(2026, 8, 18, 11), dt(2026, 8, 18, 11, 30))],
        }
    )

    intervals = await adapter.get_busy_intervals(date(2026, 8, 18), ["write", "main"])

    assert len(intervals) == 2
    assert adapter.queried_calendar_ids == [["write", "main"]]


async def test_fake_calendar_create_enforces_event_id_uniqueness() -> None:
    adapter = FakeCalendarAdapter()
    await adapter.create_event("local-id", "Visita", dt(2026, 8, 18, 9), dt(2026, 8, 18, 9, 45))

    with pytest.raises(AlreadyExistsError):
        await adapter.create_event(
            "local-id",
            "Visita duplicada",
            dt(2026, 8, 18, 9),
            dt(2026, 8, 18, 9, 45),
        )


async def test_fake_calendar_timeout_after_create_persists_event_for_retry() -> None:
    adapter = FakeCalendarAdapter(timeout_after_create=True)

    with pytest.raises(CalendarUnavailableError):
        await adapter.create_event(
            "local-id",
            "Visita",
            dt(2026, 8, 18, 9),
            dt(2026, 8, 18, 9, 45),
        )

    with pytest.raises(AlreadyExistsError):
        await adapter.create_event(
            "local-id",
            "Visita",
            dt(2026, 8, 18, 9),
            dt(2026, 8, 18, 9, 45),
        )


async def test_fake_calendar_delete_and_get_event() -> None:
    adapter = FakeCalendarAdapter()
    event = await adapter.create_event(
        "local-id",
        "Visita",
        dt(2026, 8, 18, 9),
        dt(2026, 8, 18, 9, 45),
    )

    assert await adapter.get_event("local-id") == event
    await adapter.delete_event("local-id")

    with pytest.raises(EventNotFoundError):
        await adapter.get_event("local-id")


def test_calendar_adapter_settings_selects_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba")
    monkeypatch.setenv("META_APP_SECRET", "test")
    monkeypatch.setenv("META_ACCESS_TOKEN", "test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setenv("CALENDAR_ADAPTER", "fake")
    get_settings.cache_clear()

    adapter = get_calendar_adapter(get_settings())

    assert isinstance(adapter, FakeCalendarAdapter)
    get_settings.cache_clear()

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol

from app.config.settings import Settings


class CalendarUnavailableError(RuntimeError):
    """Calendar provider could not complete the requested operation."""


class AlreadyExistsError(RuntimeError):
    """Calendar provider already has an event with the supplied id."""


class EventNotFoundError(RuntimeError):
    """Calendar provider has no event with the supplied id."""


@dataclass(frozen=True)
class BusyInterval:
    start: datetime
    end: datetime

    def intersects(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end


@dataclass(frozen=True)
class ExternalEventRef:
    event_id: str
    summary: str
    start: datetime
    end: datetime


class CalendarAdapter(Protocol):
    async def get_busy_intervals(
        self,
        target_date: date,
        calendar_ids: Iterable[str],
    ) -> list[BusyInterval]:
        ...

    async def create_event(
        self,
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
    ) -> ExternalEventRef:
        ...

    async def delete_event(self, event_id: str) -> None:
        ...

    async def get_event(self, event_id: str) -> ExternalEventRef:
        ...


class FakeCalendarAdapter:
    def __init__(
        self,
        busy_by_calendar: dict[str, list[BusyInterval]] | None = None,
        raise_on: set[str] | None = None,
        timeout_after_create: bool = False,
    ) -> None:
        self.busy_by_calendar = busy_by_calendar or {}
        self.raise_on = raise_on or set()
        self.timeout_after_create = timeout_after_create
        self._events: dict[str, ExternalEventRef] = {}
        self.created_event_ids: list[str] = []
        self.deleted_event_ids: list[str] = []
        self.queried_calendar_ids: list[list[str]] = []
        self.create_call_count = 0
        self.delete_call_count = 0
        self.query_call_count = 0

    def add_busy(self, calendar_id: str, start: datetime, end: datetime) -> None:
        self.busy_by_calendar.setdefault(calendar_id, []).append(BusyInterval(start, end))

    async def get_busy_intervals(
        self,
        target_date: date,
        calendar_ids: Iterable[str],
    ) -> list[BusyInterval]:
        self.query_call_count += 1
        calendar_id_list = list(calendar_ids)
        self.queried_calendar_ids.append(calendar_id_list)
        if "query" in self.raise_on:
            raise CalendarUnavailableError("fake calendar query failed")

        intervals: list[BusyInterval] = []
        for calendar_id in calendar_id_list:
            intervals.extend(
                interval
                for interval in self.busy_by_calendar.get(calendar_id, [])
                if _interval_touches_date(interval, target_date)
            )
        return intervals

    async def create_event(
        self,
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
    ) -> ExternalEventRef:
        self.create_call_count += 1
        if event_id in self._events:
            raise AlreadyExistsError(f"calendar event already exists: {event_id}")
        if "create" in self.raise_on:
            raise CalendarUnavailableError("fake calendar create failed")

        event = ExternalEventRef(event_id=event_id, summary=summary, start=start, end=end)
        self._events[event_id] = event
        self.created_event_ids.append(event_id)
        if self.timeout_after_create:
            self.timeout_after_create = False
            raise CalendarUnavailableError("fake calendar timed out after create")
        return event

    async def delete_event(self, event_id: str) -> None:
        self.delete_call_count += 1
        if "delete" in self.raise_on:
            raise CalendarUnavailableError("fake calendar delete failed")
        if event_id not in self._events:
            raise EventNotFoundError(f"calendar event not found: {event_id}")
        del self._events[event_id]
        self.deleted_event_ids.append(event_id)

    async def get_event(self, event_id: str) -> ExternalEventRef:
        if "get" in self.raise_on:
            raise CalendarUnavailableError("fake calendar get failed")
        try:
            return self._events[event_id]
        except KeyError as exc:
            raise EventNotFoundError(f"calendar event not found: {event_id}") from exc


def get_calendar_adapter(settings: Settings) -> CalendarAdapter:
    if settings.calendar_adapter == "fake":
        return FakeCalendarAdapter()
    raise ValueError(f"Unsupported calendar adapter: {settings.calendar_adapter}")


def _interval_touches_date(interval: BusyInterval, target_date: date) -> bool:
    start_of_day = datetime.combine(target_date, time.min, tzinfo=interval.start.tzinfo)
    end_of_day = datetime.combine(target_date, time.max, tzinfo=interval.start.tzinfo)
    return interval.intersects(start_of_day, end_of_day)

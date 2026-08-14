from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.appointment.models import ACTIVE_APPOINTMENT_STATUSES, Appointment, BlockedDate, Holiday
from app.calendar.adapter import BusyInterval, CalendarAdapter, CalendarUnavailableError

VISIT_TIMEZONE = ZoneInfo("America/Bogota")
VISIT_START_TIMES = (time(8), time(9), time(10), time(11))
VISIT_DURATION = timedelta(minutes=45)
MINIMUM_NOTICE_DAYS = 3


@dataclass(frozen=True)
class VisitDateDecision:
    accepted: bool
    response_code: str | None = None


@dataclass(frozen=True)
class VisitSlot:
    start_time: time
    end_time: time

    @property
    def label(self) -> str:
        return self.start_time.strftime("%H:%M")


@dataclass(frozen=True)
class AvailabilityResult:
    visit_date: date
    slots: list[VisitSlot]
    response_code: str
    requires_review: bool = False


def validate_visit_date(
    visit_date: date,
    *,
    today: date,
    holidays: set[date],
    blocked_dates: set[date],
) -> VisitDateDecision:
    days_until_visit = (visit_date - today).days
    if days_until_visit == 0:
        return VisitDateDecision(False, "RESP-VISIT-004")
    if days_until_visit == 1:
        return VisitDateDecision(False, "RESP-VISIT-005")
    if visit_date.weekday() in {0, 6}:
        return VisitDateDecision(False, "RESP-VISIT-006")
    if visit_date in holidays:
        return VisitDateDecision(False, "RESP-VISIT-007")
    if visit_date in blocked_dates:
        return VisitDateDecision(False, "RESP-VISIT-008")
    if days_until_visit < MINIMUM_NOTICE_DAYS:
        return VisitDateDecision(False, "RESP-VISIT-004")
    return VisitDateDecision(True)


def deterministic_visit_slots() -> list[VisitSlot]:
    return [VisitSlot(start, _slot_end(start)) for start in VISIT_START_TIMES]


def slot_datetime(visit_date: date, slot_time: time) -> datetime:
    return datetime.combine(visit_date, slot_time, tzinfo=VISIT_TIMEZONE)


def busy_intersects_slot(interval: BusyInterval, visit_date: date, slot_time: time) -> bool:
    slot_start = slot_datetime(visit_date, slot_time)
    slot_end = slot_start + VISIT_DURATION
    return interval.intersects(slot_start, slot_end)


class AvailabilityService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        calendar_adapter: CalendarAdapter,
        freebusy_calendar_ids: Iterable[str],
    ) -> None:
        self.sessionmaker = sessionmaker
        self.calendar_adapter = calendar_adapter
        self.freebusy_calendar_ids = list(freebusy_calendar_ids)

    async def available_slots(
        self,
        visit_date: date,
        *,
        today: date,
        request_id: str | None = None,
    ) -> AvailabilityResult:
        holidays, blocked_dates, local_active_times = await self._local_calendar_state(visit_date)
        decision = validate_visit_date(
            visit_date,
            today=today,
            holidays=holidays,
            blocked_dates=blocked_dates,
        )
        if not decision.accepted:
            return AvailabilityResult(visit_date, [], decision.response_code or "RESP-VISIT-009")

        try:
            busy_intervals = await self.calendar_adapter.get_busy_intervals(
                visit_date,
                self.freebusy_calendar_ids,
            )
        except CalendarUnavailableError:
            return AvailabilityResult(
                visit_date,
                [],
                "RESP-CALENDAR-ERROR-001",
                requires_review=True,
            )

        slots = [
            slot
            for slot in deterministic_visit_slots()
            if slot.start_time not in local_active_times
            and not any(
                busy_intersects_slot(interval, visit_date, slot.start_time)
                for interval in busy_intervals
            )
        ]
        if not slots:
            return AvailabilityResult(visit_date, [], "RESP-VISIT-009")
        return AvailabilityResult(visit_date, slots, "RESP-VISIT-TIME-001")

    async def _local_calendar_state(
        self,
        visit_date: date,
    ) -> tuple[set[date], set[date], set[time]]:
        async with self.sessionmaker() as session:
            holidays = set(
                await session.scalars(
                    select(Holiday.holiday_date).where(Holiday.holiday_date == visit_date)
                )
            )
            blocked_dates = set(
                await session.scalars(
                    select(BlockedDate.blocked_date).where(BlockedDate.blocked_date == visit_date)
                )
            )
            active_times = set(
                await session.scalars(
                    select(Appointment.start_time).where(
                        Appointment.appointment_date == visit_date,
                        Appointment.appointment_status.in_(ACTIVE_APPOINTMENT_STATUSES),
                    )
                )
            )
        return holidays, blocked_dates, active_times


def _slot_end(start_time: time) -> time:
    return (datetime.combine(date.min, start_time) + VISIT_DURATION).time()

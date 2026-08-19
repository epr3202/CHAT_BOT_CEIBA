from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.appointment.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentChange,
    calculate_visit_end_time,
)
from app.calendar.adapter import (
    AlreadyExistsError,
    CalendarAdapter,
    CalendarUnavailableError,
    EventNotFoundError,
)
from app.conversation.states import ConversationState
from app.scheduling.availability import AvailabilityService, slot_datetime

BOGOTA = ZoneInfo("America/Bogota")
DEFAULT_REMINDER_SEND_TIME = time(9)

VisitDateInterpretation = Literal["EXACTA", "RELATIVA", "NO_INTERPRETABLE"]
VisitTimeInterpretation = Literal[
    "OFFERED_SLOT",
    "OUTSIDE_OFFER",
    "NO_INTERPRETABLE",
    "OUT_OF_HOURS",
]

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
SPANISH_WEEKDAYS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}
SPANISH_HOURS = {
    "dos": 2,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
}


@dataclass(frozen=True)
class VisitDateTextResult:
    resolved_date: date | None
    needs_confirmation: bool
    next_state: ConversationState
    interpretation: VisitDateInterpretation = "NO_INTERPRETABLE"


@dataclass(frozen=True)
class VisitTimeResult:
    accepted: bool
    preferred_visit_time: time | None = None
    response_code: str | None = None
    interpretation: VisitTimeInterpretation = "NO_INTERPRETABLE"


@dataclass(frozen=True)
class VisitAttendeesResult:
    accepted: bool
    response_code: str | None = None
    needs_handoff: bool = False


@dataclass(frozen=True)
class VisitServiceResult:
    response_code: str
    state: ConversationState | None = None
    appointment_id: UUID | None = None
    external_calendar_id: str | None = None


@dataclass(frozen=True)
class VisitReminder:
    appointment_id: UUID
    scheduled_at: datetime
    response_code: str


def resolve_visit_date_text(
    message_text: str,
    *,
    today: date,
    require_absolute_confirmation: bool,
) -> VisitDateTextResult:
    normalized = _normalize_spanish_text(message_text)
    relative = _resolve_relative_visit_date(normalized, today)
    if relative is not None:
        return VisitDateTextResult(
            relative,
            needs_confirmation=require_absolute_confirmation,
            next_state=ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            interpretation="RELATIVA",
        )

    absolute = _resolve_absolute_visit_date(normalized, today)
    if absolute is not None:
        return VisitDateTextResult(
            absolute,
            needs_confirmation=False,
            next_state=ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            interpretation="EXACTA",
        )

    return VisitDateTextResult(
        None,
        needs_confirmation=False,
        next_state=ConversationState.WAITING_FOR_APPOINTMENT_DATE,
        interpretation="NO_INTERPRETABLE",
    )


def interpret_visit_time(message_text: str, offered_slots: list[time]) -> VisitTimeResult:
    normalized = _normalize_spanish_text(message_text)
    candidate = _extract_visit_time(normalized)
    if candidate is None:
        return VisitTimeResult(
            False,
            response_code="RESP-VISIT-TIME-003",
            interpretation="NO_INTERPRETABLE",
        )

    allowed_times = {time(8), time(9), time(10), time(11)}
    if candidate not in allowed_times:
        return VisitTimeResult(
            False,
            preferred_visit_time=candidate,
            response_code="RESP-VISIT-TIME-002",
            interpretation="OUT_OF_HOURS",
        )

    if candidate not in set(offered_slots):
        return VisitTimeResult(
            False,
            preferred_visit_time=candidate,
            response_code="RESP-VISIT-TIME-004",
            interpretation="OUTSIDE_OFFER",
        )

    return VisitTimeResult(
        True,
        preferred_visit_time=candidate,
        interpretation="OFFERED_SLOT",
    )


def _normalize_spanish_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _resolve_relative_visit_date(normalized: str, today: date) -> date | None:
    if re.search(r"\bpasado\s+manana\b", normalized):
        return today + timedelta(days=2)
    if re.search(r"\bmanana\b", normalized):
        return today + timedelta(days=1)
    if re.search(r"\bhoy\b", normalized):
        return today

    for weekday_name, weekday in SPANISH_WEEKDAYS.items():
        if not re.search(rf"\b(?:(?:el|este|proximo)\s+)?{weekday_name}\b", normalized):
            continue
        days_until = (weekday - today.weekday()) % 7
        if days_until == 0:
            days_until = 7
        return today + timedelta(days=days_until)
    return None


def _resolve_absolute_visit_date(normalized: str, today: date) -> date | None:
    numeric = re.search(r"\b(\d{1,2})\s*[/-]\s*(\d{1,2})(?:\s*[/-]\s*(\d{2,4}))?\b", normalized)
    if numeric is not None:
        day_value = int(numeric.group(1))
        month_value = int(numeric.group(2))
        year_text = numeric.group(3)
        year_value = int(year_text) if year_text else None
        if year_value is not None and year_value < 100:
            year_value += 2000
        return _future_date(day_value, month_value, year_value, today)

    month_pattern = "|".join(SPANISH_MONTHS)
    textual = re.search(
        rf"\b(\d{{1,2}})\s+(?:de\s+)?({month_pattern})(?:\s+de\s+(\d{{4}}))?\b",
        normalized,
    )
    if textual is None:
        return None
    return _future_date(
        int(textual.group(1)),
        SPANISH_MONTHS[textual.group(2)],
        int(textual.group(3)) if textual.group(3) else None,
        today,
    )


def _future_date(
    day_value: int,
    month_value: int,
    year_value: int | None,
    today: date,
) -> date | None:
    inferred_year = year_value or today.year
    try:
        candidate = date(inferred_year, month_value, day_value)
    except ValueError:
        return None
    if year_value is not None:
        return candidate if candidate >= today else None
    if candidate < today:
        try:
            return date(today.year + 1, month_value, day_value)
        except ValueError:
            return None
    return candidate


def _extract_visit_time(normalized: str) -> time | None:
    numeric = re.search(r"\b(?:a\s+las?\s+)?(\d{1,2})(?::(\d{2}))?\b", normalized)
    if numeric is not None:
        hour_value = int(numeric.group(1))
        minute_value = int(numeric.group(2) or 0)
        is_afternoon = any(token in normalized for token in ("tarde", "pm", "p. m."))
        if is_afternoon and 1 <= hour_value < 12:
            hour_value += 12
        try:
            return time(hour_value, minute_value)
        except ValueError:
            return None

    for word, hour_value in SPANISH_HOURS.items():
        if re.search(rf"\b{word}\b", normalized):
            if "tarde" in normalized and hour_value < 12:
                hour_value += 12
            return time(hour_value)
    return None


def validate_visit_attendees(
    attendee_count: int,
    *,
    exception_requested: bool,
) -> VisitAttendeesResult:
    if 1 <= attendee_count <= 3:
        return VisitAttendeesResult(True)
    if exception_requested:
        return VisitAttendeesResult(False, "RESP-VISIT-DATA-002", needs_handoff=True)
    return VisitAttendeesResult(False, "RESP-VISIT-DATA-002")


class VisitSchedulingService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        calendar_adapter: CalendarAdapter,
        freebusy_calendar_ids: list[str],
        reminder_send_time: time = DEFAULT_REMINDER_SEND_TIME,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.calendar_adapter = calendar_adapter
        self.freebusy_calendar_ids = freebusy_calendar_ids
        self.reminder_send_time = reminder_send_time

    async def prepare_confirmation_summary(
        self,
        *,
        conversation_id: int,
        preferred_visit_date: date,
        preferred_visit_time: time,
        attendee_count: int,
        visit_reason: str,
    ) -> VisitServiceResult:
        return VisitServiceResult(
            response_code="RESP-VISIT-CONFIRM-001",
            state=ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
        )

    async def confirm_appointment(
        self,
        *,
        customer_id: int,
        lead_id: UUID | None,
        conversation_id: int,
        visit_date: date,
        visit_time: time,
        attendee_count: int,
        visit_reason: str,
        customer_confirmation: bool,
        now: datetime,
        request_id: str | None = None,
        simulate_confirmation_message_failure: bool = False,
    ) -> VisitServiceResult:
        if not customer_confirmation:
            return VisitServiceResult(
                response_code="RESP-VISIT-CONFIRM-001",
                state=ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
            )

        available = await self._is_slot_available(visit_date, visit_time, today=now.date())
        if not available:
            return VisitServiceResult(
                response_code="RESP-VISIT-CONFIRM-005",
                state=ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
            )

        try:
            appointment_id = await self._insert_pending_appointment(
                customer_id=customer_id,
                lead_id=lead_id,
                visit_date=visit_date,
                visit_time=visit_time,
                attendee_count=attendee_count,
                visit_reason=visit_reason,
            )
        except IntegrityError:
            return VisitServiceResult(
                response_code="RESP-VISIT-CONFIRM-005",
                state=ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
            )

        event_id = appointment_id.hex
        try:
            await self._create_or_reconcile_event(
                event_id=event_id,
                summary="Visita comercial La Ceiba Club House",
                start=slot_datetime(visit_date, visit_time),
                end=slot_datetime(visit_date, calculate_visit_end_time(visit_time)),
            )
        except CalendarUnavailableError:
            await self._mark_appointment_for_reconciliation(appointment_id)
            return VisitServiceResult(
                response_code="RESP-CALENDAR-ERROR-002",
                state=ConversationState.WAITING_FOR_HUMAN,
                appointment_id=appointment_id,
            )

        await self._confirm_pending_appointment(appointment_id, event_id, visit_date)
        return VisitServiceResult(
            response_code="RESP-VISIT-CONFIRM-003",
            state=ConversationState.APPOINTMENT_CONFIRMED,
            appointment_id=appointment_id,
            external_calendar_id=event_id,
        )

    async def retry_confirmation_message(self, appointment_id: UUID) -> VisitServiceResult:
        return VisitServiceResult(
            response_code="RESP-VISIT-CONFIRM-003",
            state=ConversationState.APPOINTMENT_CONFIRMED,
            appointment_id=appointment_id,
        )

    async def get_visit_reminder(self, appointment_id: UUID) -> VisitReminder:
        async with self.sessionmaker() as session:
            appointment = await session.get(Appointment, appointment_id)
        if appointment is None or appointment.reminder_scheduled_at is None:
            raise ValueError(f"Appointment has no reminder: {appointment_id}")
        return VisitReminder(
            appointment_id=appointment_id,
            scheduled_at=appointment.reminder_scheduled_at,
            response_code="RESP-VISIT-REMINDER-001",
        )

    async def process_due_reminders(self, *, now: datetime) -> None:
        async with self.sessionmaker() as session:
            async with session.begin():
                appointments = await session.scalars(
                    select(Appointment).where(
                        Appointment.reminder_scheduled_at <= now.astimezone(UTC),
                        Appointment.reminder_sent_at.is_(None),
                        Appointment.appointment_status.in_(ACTIVE_APPOINTMENT_STATUSES),
                    )
                )
                for appointment in appointments.all():
                    appointment.reminder_sent_at = now.astimezone(UTC)

    async def count_sent_reminders(self, appointment_id: UUID) -> int:
        async with self.sessionmaker() as session:
            sent = await session.scalar(
                select(func.count(Appointment.appointment_id)).where(
                    Appointment.appointment_id == appointment_id,
                    Appointment.reminder_sent_at.is_not(None),
                )
            )
        return int(sent or 0)

    async def request_reschedule(self, customer_id: int) -> VisitServiceResult:
        appointments = await self._active_appointments_for_customer(customer_id)
        if len(appointments) == 1:
            return VisitServiceResult(
                response_code="RESP-RESCHEDULE-001",
                appointment_id=appointments[0].appointment_id,
            )
        if len(appointments) > 1:
            return VisitServiceResult(response_code="RESP-RESCHEDULE-002")
        return VisitServiceResult(response_code="RESP-RESCHEDULE-006")

    async def reschedule_appointment(
        self,
        *,
        appointment_id: UUID,
        new_date: date,
        new_time: time,
        actor: str,
        now: datetime,
    ) -> VisitServiceResult:
        async with self.sessionmaker() as session:
            appointment = await session.get(Appointment, appointment_id)
            if appointment is None:
                return VisitServiceResult(response_code="RESP-RESCHEDULE-006")
            previous_date = appointment.appointment_date
            previous_time = appointment.start_time

        if not await self._is_slot_available(new_date, new_time, today=now.date()):
            return VisitServiceResult(response_code="RESP-VISIT-CONFIRM-005")

        try:
            await self._update_or_reconcile_event(
                event_id=appointment_id.hex,
                summary="Visita comercial La Ceiba Club House",
                start=slot_datetime(new_date, new_time),
                end=slot_datetime(new_date, calculate_visit_end_time(new_time)),
            )
        except CalendarUnavailableError:
            return VisitServiceResult(response_code="RESP-CALENDAR-ERROR-003")

        try:
            async with self.sessionmaker() as session:
                async with session.begin():
                    appointment = await session.get(Appointment, appointment_id)
                    if appointment is None:
                        return VisitServiceResult(response_code="RESP-RESCHEDULE-006")
                    appointment.appointment_date = new_date
                    appointment.start_time = new_time
                    appointment.end_time = calculate_visit_end_time(new_time)
                    appointment.appointment_status = "RESCHEDULED"
                    appointment.reschedule_count += 1
                    appointment.reminder_scheduled_at = self._reminder_at(new_date)
                    session.add(
                        AppointmentChange(
                            appointment_id=appointment_id,
                            previous_date=previous_date,
                            previous_start_time=previous_time,
                            new_date=new_date,
                            new_start_time=new_time,
                            changed_by_type=actor,
                            changed_by_id=actor,
                        )
                    )
        except IntegrityError:
            return VisitServiceResult(response_code="RESP-VISIT-CONFIRM-005")

        return VisitServiceResult(
            response_code="RESP-RESCHEDULE-004",
            appointment_id=appointment_id,
        )

    async def request_cancellation(self, customer_id: int) -> VisitServiceResult:
        appointments = await self._active_appointments_for_customer(customer_id)
        if not appointments:
            return VisitServiceResult(response_code="RESP-CANCEL-VISIT-005")
        return VisitServiceResult(
            response_code="RESP-CANCEL-VISIT-001",
            appointment_id=appointments[0].appointment_id,
        )

    async def cancel_appointment(
        self,
        *,
        appointment_id: UUID,
        customer_confirmation: bool,
        reason: str,
        now: datetime,
    ) -> VisitServiceResult:
        if not customer_confirmation:
            return VisitServiceResult(response_code="RESP-CANCEL-VISIT-003")

        async with self.sessionmaker() as session:
            appointment = await session.get(Appointment, appointment_id)
            if appointment is None:
                return VisitServiceResult(response_code="RESP-CANCEL-VISIT-005")
            external_calendar_id = appointment.external_calendar_id

        if external_calendar_id is not None:
            try:
                await self.calendar_adapter.delete_event(external_calendar_id)
            except EventNotFoundError:
                pass
            except CalendarUnavailableError:
                async with self.sessionmaker() as session:
                    async with session.begin():
                        appointment = await session.get(Appointment, appointment_id)
                        if appointment is not None:
                            appointment.requires_reconciliation = True
                return VisitServiceResult(
                    response_code="RESP-CALENDAR-ERROR-004",
                    appointment_id=appointment_id,
                )

        async with self.sessionmaker() as session:
            async with session.begin():
                appointment = await session.get(Appointment, appointment_id)
                if appointment is None:
                    return VisitServiceResult(response_code="RESP-CANCEL-VISIT-005")
                appointment.appointment_status = "CANCELLED"
                appointment.cancellation_reason = reason
                appointment.cancelled_at = now.astimezone(UTC)
        return VisitServiceResult(
            response_code="RESP-CANCEL-VISIT-002",
            appointment_id=appointment_id,
        )

    async def _is_slot_available(self, visit_date: date, visit_time: time, *, today: date) -> bool:
        service = AvailabilityService(
            sessionmaker=self.sessionmaker,
            calendar_adapter=self.calendar_adapter,
            freebusy_calendar_ids=self.freebusy_calendar_ids,
        )
        availability = await service.available_slots(visit_date, today=today)
        return visit_time in {slot.start_time for slot in availability.slots}

    async def _insert_pending_appointment(
        self,
        *,
        customer_id: int,
        lead_id: UUID | None,
        visit_date: date,
        visit_time: time,
        attendee_count: int,
        visit_reason: str,
    ) -> UUID:
        async with self.sessionmaker() as session:
            try:
                async with session.begin():
                    appointment = Appointment(
                        customer_id=customer_id,
                        lead_id=lead_id,
                        appointment_date=visit_date,
                        start_time=visit_time,
                        attendee_count=attendee_count,
                        visit_reason=visit_reason,
                        appointment_status="PENDING_CONFIRMATION",
                    )
                    session.add(appointment)
                    await session.flush()
                    return appointment.appointment_id
            except IntegrityError:
                await session.rollback()
                raise

    async def _create_or_reconcile_event(
        self,
        *,
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
    ) -> None:
        try:
            await self.calendar_adapter.create_event(event_id, summary, start, end)
        except AlreadyExistsError:
            return
        except CalendarUnavailableError:
            try:
                await self.calendar_adapter.create_event(event_id, summary, start, end)
            except AlreadyExistsError:
                return
            raise

    async def _update_or_reconcile_event(
        self,
        *,
        event_id: str,
        summary: str,
        start: datetime,
        end: datetime,
    ) -> None:
        try:
            await self.calendar_adapter.update_event(event_id, summary, start, end)
        except EventNotFoundError:
            try:
                await self.calendar_adapter.create_event(event_id, summary, start, end)
            except AlreadyExistsError as create_exc:
                raise CalendarUnavailableError(
                    f"calendar event appeared during reschedule: {event_id}"
                ) from create_exc
            except CalendarUnavailableError:
                raise
            return
        except CalendarUnavailableError:
            await self.calendar_adapter.update_event(event_id, summary, start, end)

    async def _confirm_pending_appointment(
        self,
        appointment_id: UUID,
        external_calendar_id: str,
        visit_date: date,
    ) -> None:
        async with self.sessionmaker() as session:
            async with session.begin():
                appointment = await session.get(Appointment, appointment_id)
                if appointment is None:
                    raise ValueError(f"Appointment not found: {appointment_id}")
                appointment.external_calendar_id = external_calendar_id
                appointment.appointment_status = "CONFIRMED"
                appointment.reminder_scheduled_at = self._reminder_at(visit_date)
                appointment.requires_reconciliation = False

    async def _mark_appointment_for_reconciliation(self, appointment_id: UUID) -> None:
        async with self.sessionmaker() as session:
            async with session.begin():
                appointment = await session.get(Appointment, appointment_id)
                if appointment is not None:
                    appointment.requires_reconciliation = True

    async def _active_appointments_for_customer(self, customer_id: int) -> list[Appointment]:
        async with self.sessionmaker() as session:
            appointments = await session.scalars(
                select(Appointment)
                .where(
                    Appointment.customer_id == customer_id,
                    Appointment.appointment_status.in_(ACTIVE_APPOINTMENT_STATUSES),
                )
                .order_by(Appointment.appointment_date, Appointment.start_time)
            )
            return list(appointments.all())

    def _reminder_at(self, visit_date: date) -> datetime:
        reminder_date = visit_date - timedelta(days=1)
        return datetime.combine(reminder_date, self.reminder_send_time, tzinfo=BOGOTA).astimezone(
            UTC
        )

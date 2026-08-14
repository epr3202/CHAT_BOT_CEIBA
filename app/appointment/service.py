from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
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


@dataclass(frozen=True)
class VisitDateTextResult:
    resolved_date: date | None
    needs_confirmation: bool
    next_state: ConversationState


@dataclass(frozen=True)
class VisitTimeResult:
    accepted: bool
    preferred_visit_time: time | None = None
    response_code: str | None = None


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
    normalized = message_text.strip().casefold()
    if "próximo sábado" in normalized or "proximo sabado" in normalized:
        days_until_saturday = (5 - today.weekday()) % 7
        if days_until_saturday == 0:
            days_until_saturday = 7
        resolved = today + timedelta(days=days_until_saturday)
        return VisitDateTextResult(
            resolved,
            needs_confirmation=require_absolute_confirmation,
            next_state=ConversationState.WAITING_FOR_APPOINTMENT_DATE,
        )
    return VisitDateTextResult(
        None,
        needs_confirmation=True,
        next_state=ConversationState.WAITING_FOR_APPOINTMENT_DATE,
    )


def interpret_visit_time(message_text: str, offered_slots: list[time]) -> VisitTimeResult:
    normalized = message_text.strip().casefold()
    if "2" in normalized and ("tarde" in normalized or "pm" in normalized or "p. m." in normalized):
        return VisitTimeResult(False, response_code="RESP-VISIT-TIME-002")

    for candidate in offered_slots:
        hour_text = str(candidate.hour)
        if hour_text in normalized:
            return VisitTimeResult(True, preferred_visit_time=candidate)
    return VisitTimeResult(False, response_code="RESP-VISIT-TIME-003")


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
            await self._create_or_reconcile_event(
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

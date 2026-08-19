from __future__ import annotations

from datetime import UTC, date, datetime, time
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app import models_registry as _models_registry  # noqa: F401
from app.appointment.models import Appointment
from app.appointment.service import (
    VisitSchedulingService,
    interpret_visit_time,
    resolve_visit_date_text,
)
from app.calendar.adapter import (
    CalendarUnavailableError,
    FakeCalendarAdapter,
    get_calendar_adapter,
)
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.lead.models import Lead

BOGOTA = ZoneInfo("America/Bogota")
TODAY = date(2026, 8, 19)


class _AsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _AppointmentSession:
    def __init__(self, appointment: Appointment | None) -> None:
        self.appointment = appointment

    async def __aenter__(self) -> _AppointmentSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def begin(self) -> _AsyncContext:
        return _AsyncContext()

    async def get(self, model: type[Appointment], appointment_id: object) -> Appointment | None:
        if self.appointment is None or self.appointment.appointment_id != appointment_id:
            return None
        return self.appointment


class _AppointmentSessionmaker:
    def __init__(self, appointment: Appointment | None = None) -> None:
        self.appointment = appointment

    def __call__(self) -> _AppointmentSession:
        return _AppointmentSession(self.appointment)


def visit_service(
    appointment: Appointment | None = None,
    calendar: FakeCalendarAdapter | None = None,
) -> VisitSchedulingService:
    return VisitSchedulingService(
        sessionmaker=_AppointmentSessionmaker(appointment),  # type: ignore[arg-type]
        calendar_adapter=calendar or FakeCalendarAdapter(),
        freebusy_calendar_ids=["visits", "business-main"],
    )


def appointment(
    *,
    appointment_date: date = date(2026, 8, 22),
    start_time: time = time(9),
) -> Appointment:
    return Appointment(
        appointment_id=uuid4(),
        customer_id=1,
        appointment_date=appointment_date,
        start_time=start_time,
        attendee_count=2,
        visit_reason="una boda",
        appointment_status="PENDING_CONFIRMATION",
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("19 de septiembre", date(2026, 9, 19)),
        ("19/09", date(2026, 9, 19)),
        ("19 de septiembre de 2026", date(2026, 9, 19)),
    ],
)
def test_absolute_spanish_dates_are_exact(message: str, expected: date) -> None:
    result = resolve_visit_date_text(
        message,
        today=TODAY,
        require_absolute_confirmation=True,
    )

    assert result.interpretation == "EXACTA"
    assert result.resolved_date == expected
    assert result.needs_confirmation is False


def test_yearless_absolute_date_uses_next_future_occurrence() -> None:
    result = resolve_visit_date_text(
        "5 de enero",
        today=TODAY,
        require_absolute_confirmation=True,
    )

    assert result.interpretation == "EXACTA"
    assert result.resolved_date == date(2027, 1, 5)


def test_explicit_past_date_is_never_resolved_to_the_past() -> None:
    result = resolve_visit_date_text(
        "5 de enero de 2025",
        today=TODAY,
        require_absolute_confirmation=True,
    )

    assert result.interpretation == "NO_INTERPRETABLE"
    assert result.resolved_date is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("mañana", date(2026, 8, 20)),
        ("el próximo sábado", date(2026, 8, 22)),
    ],
)
def test_relative_dates_are_resolved_but_require_confirmation(
    message: str,
    expected: date,
) -> None:
    result = resolve_visit_date_text(
        message,
        today=TODAY,
        require_absolute_confirmation=True,
    )

    assert result.interpretation == "RELATIVA"
    assert result.resolved_date == expected
    assert result.needs_confirmation is True


def test_unrelated_text_is_not_interpretable_as_a_visit_date() -> None:
    result = resolve_visit_date_text(
        "quiero ver el salón bonito",
        today=TODAY,
        require_absolute_confirmation=True,
    )

    assert result.interpretation == "NO_INTERPRETABLE"
    assert result.resolved_date is None


def test_visit_time_accepts_only_a_slot_from_the_current_offer() -> None:
    result = interpret_visit_time("la de las 9", [time(8), time(9), time(11)])

    assert result.interpretation == "OFFERED_SLOT"
    assert result.accepted is True
    assert result.preferred_visit_time == time(9)


def test_valid_visit_time_outside_offer_has_distinct_response() -> None:
    result = interpret_visit_time("a las 10", [time(8), time(9), time(11)])

    assert result.interpretation == "OUTSIDE_OFFER"
    assert result.accepted is False
    assert result.response_code == "RESP-VISIT-TIME-004"


def test_non_interpretable_visit_time_uses_time_003() -> None:
    result = interpret_visit_time("la que sea", [time(8), time(9)])

    assert result.interpretation == "NO_INTERPRETABLE"
    assert result.response_code == "RESP-VISIT-TIME-003"


def test_afternoon_time_keeps_specific_time_002_response() -> None:
    result = interpret_visit_time("a las 2 de la tarde", [time(8), time(9)])

    assert result.interpretation == "OUT_OF_HOURS"
    assert result.response_code == "RESP-VISIT-TIME-002"


@pytest.mark.asyncio
async def test_confirmation_summary_with_event_has_complete_render_variables() -> None:
    result = await visit_service().prepare_confirmation_summary(
        conversation_id=1,
        customer_name="Natalia Pérez",
        preferred_visit_date=date(2026, 9, 19),
        preferred_visit_time=time(9),
        attendee_count=2,
        visit_reason="una boda",
    )

    assert result.response_code == "RESP-VISIT-CONFIRM-001"
    assert result.state == ConversationState.APPOINTMENT_PENDING_CONFIRMATION
    assert result.variables == {
        "visit_date": "19 de septiembre de 2026",
        "visit_time": "09:00",
        "event_type": "una boda",
        "visit_attendee_count": "2",
    }


@pytest.mark.asyncio
async def test_confirmation_summary_without_event_uses_confirm_002() -> None:
    result = await visit_service().prepare_confirmation_summary(
        conversation_id=1,
        customer_name="Natalia Pérez",
        preferred_visit_date=date(2026, 9, 19),
        preferred_visit_time=time(9),
        attendee_count=2,
        visit_reason=None,
    )

    assert result.response_code == "RESP-VISIT-CONFIRM-002"
    assert "event_type" not in result.variables


@pytest.mark.asyncio
async def test_confirmation_summary_rejects_missing_required_name_safely() -> None:
    result = await visit_service().prepare_confirmation_summary(
        conversation_id=1,
        customer_name=None,
        preferred_visit_date=date(2026, 9, 19),
        preferred_visit_time=time(9),
        attendee_count=2,
        visit_reason="una boda",
    )

    assert result.response_code == "RESP-VISIT-CONFIRM-006"
    assert result.state == ConversationState.WAITING_FOR_HUMAN
    assert result.needs_handoff is True


@pytest.mark.asyncio
async def test_reschedule_summary_has_specific_template_state_and_variables() -> None:
    current = appointment()
    result = await visit_service(current).prepare_reschedule_summary(
        appointment_id=current.appointment_id,
        new_date=date(2026, 9, 23),
        new_time=time(10),
    )

    assert result.response_code == "RESP-RESCHEDULE-003"
    assert result.state == ConversationState.APPOINTMENT_PENDING_CONFIRMATION
    assert result.variables == {
        "new_visit_date": "23 de septiembre de 2026",
        "new_visit_time": "10:00",
    }


@pytest.mark.asyncio
async def test_single_active_reschedule_returns_renderable_current_appointment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = appointment()
    service = visit_service()
    monkeypatch.setattr(
        service,
        "_active_appointments_for_customer",
        AsyncMock(return_value=[current]),
    )

    result = await service.request_reschedule(1)

    assert result.response_code == "RESP-RESCHEDULE-001"
    assert result.appointment_id == current.appointment_id
    assert result.variables == {
        "visit_date": "22 de agosto de 2026",
        "visit_time": "09:00",
    }


@pytest.mark.asyncio
async def test_multiple_active_reschedules_require_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = visit_service()
    monkeypatch.setattr(
        service,
        "_active_appointments_for_customer",
        AsyncMock(return_value=[appointment(), appointment(start_time=time(10))]),
    )

    result = await service.request_reschedule(1)

    assert result.response_code == "RESP-RESCHEDULE-002"
    assert result.appointment_id is None
    assert result.needs_handoff is True


@pytest.mark.asyncio
async def test_single_active_cancellation_returns_renderable_current_appointment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = appointment()
    service = visit_service()
    monkeypatch.setattr(
        service,
        "_active_appointments_for_customer",
        AsyncMock(return_value=[current]),
    )

    result = await service.request_cancellation(1)

    assert result.response_code == "RESP-CANCEL-VISIT-001"
    assert result.appointment_id == current.appointment_id
    assert result.variables == {
        "visit_date": "22 de agosto de 2026",
        "visit_time": "09:00",
    }


@pytest.mark.asyncio
async def test_multiple_active_cancellations_never_choose_the_first_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = visit_service()
    monkeypatch.setattr(
        service,
        "_active_appointments_for_customer",
        AsyncMock(return_value=[appointment(), appointment(start_time=time(10))]),
    )

    result = await service.request_cancellation(1)

    assert result.response_code == "RESP-CANCEL-VISIT-005"
    assert result.appointment_id is None
    assert result.needs_handoff is True


@pytest.mark.asyncio
async def test_freebusy_failure_is_distinct_from_an_occupied_confirmation_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = visit_service()
    monkeypatch.setattr(
        service,
        "_is_slot_available",
        AsyncMock(side_effect=CalendarUnavailableError("freebusy unavailable")),
    )
    unavailable = await service.confirm_appointment(
        customer_id=1,
        lead_id=None,
        conversation_id=1,
        visit_date=date(2026, 9, 19),
        visit_time=time(9),
        attendee_count=2,
        visit_reason="una boda",
        customer_confirmation=True,
        now=datetime(2026, 9, 1, 9, tzinfo=BOGOTA),
    )

    monkeypatch.setattr(service, "_is_slot_available", AsyncMock(return_value=False))
    occupied = await service.confirm_appointment(
        customer_id=1,
        lead_id=None,
        conversation_id=1,
        visit_date=date(2026, 9, 19),
        visit_time=time(9),
        attendee_count=2,
        visit_reason="una boda",
        customer_confirmation=True,
        now=datetime(2026, 9, 1, 9, tzinfo=BOGOTA),
    )

    assert unavailable.response_code == "RESP-CALENDAR-ERROR-001"
    assert unavailable.state == ConversationState.WAITING_FOR_HUMAN
    assert unavailable.needs_handoff is True
    assert occupied.response_code == "RESP-VISIT-CONFIRM-005"


@pytest.mark.asyncio
async def test_freebusy_failure_is_distinct_during_reschedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = appointment()
    service = visit_service(current)
    monkeypatch.setattr(
        service,
        "_is_slot_available",
        AsyncMock(side_effect=CalendarUnavailableError("freebusy unavailable")),
    )

    result = await service.reschedule_appointment(
        appointment_id=current.appointment_id,
        new_date=date(2026, 9, 23),
        new_time=time(10),
        actor="CUSTOMER",
        now=datetime(2026, 9, 1, 9, tzinfo=BOGOTA),
    )

    assert result.response_code == "RESP-CALENDAR-ERROR-001"
    assert result.needs_handoff is True
    assert current.appointment_date == date(2026, 8, 22)


@pytest.mark.asyncio
async def test_cancellation_inside_24_hours_is_late_cancel() -> None:
    current = appointment(appointment_date=date(2026, 8, 20), start_time=time(8))
    result = await visit_service(current).cancel_appointment(
        appointment_id=current.appointment_id,
        customer_confirmation=True,
        reason="No puedo asistir",
        now=datetime(2026, 8, 19, 9, 30, tzinfo=BOGOTA),
    )

    assert result.response_code == "RESP-CANCEL-VISIT-002"
    assert current.appointment_status == "LATE_CANCEL"
    assert current.cancelled_at == datetime(2026, 8, 19, 14, 30, tzinfo=UTC)


def test_authorized_schema_surface_exists_without_touching_event_capture() -> None:
    assert "visit_draft" in Conversation.__table__.columns
    assert Lead(lead_status="VISIT_SCHEDULED", customer_id=1, channel="WHATSAPP")


def test_fake_calendar_adapter_is_shared_per_application_configuration() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        META_APP_SECRET="test-secret",
        META_ACCESS_TOKEN="test-token",
        OPENROUTER_API_KEY="test-key",
        CALENDAR_ADAPTER="fake",
        _env_file=None,
    )

    first = get_calendar_adapter(settings)
    second = get_calendar_adapter(settings)

    assert first is second

from __future__ import annotations

import asyncio
import importlib
import importlib.util
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.channel.states import Channel
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.lead.models import Lead
from tests.integration.helpers import (
    cleanup_test_environment,
    reset_test_database,
)

SLICE_MODULES = (
    "app.appointment.models",
    "app.appointment.service",
    "app.calendar.adapter",
    "app.scheduling.availability",
)

pytestmark = pytest.mark.xfail(
    condition=not all(importlib.util.find_spec(module) for module in SLICE_MODULES),
    reason="Slice 2B-1 agenda domain is intentionally not implemented before T2-T10.",
    strict=False,
)

BOGOTA = ZoneInfo("America/Bogota")
TODAY = date(2026, 8, 14)
VALID_TUESDAY = date(2026, 8, 18)
VALID_WEDNESDAY = date(2026, 8, 19)

VISIT_TEMPLATE_CODES = (
    "RESP-VISIT-004",
    "RESP-VISIT-005",
    "RESP-VISIT-006",
    "RESP-VISIT-007",
    "RESP-VISIT-008",
    "RESP-VISIT-009",
    "RESP-VISIT-TIME-001",
    "RESP-VISIT-TIME-002",
    "RESP-VISIT-DATA-002",
    "RESP-VISIT-CONFIRM-001",
    "RESP-VISIT-CONFIRM-003",
    "RESP-VISIT-CONFIRM-005",
    "RESP-RESCHEDULE-001",
    "RESP-RESCHEDULE-002",
    "RESP-CANCEL-VISIT-001",
    "RESP-CANCEL-VISIT-002",
    "RESP-CALENDAR-ERROR-001",
    "RESP-CALENDAR-ERROR-002",
    "RESP-CALENDAR-ERROR-003",
    "RESP-CALENDAR-ERROR-004",
)


@dataclass(frozen=True)
class CustomerContext:
    customer_id: int
    conversation_id: int
    lead_id: Any


def slice_module(name: str) -> Any:
    return importlib.import_module(name)


def availability_module() -> Any:
    return slice_module("app.scheduling.availability")


def appointment_models() -> Any:
    return slice_module("app.appointment.models")


def appointment_service_module() -> Any:
    return slice_module("app.appointment.service")


def calendar_module() -> Any:
    return slice_module("app.calendar.adapter")


def at_bogota(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=BOGOTA)


def approved_entry(code: str) -> KnowledgeEntry:
    return KnowledgeEntry(
        code=code,
        category="Agenda de visitas",
        question_summary=code,
        answer_template=f"{code} {{visit_date}} {{visit_time}} {{appointment_options}}",
        allowed_variables=["visit_date", "visit_time", "appointment_options"],
        version=1,
        status="APPROVED",
    )


async def prepare_database() -> Any:
    sessionmaker = await reset_test_database()
    async with sessionmaker() as session:
        async with session.begin():
            session.add(KnowledgeEntry(
                code="RESP-AI-ERROR-001",
                category="Fallback",
                question_summary="Error",
                answer_template="Error seguro.",
                allowed_variables=[],
                version=1,
                status="APPROVED",
            ))
            session.add_all(approved_entry(code) for code in VISIT_TEMPLATE_CODES)
    return sessionmaker


async def customer_context(sessionmaker: Any, phone: str | None = None) -> CustomerContext:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=phone or f"+573{uuid4().int % 10_000_0000:08d}")
            session.add(customer)
            await session.flush()
            lead = Lead(customer_id=customer.id, channel=Channel.WHATSAPP, lead_status="QUALIFYING")
            session.add(lead)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
                active_lead_id=lead.lead_id,
            )
            session.add(conversation)
            await session.flush()
            return CustomerContext(customer.id, conversation.id, lead.lead_id)


async def add_holiday(sessionmaker: Any, holiday_date: date, name: str = "Festivo") -> None:
    models = appointment_models()
    async with sessionmaker() as session:
        async with session.begin():
            session.add(models.Holiday(holiday_date=holiday_date, name=name, source="SEEDED"))


async def add_blocked_date(sessionmaker: Any, blocked_date: date) -> None:
    models = appointment_models()
    async with sessionmaker() as session:
        async with session.begin():
            session.add(
                models.BlockedDate(
                    blocked_date=blocked_date,
                    reason="Mantenimiento",
                    actor="SYSTEM",
                )
            )


async def add_appointment(
    sessionmaker: Any,
    appointment_date: date = VALID_TUESDAY,
    start: time = time(10, 0),
    status: str = "CONFIRMED",
    customer_id: int | None = None,
    lead_id: Any | None = None,
    external_calendar_id: str | None = None,
) -> Any:
    models = appointment_models()
    if customer_id is None:
        context = await customer_context(sessionmaker)
        customer_id = context.customer_id
        lead_id = context.lead_id

    appointment = models.Appointment(
        customer_id=customer_id,
        lead_id=lead_id,
        appointment_date=appointment_date,
        start_time=start,
        timezone="America/Bogota",
        attendee_count=2,
        visit_reason="wedding",
        appointment_status=status,
        external_calendar_id=external_calendar_id or f"event-{uuid4().hex}",
    )
    async with sessionmaker() as session:
        async with session.begin():
            session.add(appointment)
            await session.flush()
            return appointment


async def availability_service(sessionmaker: Any, fake: Any | None = None) -> Any:
    availability = availability_module()
    calendar = calendar_module()
    return availability.AvailabilityService(
        sessionmaker=sessionmaker,
        calendar_adapter=fake or calendar.FakeCalendarAdapter(),
        freebusy_calendar_ids=["write-calendar", "business-main"],
    )


async def visit_service(sessionmaker: Any, fake: Any | None = None) -> Any:
    service_module = appointment_service_module()
    calendar = calendar_module()
    return service_module.VisitSchedulingService(
        sessionmaker=sessionmaker,
        calendar_adapter=fake or calendar.FakeCalendarAdapter(),
        freebusy_calendar_ids=["write-calendar", "business-main"],
    )


@pytest.fixture(autouse=True)
async def cleanup_settings() -> Any:
    yield
    await cleanup_test_environment()


def test_tc_agd_001_lunes_rechazado_con_resp_visit_006() -> None:
    availability = availability_module()
    decision = availability.validate_visit_date(
        date(2026, 8, 17), today=TODAY, holidays=set(), blocked_dates=set()
    )
    assert decision.accepted is False
    assert decision.response_code == "RESP-VISIT-006"


def test_tc_agd_002_domingo_rechazado_con_resp_visit_006() -> None:
    availability = availability_module()
    decision = availability.validate_visit_date(
        date(2026, 8, 16), today=TODAY, holidays=set(), blocked_dates=set()
    )
    assert decision.accepted is False
    assert decision.response_code == "RESP-VISIT-006"


def test_tc_agd_003_festivo_colombiano_rechazado_con_resp_visit_007() -> None:
    availability = availability_module()
    holiday = date(2026, 8, 18)
    decision = availability.validate_visit_date(
        holiday, today=TODAY, holidays={holiday}, blocked_dates=set()
    )
    assert decision.accepted is False
    assert decision.response_code == "RESP-VISIT-007"


def test_tc_agd_004_fecha_bloqueada_rechazada_con_resp_visit_008() -> None:
    availability = availability_module()
    blocked = date(2026, 8, 18)
    decision = availability.validate_visit_date(
        blocked, today=TODAY, holidays=set(), blocked_dates={blocked}
    )
    assert decision.accepted is False
    assert decision.response_code == "RESP-VISIT-008"


def test_tc_agd_005_mismo_dia_rechazado_con_resp_visit_004() -> None:
    availability = availability_module()
    decision = availability.validate_visit_date(
        TODAY, today=TODAY, holidays=set(), blocked_dates=set()
    )
    assert decision.accepted is False
    assert decision.response_code == "RESP-VISIT-004"


def test_tc_agd_006_dia_siguiente_rechazado_con_resp_visit_005() -> None:
    availability = availability_module()
    decision = availability.validate_visit_date(
        TODAY + timedelta(days=1), today=TODAY, holidays=set(), blocked_dates=set()
    )
    assert decision.accepted is False
    assert decision.response_code == "RESP-VISIT-005"


def test_tc_agd_007_anticipacion_dos_dias_rechazada() -> None:
    availability = availability_module()
    decision = availability.validate_visit_date(
        date(2026, 8, 18),
        today=date(2026, 8, 16),
        holidays=set(),
        blocked_dates=set(),
    )
    assert decision.accepted is False
    assert decision.response_code == "RESP-VISIT-004"


async def test_tc_agd_008_anticipacion_exacta_tres_dias_consulta_slots() -> None:
    sessionmaker = await prepare_database()
    service = await availability_service(sessionmaker)
    result = await service.available_slots(VALID_TUESDAY, today=date(2026, 8, 15))
    assert result.response_code == "RESP-VISIT-TIME-001"
    assert result.slots


async def test_tc_agd_009_seed_contiene_festivo_emiliani_trasladado() -> None:
    seed = slice_module("scripts.seed_holidays")
    sessionmaker = await prepare_database()
    await seed.seed_colombian_holidays(sessionmaker, years=[2026])
    models = appointment_models()
    async with sessionmaker() as session:
        shifted = await session.scalar(
            select(models.Holiday).where(models.Holiday.holiday_date == date(2026, 8, 17))
        )
        original = await session.scalar(
            select(models.Holiday).where(models.Holiday.holiday_date == date(2026, 8, 15))
        )
    assert shifted is not None
    assert shifted.source == "SEEDED"
    assert original is None


async def test_tc_agd_010_dia_habil_ofrece_cuatro_slots_de_45_minutos() -> None:
    sessionmaker = await prepare_database()
    service = await availability_service(sessionmaker)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert [slot.start_time for slot in result.slots] == [
        time(8, 0),
        time(9, 0),
        time(10, 0),
        time(11, 0),
    ]
    assert all(
        slot.end_time
        == (datetime.combine(date.min, slot.start_time) + timedelta(minutes=45)).time()
        for slot in result.slots
    )


async def test_tc_agd_011_cita_local_activa_excluye_slot_aunque_freebusy_vacio() -> None:
    sessionmaker = await prepare_database()
    await add_appointment(sessionmaker, start=time(10, 0), status="CONFIRMED")
    service = await availability_service(sessionmaker)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert time(10, 0) not in [slot.start_time for slot in result.slots]


async def test_tc_agd_012_cita_cancelled_no_ocupa_slot() -> None:
    sessionmaker = await prepare_database()
    await add_appointment(sessionmaker, start=time(10, 0), status="CANCELLED")
    service = await availability_service(sessionmaker)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert time(10, 0) in [slot.start_time for slot in result.slots]


async def test_tc_agd_013_cuatro_citas_activas_dia_completo() -> None:
    sessionmaker = await prepare_database()
    for hour in (8, 9, 10, 11):
        await add_appointment(sessionmaker, start=time(hour, 0), status="CONFIRMED")
    service = await availability_service(sessionmaker)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert result.slots == []
    assert result.response_code == "RESP-VISIT-009"


async def test_tc_agd_014_freebusy_0900_0930_excluye_slot_9() -> None:
    sessionmaker = await prepare_database()
    calendar = calendar_module()
    fake = calendar.FakeCalendarAdapter(
        busy_by_calendar={
            "write-calendar": [
                calendar.BusyInterval(at_bogota(VALID_TUESDAY, 9), at_bogota(VALID_TUESDAY, 9, 30))
            ]
        }
    )
    service = await availability_service(sessionmaker, fake)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert [slot.start_time for slot in result.slots] == [time(8), time(10), time(11)]


async def test_tc_agd_015_freebusy_0830_1030_excluye_8_9_10() -> None:
    sessionmaker = await prepare_database()
    calendar = calendar_module()
    fake = calendar.FakeCalendarAdapter(
        busy_by_calendar={
            "write-calendar": [
                calendar.BusyInterval(
                    at_bogota(VALID_TUESDAY, 8, 30),
                    at_bogota(VALID_TUESDAY, 10, 30),
                )
            ]
        }
    )
    service = await availability_service(sessionmaker, fake)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert [slot.start_time for slot in result.slots] == [time(11)]


async def test_tc_agd_016_freebusy_termina_exactamente_en_inicio_no_ocupa() -> None:
    sessionmaker = await prepare_database()
    calendar = calendar_module()
    fake = calendar.FakeCalendarAdapter(
        busy_by_calendar={
            "write-calendar": [
                calendar.BusyInterval(at_bogota(VALID_TUESDAY, 8), at_bogota(VALID_TUESDAY, 9))
            ]
        }
    )
    service = await availability_service(sessionmaker, fake)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert time(9) in [slot.start_time for slot in result.slots]


async def test_tc_agd_017_freebusy_multi_calendario_une_intervalos() -> None:
    sessionmaker = await prepare_database()
    calendar = calendar_module()
    fake = calendar.FakeCalendarAdapter(
        busy_by_calendar={
            "business-main": [
                calendar.BusyInterval(
                    at_bogota(VALID_TUESDAY, 11),
                    at_bogota(VALID_TUESDAY, 11, 30),
                )
            ]
        }
    )
    service = await availability_service(sessionmaker, fake)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY)
    assert time(11) not in [slot.start_time for slot in result.slots]


async def test_tc_agd_018_freebusy_error_no_inventa_slots_y_registra_revision() -> None:
    sessionmaker = await prepare_database()
    calendar = calendar_module()
    fake = calendar.FakeCalendarAdapter(raise_on={"query"})
    service = await availability_service(sessionmaker, fake)
    result = await service.available_slots(VALID_TUESDAY, today=TODAY, request_id="tc-calendar-001")
    assert result.slots == []
    assert result.response_code == "RESP-CALENDAR-ERROR-001"
    assert result.requires_review is True


def test_tc_agd_019_fecha_relativa_se_confirma_en_absoluto_antes_de_slots() -> None:
    service_module = appointment_service_module()
    result = service_module.resolve_visit_date_text(
        "el próximo sábado",
        today=TODAY,
        require_absolute_confirmation=True,
    )
    assert result.needs_confirmation is True
    assert result.resolved_date == date(2026, 8, 15)
    assert result.next_state == ConversationState.WAITING_FOR_APPOINTMENT_DATE


def test_tc_agd_020_hora_tarde_rechazada_con_resp_visit_time_002() -> None:
    service_module = appointment_service_module()
    result = service_module.interpret_visit_time("a las 2 de la tarde", offered_slots=[])
    assert result.accepted is False
    assert result.response_code == "RESP-VISIT-TIME-002"


def test_tc_agd_021_seleccion_contextual_la_de_las_9() -> None:
    service_module = appointment_service_module()
    result = service_module.interpret_visit_time(
        "la de las 9",
        offered_slots=[time(8), time(9), time(11)],
    )
    assert result.accepted is True
    assert result.preferred_visit_time == time(9)


async def test_tc_agd_022_cuatro_asistentes_rechazo_y_excepcion_es_handoff() -> None:
    service_module = appointment_service_module()
    rejected = service_module.validate_visit_attendees(4, exception_requested=False)
    exception = service_module.validate_visit_attendees(4, exception_requested=True)
    assert rejected.accepted is False
    assert rejected.response_code == "RESP-VISIT-DATA-002"
    assert exception.needs_handoff is True


async def test_tc_agd_023_resumen_previo_a_confirmacion() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    service = await visit_service(sessionmaker)
    result = await service.prepare_confirmation_summary(
        conversation_id=context.conversation_id,
        preferred_visit_date=VALID_TUESDAY,
        preferred_visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
    )
    assert result.response_code == "RESP-VISIT-CONFIRM-001"
    assert result.state == ConversationState.APPOINTMENT_PENDING_CONFIRMATION


async def test_tc_agd_024_confirmacion_feliz_dos_transacciones_y_recordatorio() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    service = await visit_service(sessionmaker)
    result = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
        request_id="tc-agd-024",
    )
    models = appointment_models()
    async with sessionmaker() as session:
        appointment = await session.get(models.Appointment, result.appointment_id)
    assert appointment.appointment_status == "CONFIRMED"
    assert appointment.external_calendar_id == appointment.appointment_id.hex
    assert appointment.reminder_scheduled_at == at_bogota(date(2026, 8, 17), 9).astimezone(UTC)
    assert result.response_code == "RESP-VISIT-CONFIRM-003"


async def test_tc_agd_025_segunda_validacion_detecta_freebusy_nuevo() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    calendar = calendar_module()
    fake = calendar.FakeCalendarAdapter()
    service = await visit_service(sessionmaker, fake)
    fake.add_busy("business-main", at_bogota(VALID_TUESDAY, 9), at_bogota(VALID_TUESDAY, 9, 45))
    result = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
    )
    assert result.response_code == "RESP-VISIT-CONFIRM-005"
    assert result.state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION


async def test_tc_agd_026_confirmaciones_concurrentes_un_solo_slot_activo() -> None:
    sessionmaker = await prepare_database()
    first = await customer_context(sessionmaker)
    second = await customer_context(sessionmaker)
    service = await visit_service(sessionmaker)
    common = {
        "visit_date": VALID_TUESDAY,
        "visit_time": time(9),
        "attendee_count": 2,
        "visit_reason": "boda",
        "customer_confirmation": True,
        "now": at_bogota(date(2026, 8, 14), 9),
    }
    results = await asyncio.gather(
        service.confirm_appointment(
            customer_id=first.customer_id,
            lead_id=first.lead_id,
            conversation_id=first.conversation_id,
            **common,
        ),
        service.confirm_appointment(
            customer_id=second.customer_id,
            lead_id=second.lead_id,
            conversation_id=second.conversation_id,
            **common,
        ),
        return_exceptions=True,
    )
    successful_results = [
        result
        for result in results
        if getattr(result, "response_code", None) == "RESP-VISIT-CONFIRM-003"
    ]
    assert len(successful_results) == 1
    models = appointment_models()
    async with sessionmaker() as session:
        active_count = await session.scalar(
            select(func.count(models.Appointment.appointment_id)).where(
                models.Appointment.appointment_date == VALID_TUESDAY,
                models.Appointment.start_time == time(9),
                models.Appointment.appointment_status.in_(
                    ("PENDING_CONFIRMATION", "CONFIRMED", "RESCHEDULED")
                ),
            )
        )
    assert active_count == 1


async def test_tc_agd_027_adapter_falla_crear_deja_pending_y_error_seguro() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    calendar = calendar_module()
    service = await visit_service(sessionmaker, calendar.FakeCalendarAdapter(raise_on={"create"}))
    result = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
    )
    models = appointment_models()
    async with sessionmaker() as session:
        appointment = await session.get(models.Appointment, result.appointment_id)
    assert appointment.appointment_status == "PENDING_CONFIRMATION"
    assert appointment.external_calendar_id is None
    assert result.response_code == "RESP-CALENDAR-ERROR-002"


async def test_tc_agd_028_timeout_tras_crear_reintento_idempotente_confirma() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    calendar = calendar_module()
    service = await visit_service(
        sessionmaker,
        calendar.FakeCalendarAdapter(timeout_after_create=True),
    )
    result = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
    )
    assert result.response_code == "RESP-VISIT-CONFIRM-003"
    assert result.external_calendar_id == result.appointment_id.hex


async def test_tc_agd_029_fallo_mensaje_confirmacion_no_crea_otra_cita() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    service = await visit_service(sessionmaker)
    first = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
        simulate_confirmation_message_failure=True,
    )
    second = await service.retry_confirmation_message(first.appointment_id)
    models = appointment_models()
    async with sessionmaker() as session:
        count = await session.scalar(select(func.count(models.Appointment.appointment_id)))
    assert second.response_code == "RESP-VISIT-CONFIRM-003"
    assert count == 1


async def test_tc_agd_030_cita_confirmada_persiste_timezone_y_end_calculado() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    service = await visit_service(sessionmaker)
    result = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(11),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
    )
    models = appointment_models()
    async with sessionmaker() as session:
        appointment = await session.get(models.Appointment, result.appointment_id)
    assert appointment.timezone == "America/Bogota"
    assert appointment.end_time == time(11, 45)


async def test_tc_agd_031_recordatorio_programado_un_dia_antes() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    service = await visit_service(sessionmaker)
    result = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
    )
    reminder = await service.get_visit_reminder(result.appointment_id)
    assert reminder.scheduled_at == at_bogota(date(2026, 8, 17), 9).astimezone(UTC)
    assert reminder.response_code.startswith("RESP-VISIT-REMINDER")


async def test_tc_agd_032_reintento_worker_envia_un_recordatorio_logico() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    service = await visit_service(sessionmaker)
    result = await service.confirm_appointment(
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        conversation_id=context.conversation_id,
        visit_date=VALID_TUESDAY,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="boda",
        customer_confirmation=True,
        now=at_bogota(date(2026, 8, 14), 9),
    )
    await service.process_due_reminders(now=at_bogota(date(2026, 8, 17), 9))
    await service.process_due_reminders(now=at_bogota(date(2026, 8, 17), 9))
    assert await service.count_sent_reminders(result.appointment_id) == 1


async def test_tc_agd_033_una_cita_activa_pide_cambio_identifica_actual() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    appointment = await add_appointment(
        sessionmaker,
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        start=time(9),
    )
    service = await visit_service(sessionmaker)
    result = await service.request_reschedule(context.customer_id)
    assert result.appointment_id == appointment.appointment_id
    assert result.response_code == "RESP-RESCHEDULE-001"


async def test_tc_agd_034_varias_citas_activas_pide_identificar() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    await add_appointment(
        sessionmaker,
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        start=time(9),
    )
    await add_appointment(
        sessionmaker,
        appointment_date=VALID_WEDNESDAY,
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        start=time(10),
    )
    service = await visit_service(sessionmaker)
    result = await service.request_reschedule(context.customer_id)
    assert result.response_code == "RESP-RESCHEDULE-002"


async def test_tc_agd_035_reprogramacion_adapter_falla_original_intacta() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    appointment = await add_appointment(
        sessionmaker,
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        start=time(9),
    )
    calendar = calendar_module()
    service = await visit_service(sessionmaker, calendar.FakeCalendarAdapter(raise_on={"create"}))
    result = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=VALID_WEDNESDAY,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(date(2026, 8, 14), 9),
    )
    models = appointment_models()
    async with sessionmaker() as session:
        unchanged = await session.get(models.Appointment, appointment.appointment_id)
    assert result.response_code == "RESP-CALENDAR-ERROR-003"
    assert unchanged.appointment_date == VALID_TUESDAY
    assert unchanged.start_time == time(9)


async def test_tc_agd_036_reprogramacion_exitosa_append_only_e_incrementa() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    appointment = await add_appointment(
        sessionmaker,
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        start=time(9),
    )
    service = await visit_service(sessionmaker)
    result = await service.reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=VALID_WEDNESDAY,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(date(2026, 8, 14), 9),
    )
    models = appointment_models()
    async with sessionmaker() as session:
        updated = await session.get(models.Appointment, appointment.appointment_id)
        changes = (
            await session.scalars(
                select(models.AppointmentChange).where(
                    models.AppointmentChange.appointment_id == appointment.appointment_id
                )
            )
        ).all()
    assert result.response_code == "RESP-RESCHEDULE-004"
    assert updated.reschedule_count == 1
    assert len(changes) == 1
    assert changes[0].previous_date == VALID_TUESDAY
    assert changes[0].new_date == VALID_WEDNESDAY


async def test_tc_agd_037_cancelacion_con_confirmacion_elimina_evento() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    appointment = await add_appointment(
        sessionmaker,
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        start=time(9),
    )
    service = await visit_service(sessionmaker)
    prompt = await service.request_cancellation(context.customer_id)
    result = await service.cancel_appointment(
        appointment_id=appointment.appointment_id,
        customer_confirmation=True,
        reason="No puedo asistir",
        now=at_bogota(date(2026, 8, 14), 9),
    )
    models = appointment_models()
    async with sessionmaker() as session:
        cancelled = await session.get(models.Appointment, appointment.appointment_id)
    assert prompt.response_code == "RESP-CANCEL-VISIT-001"
    assert result.response_code == "RESP-CANCEL-VISIT-002"
    assert cancelled.appointment_status == "CANCELLED"


async def test_tc_agd_038_fallo_adapter_cancelar_pendiente_reconciliacion() -> None:
    sessionmaker = await prepare_database()
    context = await customer_context(sessionmaker)
    appointment = await add_appointment(
        sessionmaker,
        customer_id=context.customer_id,
        lead_id=context.lead_id,
        start=time(9),
    )
    calendar = calendar_module()
    service = await visit_service(sessionmaker, calendar.FakeCalendarAdapter(raise_on={"delete"}))
    result = await service.cancel_appointment(
        appointment_id=appointment.appointment_id,
        customer_confirmation=True,
        reason="No puedo asistir",
        now=at_bogota(date(2026, 8, 14), 9),
    )
    models = appointment_models()
    async with sessionmaker() as session:
        appointment_after_error = await session.get(models.Appointment, appointment.appointment_id)
    assert result.response_code == "RESP-CALENDAR-ERROR-004"
    assert appointment_after_error.appointment_status != "CANCELLED"
    assert appointment_after_error.requires_reconciliation is True

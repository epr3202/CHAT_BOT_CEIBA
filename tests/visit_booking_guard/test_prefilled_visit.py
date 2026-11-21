from decimal import Decimal

from app.admin.conversation_reset import reset_conversation_by_phone
from app.appointment.models import Appointment
from app.audit.models import AuditEvent
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from tests.clock import FreezeAppClock
from tests.visit_booking_guard.helpers import PHONE, Harness

VISIT_FORM = (
    "Hola, equipo de La Ceiba! 💍 Quisiera solicitar una visita para conocer el lugar y "
    "conversar sobre nuestra boda. Nombre: Luna Ejemplo Correo: luna@example.org "
    "Visita solicitada: jueves, 29 de octubre de 2026 Hora: 3:13 p. m. (Colombia) "
    "Fecha estimada de la boda: no se Invitados: Menos de 50 Inversión contemplada (COP): "
    "Entre $15 y $20 millones Nos gustaría conocer o resolver: Lo conversaremos durante la "
    "visita. ¿Nos confirman si este horario está disponible? ¡Muchas gracias!"
)


async def schedule_from_form(harness: Harness) -> list[str]:
    codes = []
    for message, intent in (
        (VISIT_FORM, "SCHEDULE_VISIT"),
        ("9 am", "UNKNOWN"),
        ("2", "UNKNOWN"),
        ("Si", "UNKNOWN"),
    ):
        await harness.send(message, intent=intent)
        await harness.assert_completed()
        codes.extend(harness.codes)
    return codes


async def test_visit_form_skips_name_and_reason_questions(harness: Harness) -> None:
    codes = await schedule_from_form(harness)
    assert "RESP-CUSTOMER-001" not in codes
    assert "RESP-VISIT-DATA-003" not in codes
    appointments = await harness.rows(Appointment)
    assert len(appointments) == 1
    assert appointments[0].visit_reason == "Boda. Lo conversaremos durante la visita."
    customer = (await harness.rows(Customer))[0]
    assert (customer.full_name, customer.email) == ("Luna Ejemplo", "luna@example.org")
    captured = [a for a in await harness.rows(AuditEvent) if a.action == "CUSTOMER_EMAIL_CAPTURED"]
    assert len(captured) == 1


async def test_visit_form_details_are_stored_and_written_to_calendar(harness: Harness) -> None:
    await schedule_from_form(harness)
    lead = (await harness.rows(Lead))[0]
    assert lead.estimated_budget == Decimal("15000000")
    event = (await harness.rows(Event))[0]
    assert (event.guest_count_min, event.guest_count_max) == (1, 49)
    assert "Fecha estimada de la boda: no se" in event.special_requests

    appointment = (await harness.rows(Appointment))[0]
    description = (await harness.calendar.get_event(appointment.appointment_id.hex)).description
    assert "Nombre del cliente: Luna Ejemplo" in description
    assert "Correo: luna@example.org" in description
    assert "Invitados: Menos de 50" in description
    assert "Inversión contemplada (COP): Entre $15 y $20 millones" in description
    assert "Fecha estimada de la boda: no se" in description


async def test_conversation_reset_clears_captured_email(harness: Harness) -> None:
    await schedule_from_form(harness)
    async with harness.db.begin() as session:
        await reset_conversation_by_phone(
            session,
            raw_phone_number=PHONE,
            dry_run=False,
            actor="admin:test",
            reason="Prueba de reinicio",
            request_id="reset-email",
        )
    customer = (await harness.rows(Customer))[0]
    assert (customer.full_name, customer.email) == (None, None)


async def test_past_visit_keeps_event_unknown_and_known_customer(
    harness: Harness, freeze_app_clock: FreezeAppClock
) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    freeze_app_clock(datetime(2026, 11, 3, 19, 8, tzinfo=ZoneInfo("America/Bogota")))
    await harness.send(VISIT_FORM)
    await harness.assert_completed()
    assert harness.codes[-1] == "RESP-DATE-PAST-001"
    assert not harness.classifier_calls
    assert not await harness.rows(Appointment)
    event = (await harness.rows(Event))[0]
    assert event.event_date is None and event.guest_count_max == 49
    assert (await harness.rows(Customer))[0].email == "luna@example.org"


async def test_wedding_date_then_too_early_then_only_available_times(
    harness: Harness, freeze_app_clock: FreezeAppClock
) -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.calendar.adapter import BusyInterval

    zone = ZoneInfo("America/Bogota")
    freeze_app_clock(datetime(2026, 11, 3, 19, 8, tzinfo=zone))
    await harness.send(VISIT_FORM)
    await harness.assert_completed()
    assert harness.codes[-1] == "RESP-DATE-PAST-001"
    assert not harness.classifier_calls
    await harness.send("5 de noviembre de 2026")
    await harness.assert_completed()
    assert harness.codes[-1] == "RESP-VISIT-004"
    start = datetime(2026, 11, 6, 8, tzinfo=zone)
    harness.calendar.busy_by_calendar["business-main"] = [
        BusyInterval(start, start + timedelta(hours=4))
    ]
    await harness.send("6 de noviembre de 2026 a las 15:13")
    await harness.assert_completed()
    assert harness.codes[-1] == "RESP-VISIT-009"
    start += timedelta(days=1)
    harness.calendar.busy_by_calendar["business-main"] = [
        BusyInterval(start, start + timedelta(hours=3))
    ]
    await harness.send("7 de noviembre de 2026 a las 15:13")
    await harness.assert_completed()
    assert (await harness.conversation()).visit_draft["offered_slots"] == ["11:00"]
    await harness.send("15:13")
    await harness.assert_completed()
    assert harness.codes[-1] == "RESP-VISIT-TIME-001"
    assert "11:00" in (await harness.bodies())[-1] and "9:00" not in (await harness.bodies())[-1]
    for value in ("11 am", "2", "sí"):
        await harness.send(value)
        await harness.assert_completed()
    (appointment,) = await harness.rows(Appointment)
    (event,) = await harness.rows(Event)
    assert event.event_type == "WEDDING" and event.event_date_type == "UNKNOWN"
    assert appointment.attendee_count == 2
    assert "boda" in appointment.visit_reason.casefold()
    assert (await harness.calendar.get_event(appointment.appointment_id.hex)).description.count(
        "Menos de 50"
    ) == 1

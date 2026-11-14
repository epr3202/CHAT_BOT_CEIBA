from decimal import Decimal

from app.admin.conversation_reset import reset_conversation_by_phone
from app.appointment.models import Appointment
from app.audit.models import AuditEvent
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from tests.visit_booking_guard.helpers import PHONE

VISIT_FORM = (
    "Hola, equipo de La Ceiba! 💍 Quisiera solicitar una visita para conocer el lugar y "
    "conversar sobre nuestra boda. Nombre: Prana Barreto Correo: prana51@hotmail.com "
    "Visita solicitada: jueves, 29 de octubre de 2026 Hora: 3:13 p. m. (Colombia) "
    "Fecha estimada de la boda: no se Invitados: Menos de 50 Inversión contemplada (COP): "
    "Entre $15 y $20 millones Nos gustaría conocer o resolver: Lo conversaremos durante la "
    "visita. ¿Nos confirman si este horario está disponible? ¡Muchas gracias!"
)


async def schedule_from_form(harness):
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


async def test_visit_form_skips_name_and_reason_questions(harness):
    codes = await schedule_from_form(harness)
    assert "RESP-CUSTOMER-001" not in codes
    assert "RESP-VISIT-DATA-003" not in codes
    appointments = await harness.rows(Appointment)
    assert len(appointments) == 1
    assert appointments[0].visit_reason == "Lo conversaremos durante la visita."
    customer = (await harness.rows(Customer))[0]
    assert (customer.full_name, customer.email) == ("Prana Barreto", "prana51@hotmail.com")
    captured = [a for a in await harness.rows(AuditEvent) if a.action == "CUSTOMER_EMAIL_CAPTURED"]
    assert len(captured) == 1


async def test_visit_form_details_are_stored_and_written_to_calendar(harness):
    await schedule_from_form(harness)
    lead = (await harness.rows(Lead))[0]
    assert lead.estimated_budget == Decimal("15000000")
    event = (await harness.rows(Event))[0]
    assert (event.guest_count_min, event.guest_count_max) == (1, 50)
    assert "Fecha estimada de la boda: no se" in event.special_requests

    appointment = (await harness.rows(Appointment))[0]
    description = (await harness.calendar.get_event(appointment.appointment_id.hex)).description
    assert "Nombre del cliente: Prana Barreto" in description
    assert "Correo: prana51@hotmail.com" in description
    assert "Invitados: Menos de 50" in description
    assert "Inversión contemplada (COP): Entre $15 y $20 millones" in description
    assert "Fecha estimada de la boda: no se" in description


async def test_conversation_reset_clears_captured_email(harness):
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

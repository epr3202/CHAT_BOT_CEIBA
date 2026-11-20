import pytest

from app.audit.models import AuditEvent
from app.config.settings import get_settings
from app.customer.models import Customer
from app.event.models import Event, EventServiceRequest
from app.notifications.models import NotificationRecipient, StaffOutbox
from app.reservation.models import Reservation
from app.reservation.settlement import sync_reservation_calendar
from tests.booking_conversation.helpers import code
from tests.visit_booking_guard.helpers import Harness

EXPERIENCE_FORM = (
    "Hola, La Ceiba. Soy luna y quiero consultar disponibilidad para esta experiencia: "
    "Romance entre Copas · 2 personas Plan base: $400.000 COP Detalles adicionales: "
    "• Violín en vivo: $300.000 COP Subtotal definido: $700.000 COP Fecha deseada: "
    "31 de octubre de 2026 Horario preferido: Noche (por confirmar) Ocasión: Aniversario "
    "¿Me confirman disponibilidad, horario, valor final y condiciones para reservar?"
)


async def converse(harness: Harness, *messages: str) -> list[str]:
    codes = []
    for message in messages:
        await harness.send(message)
        await harness.assert_completed()
        codes.extend(harness.codes)
    return codes


async def test_experience_form_never_asks_for_the_name_it_already_has(harness: Harness) -> None:
    codes = await converse(harness, EXPERIENCE_FORM, "7 pm", "sí")
    assert "RESP-CUSTOMER-001" not in codes
    assert codes[-1] == code("PAYMENT")
    customers = await harness.rows(Customer)
    assert [c.full_name for c in customers] == ["Luna"]
    reservations = await harness.rows(Reservation)
    assert len(reservations) == 1 and reservations[0].status == "PAYMENT_PENDING"
    assert not harness.classifier_calls


async def test_experience_form_name_replaces_previous_name_with_audit(harness: Harness) -> None:
    await harness.seed(full_name="Ana")
    await converse(harness, EXPERIENCE_FORM)
    assert [c.full_name for c in await harness.rows(Customer)] == ["Luna"]
    captured = [a for a in await harness.rows(AuditEvent) if a.action == "CUSTOMER_NAME_CAPTURED"]
    assert len(captured) == 1
    assert captured[0].old_value == {"full_name": "Ana"}


async def test_unpriced_extras_reach_event_staff_notice_and_calendar(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STAFF_NOTIFICATIONS_ENABLED", "true")
    get_settings.cache_clear()
    async with harness.db.begin() as session:
        session.add(
            NotificationRecipient(
                display_name="Asesora",
                phone_number="+573009998877",
                notify_on_evidence=False,
                notify_on_payment_pending=True,
                active=True,
            )
        )
    await converse(harness, EXPERIENCE_FORM, "7 pm", "sí")

    events = await harness.rows(Event)
    assert len(events) == 1
    assert "Adicional por cotizar: Violín en vivo: $300.000 COP" in events[0].special_requests
    assert "Ocasión: Aniversario" in events[0].special_requests
    services = await harness.rows(EventServiceRequest)
    assert [s.service_name for s in services] == ["VIOLINIST"]

    notices = [
        n for n in await harness.rows(StaffOutbox) if n.event_kind == "PAYMENT_PENDING_CREATED"
    ]
    assert len(notices) == 1
    assert notices[0].params[1] == "Romance entre Copas (adicionales por cotizar: Violín en vivo)"

    reservation = (await harness.rows(Reservation))[0]
    async with harness.db.begin() as session:
        (await session.get(Reservation, reservation.reservation_id)).status = "RESERVED"
    await sync_reservation_calendar(
        reservation.reservation_id,
        calendar=harness.calendar,
        sessionmaker=harness.db,
        settings=get_settings(),
    )
    description = (await harness.calendar.get_event(reservation.reservation_id.hex)).description
    assert "Adicional por cotizar: Violín en vivo: $300.000 COP" in description
    assert "Subtotal definido: $700.000 COP" in description
    assert "Ocasión: Aniversario" in description
    assert "Servicios solicitados: Violinista" in description


async def test_full_request_survives_notification_preview_limits(harness: Harness) -> None:
    extras = [f"Servicio especial {i}: {'detalle ' * 32}FIN{i}" for i in range(12)]
    form = EXPERIENCE_FORM.replace(
        "• Violín en vivo: $300.000 COP", " ".join("• " + item for item in extras)
    )
    await converse(harness, form, "7 pm", "sí")
    (reservation,) = await harness.rows(Reservation)
    assert all(item in reservation.commercial_details for item in extras)

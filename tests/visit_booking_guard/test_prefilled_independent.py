from decimal import Decimal

from app.customer.models import Customer
from app.lead.models import Lead
from tests.visit_booking_guard.helpers import Harness


async def test_budget_dotted(harness: Harness) -> None:
    await harness.send(
        "Quiero organizar una boda. Inversión contemplada (COP): $15.000.000",
        intent="SCHEDULE_VISIT",
    )
    await harness.assert_completed()
    assert len(await harness.rows(Lead)) == 1
    assert (await harness.rows(Lead))[0].estimated_budget == Decimal("15000000")


async def test_budget_small(harness: Harness) -> None:
    await harness.send(
        "Quiero organizar una boda. Inversión contemplada (COP): $15.000", intent="SCHEDULE_VISIT"
    )
    await harness.assert_completed()
    assert (await harness.rows(Lead))[0].estimated_budget == Decimal("15000")


async def test_negation_keeps_email(harness: Harness) -> None:
    await harness.send("No uses mi correo: anterior@example.org", intent="GENERAL_INFORMATION")
    await harness.assert_completed()
    assert (await harness.rows(Customer))[0].email is None


async def test_rejected_email_and_corrections(harness: Harness) -> None:
    from app.audit.models import AuditEvent

    await harness.send(
        "Nombre: Sol Ensayo Correo: sol@example.org Inversión contemplada (COP): $15.000.000",
        intent="SCHEDULE_VISIT",
    )
    await harness.assert_completed()
    await harness.send("El correo que aparece en el formulario no es mío.")
    await harness.assert_completed()
    assert (await harness.rows(Customer))[0].email is None
    await harness.send("Mi nombre correcto es Luna Ensayo. Presupuesto actualizado: $18.000.000")
    await harness.assert_completed()
    assert (await harness.rows(Customer))[0].full_name == "Luna Ensayo"
    assert (await harness.rows(Lead))[0].estimated_budget == Decimal("18000000")
    assert "CUSTOMER_EMAIL_WITHDRAWN" in {event.action for event in await harness.rows(AuditEvent)}
    await harness.send("Correo: otro@example.org. No utilicen este correo para contactarme.")
    await harness.assert_completed()
    assert (await harness.rows(Customer))[0].email is None

from decimal import Decimal

import pytest

from app.ai.models import AIExecution
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import code
from tests.visit_booking_guard.helpers import Harness

OLD_PAYMENT = (
    "¡Listo! Tu fecha está disponible hoy y queda asegurada al recibir el abono de "
    "{deposit_amount}. Puedes transferir a {bank_name}, {account_type} No. "
    "{account_number}, a nombre de {account_holder}. Cuando lo hagas, envíame aquí "
    "la foto del comprobante y nuestro equipo lo confirma."
)
NEW_PAYMENT = OLD_PAYMENT.replace(
    "{account_holder}. Cuando",
    "{account_holder}.\nLlave Bre-B: {breb_key}\nCuando",
)
KEY = "CEIBA-BREB-TEST"


async def install_payment_template(harness: Harness, *, use_breb: bool) -> None:
    async with harness.db.begin() as session:
        session.add(
            KnowledgeEntry(
                code=code("PAYMENT"),
                version=101,
                category="Reservas",
                question_summary="Instrucciones de pago",
                answer_template=NEW_PAYMENT if use_breb else OLD_PAYMENT,
                allowed_variables=[
                    "account_holder", "account_number", "account_type", "bank_name",
                    "deposit_amount", *(["breb_key"] if use_breb else []),
                ],
                status="APPROVED",
            )
        )


async def select_and_confirm_booking(harness: Harness) -> None:
    await harness.send("quiero reservar para el 14 de octubre a las 7 pm")
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_PLAN"
    await harness.send("1")
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    await harness.send("sí")
    await harness.assert_completed()


@pytest.mark.parametrize("event_type", ["ROMANTIC_DINNER", "PROPOSAL"])
async def test_g2_payment_instructions_include_breb_and_preserve_bank_text(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, event_type: str
) -> None:
    monkeypatch.setenv("BANK_BREB_KEY", KEY)
    get_settings.cache_clear()
    await harness.seed(event_type=event_type)
    await install_payment_template(harness, use_breb=True)
    await select_and_confirm_booking(harness)
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None
    assert harness.codes == [code("PAYMENT")]
    body = (await harness.bodies())[-1]
    reservations = await harness.rows(Reservation)
    assert len(reservations) == 1
    assert reservations[0].status == "PAYMENT_PENDING"
    deposit = Decimal(reservations[0].price_cop) / 2
    old_text = OLD_PAYMENT.format(
        deposit_amount="$" + f"{deposit:,.0f}".replace(",", "."),
        bank_name="Banco Ficticio",
        account_type="Ahorros",
        account_number="000123456",
        account_holder="Club de Prueba",
    )
    assert "Llave Bre-B: " + KEY in body
    assert body.replace("\nLlave Bre-B: " + KEY + "\n", " ") == old_text
    assert all(
        value in body for value in ("Banco Ficticio", "Ahorros", "000123456", "Club de Prueba")
    )
    assert await harness.rows(AIExecution) == []
    assert harness.calendar.created_event_ids == []


async def test_g2_old_payment_template_remains_compatible_without_breb(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BANK_BREB_KEY", "")
    get_settings.cache_clear()
    await harness.seed()
    await install_payment_template(harness, use_breb=False)
    await select_and_confirm_booking(harness)
    assert (await harness.conversation()).state == "BOT_ACTIVE"
    assert harness.codes == [code("PAYMENT")]
    assert "Llave Bre-B" not in (await harness.bodies())[-1]
    assert len(await harness.rows(Reservation)) == 1


async def test_g2_new_payment_template_without_key_does_not_create_payment_request(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BANK_BREB_KEY", "")
    get_settings.cache_clear()
    await harness.seed()
    await install_payment_template(harness, use_breb=True)
    await select_and_confirm_booking(harness)
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert code("PAYMENT") not in harness.codes
    assert await harness.rows(Reservation) == []
    assert harness.calendar.created_event_ids == []

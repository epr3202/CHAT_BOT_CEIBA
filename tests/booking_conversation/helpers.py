# Literal customer copy intentionally preserves long sentences.
# ruff: noqa: E501
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Message
from app.customer.models import Customer
from app.event.models import Event
from app.payment.models import PaymentEvidence
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.integration.helpers import whatsapp_message_payload
from tests.unit.test_ai_client import valid_classification
from tests.visit_booking_guard.helpers import BOGOTA, PHONE, ROMANTIC_INFO, Harness

START = datetime(2026, 10, 7, 19, tzinfo=BOGOTA)
TEMPLATES = {
    "PLAN": "¡Perfecto! Estas son nuestras experiencias disponibles:\n{plan_options}\nCuéntame el número o el nombre de la que quieres reservar.",
    "DATETIME": "¿Para qué fecha y a qué hora te gustaría vivirla? Por ejemplo: 7 de octubre a las 7 pm.",
    "TIME": "¿A qué hora te gustaría? Atendemos entre las 12 del día y las 9 de la noche.",
    "UNAVAILABLE": "Esa fecha y hora no están disponibles en nuestra agenda. ¿Quieres proponerme otra?",
    "CONFIRM": "Revisemos: {plan_name}, el {booking_date} a las {booking_time}. Valor {total_amount}; para asegurar la fecha se abona el 50 % ({deposit_amount}). ¿Deseas que registre tu reserva?",
    "PAYMENT": "¡Listo! Tu fecha está disponible hoy y queda asegurada al recibir el abono de {deposit_amount}. Puedes transferir a {bank_name}, {account_type} No. {account_number}, a nombre de {account_holder}.\nLlave Bre-B: {breb_key}\nCuando lo hagas, envíame aquí la foto del comprobante y nuestro equipo lo confirma.",
    "EVIDENCE": "¡Gracias! Recibimos tu comprobante. Nuestro equipo lo revisará y te confirmo por aquí en cuanto quede validado.",
    "CONFIRMED": "¡Tu reserva está confirmada! {plan_name}, el {booking_date} a las {booking_time}. Saldo pendiente: {missing_amount}, a más tardar el {balance_due_date}. ¡Nos vemos en La Ceiba!",
    "PARTIAL": "Registramos tu abono. Para asegurar la fecha faltan {missing_amount}; cuando completes el 50 % envíame el comprobante y confirmamos tu reserva.",
    "REJECTED": "No pudimos validar el comprobante que enviaste. ¿Puedes revisarlo y enviarlo de nuevo? Si tienes dudas, con gusto te comunico con un asesor.",
}


def code(name: str) -> str:
    return f"RESP-BOOKING-{name}-001"


async def selected_plan(harness: Harness) -> Plan:
    return next(p for p in await harness.rows(Plan) if p.code == "RITUAL_CORAZON")


async def send_catalog_information(harness: Harness) -> None:
    harness.turn += 1
    harness.codes.clear()
    harness.ai_result = dict(
        valid_classification(),
        primary_intent="GENERAL_INFORMATION",
        confidence=0.95,
        requested_action=None,
        extracted_entities=[
            {
                "entity": "event_type",
                "raw_value": "citas romanticas",
                "normalized_value": "ROMANTIC_DINNER",
                "quality_status": "PROVIDED",
                "confidence": 0.95,
                "needs_confirmation": False,
            }
        ],
    )
    payload = json.loads(
        whatsapp_message_payload(
            f"g2.189.{harness.turn}", phone=PHONE.lstrip("+"), text=ROMANTIC_INFO
        )
    )
    await process_whatsapp_webhook(payload, harness.db)
    await harness.assert_completed()


async def to_confirmation(harness: Harness) -> None:
    await harness.seed()
    await harness.send("quiero reservar para el 7 de octubre a las 7 pm")
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_PLAN"
    await harness.send("1")
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"


async def send_evidence(harness: Harness, caption: str | None = None) -> None:
    harness.turn += 1
    harness.codes.clear()
    payload = json.loads(
        whatsapp_message_payload(
            f"booking.media.{harness.turn}", phone=PHONE.lstrip("+"), text="unused"
        )
    )
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message["type"] = "image"
    message.pop("text")
    message["image"] = {"id": "synthetic-proof", "mime_type": "image/jpeg", "sha256": "0" * 64}
    if caption:
        message["image"]["caption"] = caption
    await process_whatsapp_webhook(payload, harness.db, request_id="booking-media")
    await harness.assert_completed()


async def review_fixture(harness: Harness, *, conversation_linked: bool = True) -> PaymentEvidence:
    await harness.seed(state="BOT_ACTIVE")
    selected = await selected_plan(harness)
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        customer = await session.scalar(select(Customer))
        event = await session.scalar(select(Event))
        row = Reservation(
            lead_id=conversation.active_lead_id,
            event_id=event.event_id,
            customer_id=customer.id,
            plan_id=selected.plan_id,
            conversation_id=conversation.id if conversation_linked else None,
            starts_at=START,
            ends_at=START.replace(hour=22),
            price_cop=250000,
            amount_paid_cop=0,
            status="PAYMENT_REVIEW",
            calendar_status="NONE",
        )
        session.add(row)
        await session.flush()
        message = Message(
            external_message_id=f"proof-{uuid4()}",
            conversation_id=conversation.id,
            customer_id=customer.id,
            channel="WHATSAPP",
            direction="INBOUND",
            message_type="image",
            content={},
        )
        session.add(message)
        await session.flush()
        evidence = PaymentEvidence(
            conversation_id=conversation.id,
            customer_id=customer.id,
            message_id=message.id,
            reservation_id=row.reservation_id,
            media_id="proof",
            mime_type="image/jpeg",
            declared_sha256="0" * 64,
            review_status="PENDING_REVIEW",
        )
        session.add(evidence)
        await session.flush()
    return evidence


def draft_of(conversation: Any) -> dict:
    draft = getattr(conversation, "booking_draft", None)
    assert isinstance(draft, dict), "Falta booking_draft persistido"
    return draft

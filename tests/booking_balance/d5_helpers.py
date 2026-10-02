import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Message, Outbox
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.notifications.models import NotificationRecipient, StaffOutbox
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from tests.booking_balance.conftest import BookingBalanceClock
from tests.booking_conversation.helpers import selected_plan
from tests.integration.helpers import login_headers, whatsapp_message_payload
from tests.visit_booking_guard.helpers import PHONE, Harness


async def seed_booking(
    harness: Harness,
    *,
    status: str = "PAYMENT_PENDING",
    paid: int = 0,
    past: bool = False,
    payment_handoff: bool = False,
) -> Reservation:
    await harness.seed(state="BOT_ACTIVE")
    conversation = await harness.conversation()
    plan = await selected_plan(harness)
    start = BookingBalanceClock.instant + timedelta(days=-1 if past else 10, hours=9)
    async with harness.db.begin() as session:
        customer = await session.get(Customer, conversation.customer_id)
        event = await session.scalar(
            select(Event).where(Event.lead_id == conversation.active_lead_id)
        )
        row = Reservation(
            lead_id=conversation.active_lead_id,
            event_id=event.event_id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            plan_id=plan.plan_id,
            starts_at=start,
            ends_at=start + timedelta(hours=3),
            price_cop=400000,
            amount_paid_cop=paid,
            status=status,
            payment_kind="DEPOSIT" if status == "RESERVED" else None,
            balance_due_at=start - timedelta(days=1) if status == "RESERVED" else None,
            calendar_status="CONFIRMED" if status == "RESERVED" else "NONE",
            external_calendar_id="already-confirmed" if status == "RESERVED" else None,
        )
        session.add(row)
        session.add(
            NotificationRecipient(
                display_name="Asesor D5",
                phone_number="+573000000197",
                active=True,
                notify_on_evidence=True,
            )
        )
        if payment_handoff:
            saved = await session.get(Conversation, conversation.id)
            saved.state = "WAITING_FOR_HUMAN"
            saved.pending_action = "WAIT_FOR_HUMAN"
            session.add(
                Handoff(
                    conversation_id=conversation.id,
                    reason="PAYMENT_REVIEW",
                    priority="URGENT",
                    status="PENDING",
                    summary="Revisión humana de comprobantes",
                )
            )
        await session.flush()
    return row


async def image(
    harness: Harness, external_id: str, *, caption: str | None = None
) -> dict[str, Any]:
    payload = json.loads(whatsapp_message_payload(external_id, phone=PHONE.lstrip("+")))
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = "image"
    message["timestamp"] = str(int(BookingBalanceClock.instant.timestamp()))
    message["image"] = {
        "id": f"synthetic-{external_id}",
        "mime_type": "image/jpeg",
        "sha256": "0" * 64,
    }
    if caption is not None:
        message["image"]["caption"] = caption
    await process_whatsapp_webhook(payload, harness.db, request_id=f"request-{external_id}")
    await harness.assert_completed()
    return payload


async def incoming_evidence(harness: Harness, external_id: str) -> PaymentEvidence:
    async with harness.db() as session:
        row = await session.scalar(
            select(PaymentEvidence)
            .join(Message, Message.id == PaymentEvidence.message_id)
            .where(Message.external_message_id == external_id)
        )
        assert row is not None, f"Imagen {external_id} no produjo evidencia"
        return row


async def message_outboxes(harness: Harness, external_id: str) -> list[Outbox]:
    async with harness.db() as session:
        return list(
            await session.scalars(
                select(Outbox)
                .join(Message, Message.id == Outbox.message_id)
                .where(Message.external_message_id == external_id)
                .order_by(Outbox.id)
            )
        )


async def review(api: AsyncClient, evidence: PaymentEvidence, amount: int) -> dict[str, Any]:
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=await login_headers(api, "90000000"),
        json={"amount_cop": amount},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def saved_booking(harness: Harness, reservation_id: UUID) -> Reservation:
    async with harness.db() as session:
        row = await session.get(Reservation, reservation_id)
        assert row is not None
        return row


async def staff_notice(harness: Harness, evidence: PaymentEvidence) -> list[StaffOutbox]:
    return [
        row
        for row in await harness.rows(StaffOutbox)
        if row.event_kind == "EVIDENCE_RECEIVED" and row.source_id == str(evidence.id)
    ]


async def new_conversation_after_three_days(harness: Harness) -> Conversation:
    original = await harness.conversation()
    BookingBalanceClock.instant += timedelta(days=3)
    async with harness.db.begin() as session:
        previous = await session.get(Conversation, original.id)
        previous.state = "CLOSED"
        row = Conversation(
            customer_id=original.customer_id,
            channel="WHATSAPP",
            state="BOT_ACTIVE",
            created_at=BookingBalanceClock.instant,
        )
        session.add(row)
        await session.flush()
    return row


async def take(api: AsyncClient, handoff: Handoff) -> None:
    response = await api.post(
        f"/admin/handoffs/{handoff.id}/take", headers=await login_headers(api, "90000000")
    )
    assert response.status_code == 200, response.text

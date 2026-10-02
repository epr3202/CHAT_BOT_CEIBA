"""D5 extension: finish the reservation's payment cases across customer conversations."""

from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.audit.models import AuditEvent
from app.channel.models import Message
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from tests.booking_balance.conftest import BookingBalanceClock
from tests.booking_balance.d5_helpers import image, incoming_evidence, review, seed_booking
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize("original_closed", [False, True])
async def test_last_evidence_closes_both_reservation_conversations_but_not_another_customer(
    harness: Harness, api: AsyncClient, original_closed: bool
) -> None:
    booking = await seed_booking(harness)
    await image(harness, "d5.lifecycle.old")
    first = await incoming_evidence(harness, "d5.lifecycle.old")
    original = await harness.conversation()
    BookingBalanceClock.instant += timedelta(days=3)
    async with harness.db.begin() as session:
        if original_closed:
            previous = await session.get(Conversation, original.id)
            previous.state = "CLOSED"
        current = Conversation(
            customer_id=original.customer_id,
            channel="WHATSAPP",
            state="BOT_ACTIVE",
            active_lead_id=original.active_lead_id,
            created_at=BookingBalanceClock.instant,
        )
        session.add(current)
        await session.flush()
    await image(harness, "d5.lifecycle.new")
    second = await incoming_evidence(harness, "d5.lifecycle.new")
    assert second.conversation_id == current.id
    assert first.reservation_id == second.reservation_id == booking.reservation_id

    async with harness.db.begin() as session:
        outsider = Customer(phone_number="+573777000123", full_name="Otro cliente")
        session.add(outsider)
        await session.flush()
        outsider_conversation = Conversation(
            customer_id=outsider.id,
            channel="WHATSAPP",
            state="WAITING_FOR_HUMAN",
            pending_action="WAIT_FOR_HUMAN",
        )
        session.add(outsider_conversation)
        await session.flush()
        outsider_case = Handoff(
            conversation_id=outsider_conversation.id,
            reason="PAYMENT_REVIEW",
            priority="URGENT",
            status="PENDING",
            summary="Revisión de otro cliente",
        )
        session.add(outsider_case)
        await session.flush()

    partial = await review(api, first, 100000)
    assert partial["result"] == "PARTIAL"
    assert all(case.status == "PENDING" for case in await harness.rows(Handoff))
    final = await review(api, second, 100000)
    assert final["result"] == "RESERVED"
    payment_cases = [
        case
        for case in await harness.rows(Handoff)
        if case.conversation_id in {original.id, current.id}
    ]
    assert len(payment_cases) == 2
    assert all(case.status == "RESOLVED" and case.resolved_at for case in payment_cases), (
        "D5: el último comprobante debe resolver los casos de pago de ambas conversaciones"
    )
    conversations = {row.id: row for row in await harness.rows(Conversation)}
    for conversation_id in (original.id, current.id):
        conversation = conversations[conversation_id]
        if original_closed and conversation_id == original.id:
            assert conversation.state == "CLOSED"
            continue
        assert conversation.state == "BOT_ACTIVE" and conversation.bot_enabled
        assert conversation.pending_action is None
    unrelated = next(case for case in await harness.rows(Handoff) if case.id == outsider_case.id)
    assert unrelated.status == "PENDING" and unrelated.resolved_at is None
    assert conversations[outsider_conversation.id].state == "WAITING_FOR_HUMAN"
    resolved = [
        event for event in await harness.rows(AuditEvent) if event.action == "HANDOFF_RESOLVED"
    ]
    assert {event.new_value["handoff_id"] for event in resolved} == {
        case.id for case in payment_cases
    }
    assert all(
        event.new_value["reservation_id"] == str(booking.reservation_id) for event in resolved
    )


async def test_payment_case_remains_open_for_pending_evidence_of_another_reservation(
    harness: Harness, api: AsyncClient
) -> None:
    booking = await seed_booking(harness)
    await image(harness, "d5.lifecycle.current-reservation")
    current = await incoming_evidence(harness, "d5.lifecycle.current-reservation")
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        other = Reservation(
            lead_id=booking.lead_id,
            event_id=booking.event_id,
            plan_id=booking.plan_id,
            customer_id=booking.customer_id,
            conversation_id=conversation.id,
            status="PAYMENT_REVIEW",
            starts_at=booking.starts_at + timedelta(days=1),
            ends_at=booking.ends_at + timedelta(days=1),
            price_cop=400000,
            amount_paid_cop=0,
            calendar_status="NONE",
        )
        message = Message(
            external_message_id="d5.lifecycle.other-reservation",
            conversation_id=conversation.id,
            customer_id=booking.customer_id,
            channel="WHATSAPP",
            direction="INBOUND",
            message_type="image",
            content={"image": {"id": "synthetic-other-reservation"}},
        )
        session.add_all([other, message])
        await session.flush()
        session.add(
            PaymentEvidence(
                conversation_id=conversation.id,
                customer_id=booking.customer_id,
                message_id=message.id,
                media_id="synthetic-other-reservation",
                mime_type="image/jpeg",
                declared_sha256="0" * 64,
                reservation_id=other.reservation_id,
                download_status="PENDING",
                review_status="PENDING_REVIEW",
            )
        )
    result = await review(api, current, 100000)
    assert result["result"] == "PARTIAL"
    case = (await harness.rows(Handoff))[0]
    assert case.status == "PENDING" and case.resolved_at is None, (
        "D5: un caso con otra reserva pendiente no se resuelve al terminar sólo una reserva"
    )
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"

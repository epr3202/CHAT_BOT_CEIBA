from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.channel.delivery import eligibility
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Message, Outbox
from app.channel.outbound import WhatsAppOutboundClient
from app.channel.worker import process_outbox_once
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence
from tests.booking_balance.d5_helpers import (
    image,
    incoming_evidence,
    message_outboxes,
    new_conversation_after_three_days,
    review,
    saved_booking,
    seed_booking,
    staff_notice,
    take,
)
from tests.booking_conversation.helpers import TEMPLATES
from tests.integration.helpers import login_headers
from tests.visit_booking_guard.helpers import Harness


async def test_t1_incident_196_two_100000_deposits_resolve_handoff(
    harness: Harness, api: AsyncClient
) -> None:
    booking = await seed_booking(harness)
    await image(harness, "d5.t1.a")
    first = await incoming_evidence(harness, "d5.t1.a")
    result = await review(api, first, 100000)
    assert result["result"] == "PARTIAL"
    assert result["reservation"]["amount_paid_cop"] == 100000
    await image(harness, "d5.t1.b")
    second = await incoming_evidence(harness, "d5.t1.b")
    assert second.reservation_id == booking.reservation_id
    ack = await message_outboxes(harness, "d5.t1.b")
    assert any(row.payload["text"]["body"] == TEMPLATES["EVIDENCE"] for row in ack), (
        "El segundo abono requiere acuse RESP-BOOKING-EVIDENCE-001"
    )
    assert len(await staff_notice(harness, second)) == 1
    result = await review(api, second, 100000)
    assert result["result"] == "RESERVED"
    assert result["reservation"]["amount_paid_cop"] == 200000
    assert result["customer_notification"] == "ENQUEUED"
    assert any("¡Tu reserva está confirmada!" in body for body in await harness.bodies())
    cases = await harness.rows(Handoff)
    assert cases and all(case.status == "RESOLVED" and case.resolved_at for case in cases)
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE" and conversation.bot_enabled
    assert conversation.pending_action is None


async def test_t2_two_images_during_review_both_link_and_ack_without_extra_transition(
    harness: Harness,
) -> None:
    booking = await seed_booking(harness)
    await image(harness, "d5.t2.a")
    await image(harness, "d5.t2.b")
    evidence = await harness.rows(PaymentEvidence)
    assert len(evidence) == 2 and all(
        row.reservation_id == booking.reservation_id for row in evidence
    ), "Las dos imágenes deben vincularse mientras la reserva sigue en PAYMENT_REVIEW"
    for external_id in ("d5.t2.a", "d5.t2.b"):
        ack = await message_outboxes(harness, external_id)
        assert len(ack) == 1 and ack[0].payload["text"]["body"] == TEMPLATES["EVIDENCE"]
    transitions = [
        row for row in await harness.rows(AuditEvent) if row.action == "RESERVATION_STATUS_CHANGED"
    ]
    assert len(transitions) == 1
    assert (await saved_booking(harness, booking.reservation_id)).status == "PAYMENT_REVIEW"
    assert len(await harness.rows(Handoff)) == 1


async def test_t3_balance_paid_in_new_conversation_without_calendar_mutation(
    harness: Harness, api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    booking = await seed_booking(harness, status="RESERVED", paid=200000)
    calendar_spies = {}
    for method in ("list_events", "create_event", "update_event", "delete_event"):
        spy = AsyncMock(wraps=getattr(harness.calendar, method))
        monkeypatch.setattr(harness.calendar, method, spy)
        calendar_spies[method] = spy
    current = await new_conversation_after_three_days(harness)
    await image(harness, "d5.t3.a")
    first = await incoming_evidence(harness, "d5.t3.a")
    assert first.conversation_id == current.id
    assert first.reservation_id == booking.reservation_id
    ack = await message_outboxes(harness, "d5.t3.a")
    assert len(ack) == 1 and ack[0].payload["text"]["body"] == TEMPLATES["EVIDENCE"]
    notice = await staff_notice(harness, first)
    assert len(notice) == 1 and notice[0].params[3] == "$200.000"
    calendar_calls = len(harness.calendar.queried_dates)
    result = await review(api, first, 100000)
    assert result["reservation"]["status"] == "RESERVED"
    assert result["reservation"]["amount_paid_cop"] == 300000
    notices = await message_outboxes(harness, "d5.t3.a")
    assert any(
        "Registramos tu pago. El saldo pendiente es $100.000" in row.payload["text"]["body"]
        for row in notices
    )
    assert any("debe estar pagado a más tardar" in row.payload["text"]["body"] for row in notices)
    await image(harness, "d5.t3.b")
    second = await incoming_evidence(harness, "d5.t3.b")
    assert second.reservation_id == booking.reservation_id
    result = await review(api, second, 100000)
    assert result["reservation"]["amount_paid_cop"] == 400000
    saved = await saved_booking(harness, booking.reservation_id)
    assert saved.status == "RESERVED" and saved.payment_kind == "FULL"
    assert saved.balance_due_at is None
    assert getattr(saved, "balance_overdue_at", None) is None
    assert (
        saved.external_calendar_id == "already-confirmed" and saved.calendar_status == "CONFIRMED"
    )
    assert len(harness.calendar.queried_dates) == calendar_calls
    assert all(spy.await_count == 0 for spy in calendar_spies.values()), (
        "Aceptar pagos de saldo no consulta ni modifica Calendar"
    )
    paid = await message_outboxes(harness, "d5.t3.b")
    assert any(
        "¡Recibimos el pago completo de tu reserva!" in row.payload["text"]["body"] for row in paid
    )
    changes = [
        row for row in await harness.rows(AuditEvent) if row.action == "RESERVATION_BALANCE_PAYMENT"
    ]
    assert len(changes) == 2
    assert changes[0].old_value["amount_paid_cop"] == 200000
    assert changes[-1].new_value["amount_paid_cop"] == 400000


async def test_t4_taken_handoff_captures_evidence_without_automatic_ack(
    harness: Harness, api: AsyncClient
) -> None:
    booking = await seed_booking(harness, status="PAYMENT_REVIEW", payment_handoff=True)
    case = (await harness.rows(Handoff))[0]
    await take(api, case)
    await image(harness, "d5.t4.taken")
    evidence = await incoming_evidence(harness, "d5.t4.taken")
    assert evidence.reservation_id == booking.reservation_id
    assert not await message_outboxes(harness, "d5.t4.taken")
    audits = await harness.rows(AuditEvent)
    assert any(row.action == "PAYMENT_ACK_SKIPPED_HUMAN_ACTIVE" for row in audits)


@pytest.mark.parametrize("status,past", [("PAYMENT_PENDING", True), ("CANCELLED", False)])
async def test_t5_past_or_cancelled_booking_is_never_linked(
    harness: Harness, status: str, past: bool
) -> None:
    await seed_booking(harness, status=status, past=past, payment_handoff=True)
    await image(harness, "d5.t5.ineligible")
    evidence = await incoming_evidence(harness, "d5.t5.ineligible")
    assert evidence.reservation_id is None, "Una reserva pasada o cancelada no recibe evidencias"
    assert not await staff_notice(harness, evidence)
    assert not await message_outboxes(harness, "d5.t5.ineligible")


async def test_t6_duplicate_first_webhook_has_one_evidence_ack_and_staff_notice(
    harness: Harness,
) -> None:
    await seed_booking(harness)
    payload = await image(harness, "d5.t6.first")
    await process_whatsapp_webhook(payload, harness.db, request_id="d5-t6-redelivery")
    assert len(await harness.rows(PaymentEvidence)) == 1
    evidence = await incoming_evidence(harness, "d5.t6.first")
    assert len(await message_outboxes(harness, "d5.t6.first")) == 1
    assert len(await staff_notice(harness, evidence)) == 1
    assert len(await harness.rows(Message)) == 1


async def test_t7_second_evidence_ack_has_own_context_and_pending_handoff_proof(
    harness: Harness,
) -> None:
    booking = await seed_booking(harness)
    await image(harness, "d5.t7.first")
    await image(harness, "d5.t7.second", caption="texto privado nunca debe repetirse")
    evidence = await incoming_evidence(harness, "d5.t7.second")
    ack = await message_outboxes(harness, "d5.t7.second")
    assert len(ack) == 1, "La segunda evidencia vinculada requiere exactamente un acuse"
    context = ack[0].delivery_context
    assert isinstance(context, dict)
    assert context.get("origin") == "PAYMENT_EVIDENCE_ACK"
    assert context.get("purpose") == "EVIDENCE_RECEIPT"
    assert context.get("evidence_id") == evidence.id
    cases = await harness.rows(Handoff)
    assert len(cases) == 1 and cases[0].status == "PENDING"
    assert context.get("handoff_id") == cases[0].id
    assert evidence.reservation_id == booking.reservation_id
    assert evidence.review_status == "PENDING_REVIEW"
    assert ack[0].payload["text"]["body"] == TEMPLATES["EVIDENCE"]
    first = await message_outboxes(harness, "d5.t7.first")
    assert len(first) == 1 and first[0].delivery_context["origin"] == "HANDOFF_NOTICE"
    async with harness.db() as session:
        conversation = await session.get(Conversation, evidence.conversation_id)
        row = await session.get(Outbox, ack[0].id)
        assert (await eligibility(session, conversation, row))[0] == "ELIGIBLE"


async def test_t8_taken_after_enqueue_suppresses_second_ack_before_meta(
    harness: Harness, api: AsyncClient
) -> None:
    await seed_booking(harness)
    await image(harness, "d5.t8.first")
    await image(harness, "d5.t8.second")
    ack = await message_outboxes(harness, "d5.t8.second")
    assert len(ack) == 1, "Falta el acuse encolado que debe revocarse al tomar el caso"
    async with harness.db.begin() as session:
        first = await session.scalar(select(Outbox).where(Outbox.id != ack[0].id))
        first.status = "SENT"
    await take(api, (await harness.rows(Handoff))[0])
    with respx.mock(assert_all_called=False) as router:
        route = router.post("https://graph.facebook.com/v20.0/123456789/messages").mock(
            return_value=httpx.Response(200, json={"messages": [{"id": "must-not-send"}]})
        )
        async with WhatsAppOutboundClient(get_settings()) as sender:
            await process_outbox_once(harness.db, sender, now=datetime.now(UTC))
        assert route.call_count == 0
    async with harness.db() as session:
        saved = await session.get(Outbox, ack[0].id)
        assert saved.status == "SUPPRESSED"
        assert saved.delivery_reason and (
            "HUMAN_ACTIVE" in saved.delivery_reason or "TAKEN" in saved.delivery_reason
        ), saved.delivery_reason


async def test_t9_paused_text_never_uses_evidence_ack_exception(harness: Harness) -> None:
    await seed_booking(harness, status="PAYMENT_REVIEW", payment_handoff=True)
    await harness.send("ya pagué, confírmame y dime el precio", intent="PAYMENT_MESSAGE")
    assert not await harness.rows(Outbox)
    assert not await harness.rows(PaymentEvidence)
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"


async def test_t10_second_image_redelivery_has_single_authorized_ack(harness: Harness) -> None:
    await seed_booking(harness)
    await image(harness, "d5.t10.first")
    payload = await image(harness, "d5.t10.second")
    await process_whatsapp_webhook(payload, harness.db, request_id="d5-t10-redelivery")
    evidence = await incoming_evidence(harness, "d5.t10.second")
    ack = await message_outboxes(harness, "d5.t10.second")
    assert len(ack) == 1, "El reenvío de la segunda imagen no omite ni duplica el acuse"
    assert ack[0].delivery_context.get("origin") == "PAYMENT_EVIDENCE_ACK"
    assert len(await harness.rows(PaymentEvidence)) == 2
    assert len(await staff_notice(harness, evidence)) == 1
    assert len(await harness.rows(Message)) == 2


async def test_d5_partial_with_another_pending_evidence_preserves_review_and_open_handoff(
    harness: Harness, api: AsyncClient
) -> None:
    booking = await seed_booking(harness)
    await image(harness, "d5.partial.first")
    await image(harness, "d5.partial.second")
    first = await incoming_evidence(harness, "d5.partial.first")
    second = await incoming_evidence(harness, "d5.partial.second")
    assert second.reservation_id == booking.reservation_id
    result = await review(api, first, 100000)
    assert result["result"] == "PARTIAL"
    assert result["reservation"]["status"] == "PAYMENT_REVIEW"
    assert (await harness.rows(Handoff))[0].status == "PENDING"
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    result = await review(api, second, 100000)
    assert result["result"] == "RESERVED"
    assert (await harness.rows(Handoff))[0].status == "RESOLVED"
    assert (await harness.conversation()).state == "BOT_ACTIVE"


@pytest.mark.parametrize("status", ["PAYMENT_PENDING", "PAYMENT_REVIEW", "RESERVED"])
async def test_d5_rejected_linked_evidence_notifies_and_resolves_last_payment_handoff(
    harness: Harness, api: AsyncClient, status: str
) -> None:
    paid = 200000 if status == "RESERVED" else 0
    booking = await seed_booking(harness, status=status, paid=paid, payment_handoff=True)
    await image(harness, "d5.reject.linked")
    evidence = await incoming_evidence(harness, "d5.reject.linked")
    assert evidence.reservation_id == booking.reservation_id
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/reject",
        headers=await login_headers(api, "90000000"),
        json={"note": "Referencia bancaria no válida"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "REJECTED"
    notices = await message_outboxes(harness, "d5.reject.linked")
    assert any(row.payload["text"]["body"] == TEMPLATES["REJECTED"] for row in notices)
    saved = await saved_booking(harness, booking.reservation_id)
    assert saved.amount_paid_cop == paid
    assert saved.status == ("RESERVED" if status == "RESERVED" else "PAYMENT_PENDING")
    case = (await harness.rows(Handoff))[0]
    assert case.status == "RESOLVED" and case.resolved_at
    assert (await harness.conversation()).state == "BOT_ACTIVE"

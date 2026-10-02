"""Contracts added after frozen G2; they extend the documented receipt authority."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.channel.outbound import WhatsAppOutboundClient
from app.channel.worker import process_outbox_once
from app.config.settings import get_settings
from app.conversation.models import Conversation, KnowledgeEntry
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence
from app.reservation.booking import payment_reservation_candidate
from app.reservation.models import Reservation
from tests.booking_balance.conftest import BookingBalanceClock
from tests.booking_balance.d5_helpers import (
    image,
    incoming_evidence,
    message_outboxes,
    review,
    seed_booking,
)
from tests.integration.helpers import login_headers, whatsapp_message_payload
from tests.visit_booking_guard.helpers import PHONE, Harness


async def test_other_open_case_denies_ack_and_preserves_pause_after_review(
    harness: Harness, api: AsyncClient
) -> None:
    await seed_booking(harness, status="PAYMENT_REVIEW", payment_handoff=True)
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        session.add(
            Handoff(
                conversation_id=conversation.id,
                status="PENDING",
                reason="CUSTOMER_REQUEST",
                priority="NORMAL",
                summary="Otro caso humano abierto",
            )
        )
    await image(harness, "extended.other-case")
    evidence = await incoming_evidence(harness, "extended.other-case")
    assert evidence.reservation_id is not None
    assert not await message_outboxes(harness, "extended.other-case")
    assert any(
        audit.action == "PAYMENT_ACK_SKIPPED_OTHER_HANDOFF"
        for audit in await harness.rows(AuditEvent)
    )
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/reject",
        headers=await login_headers(api, "90000000"),
        json={"note": "Referencia inválida"},
    )
    assert response.status_code == 200, response.text
    cases = {case.reason: case for case in await harness.rows(Handoff)}
    assert cases["PAYMENT_REVIEW"].status == "RESOLVED"
    assert cases["CUSTOMER_REQUEST"].status == "PENDING"
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert (await harness.conversation()).pending_action == "WAIT_FOR_HUMAN"


async def test_document_during_pause_keeps_passive_capture_without_ack(harness: Harness) -> None:
    booking = await seed_booking(harness, status="PAYMENT_REVIEW", payment_handoff=True)
    payload = json.loads(whatsapp_message_payload("extended.document", phone=PHONE.lstrip("+")))
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message.update(
        type="document",
        document={"id": "document-proof", "mime_type": "application/pdf", "sha256": "0" * 64},
    )
    await process_whatsapp_webhook(payload, harness.db, request_id="extended-document")
    await harness.assert_completed()
    evidence = await incoming_evidence(harness, "extended.document")
    assert evidence.reservation_id == booking.reservation_id
    assert not await message_outboxes(harness, "extended.document")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"


async def test_manual_booking_balance_receipt_notifies_current_customer_conversation(
    harness: Harness, api: AsyncClient
) -> None:
    booking = await seed_booking(harness, status="RESERVED", paid=200000)
    async with harness.db.begin() as session:
        saved = await session.get(Reservation, booking.reservation_id)
        saved.conversation_id = None
    await image(harness, "extended.manual-balance")
    evidence = await incoming_evidence(harness, "extended.manual-balance")
    assert evidence.reservation_id == booking.reservation_id
    result = await review(api, evidence, 100000)
    assert result["customer_notification"] == "ENQUEUED"
    notices = await message_outboxes(harness, "extended.manual-balance")
    assert any(
        "Registramos tu pago. El saldo pendiente es $100.000" in row.payload["text"]["body"]
        for row in notices
    )
    assert (await harness.rows(Handoff))[0].status == "RESOLVED"
    assert (await harness.conversation()).state == "BOT_ACTIVE"


@pytest.mark.parametrize("revoke", ["detached", "closed", "other_case", "bot_disabled"])
async def test_receipt_admission_revalidates_association_and_exclusive_case_without_http(
    harness: Harness, revoke: str
) -> None:
    await seed_booking(harness)
    await image(harness, "extended.admission.first")
    await image(harness, "extended.admission.second")
    evidence = await incoming_evidence(harness, "extended.admission.second")
    ack = await message_outboxes(harness, "extended.admission.second")
    assert len(ack) == 1 and ack[0].delivery_context["origin"] == "PAYMENT_EVIDENCE_ACK"
    async with harness.db.begin() as session:
        first = await session.scalar(select(Outbox).where(Outbox.id != ack[0].id))
        first.status = "SENT"
        conversation = await session.get(Conversation, evidence.conversation_id)
        if revoke == "detached":
            saved = await session.get(PaymentEvidence, evidence.id)
            saved.reservation_id = None
        elif revoke == "closed":
            conversation.state = "CLOSED"
        elif revoke == "bot_disabled":
            conversation.bot_enabled = False
        else:
            session.add(
                Handoff(
                    conversation_id=conversation.id,
                    status="PENDING",
                    reason="COMPLAINT",
                    priority="URGENT",
                    summary="Otro caso revoca el permiso de acuse",
                )
            )
    with respx.mock(assert_all_called=False) as router:
        route = router.post("https://graph.facebook.com/v20.0/123456789/messages").mock(
            return_value=httpx.Response(200, json={"messages": [{"id": "must-not-send"}]})
        )
        async with WhatsAppOutboundClient(get_settings()) as sender:
            await process_outbox_once(harness.db, sender, now=datetime.now(UTC))
        assert route.call_count == 0
    reasons = {
        "detached": "PAYMENT_ACK_EVIDENCE_UNLINKED",
        "closed": "PAYMENT_ACK_CLOSED",
        "other_case": "PAYMENT_ACK_OTHER_HANDOFF",
        "bot_disabled": "PAYMENT_ACK_BOT_DISABLED",
    }
    async with harness.db() as session:
        saved = await session.get(Outbox, ack[0].id)
        assert saved.status == "SUPPRESSED" and saved.delivery_reason == reasons[revoke]


async def test_candidate_priority_and_recency_ignore_full_cancelled_or_past(
    harness: Harness,
) -> None:
    original = await seed_booking(harness, status="RESERVED", paid=200000)
    candidates = []
    async with harness.db.begin() as session:
        for status, days in (
            ("PAYMENT_REVIEW", -5),
            ("PAYMENT_REVIEW", -3),
            ("PAYMENT_PENDING", -1),
        ):
            row = Reservation(
                lead_id=original.lead_id,
                event_id=original.event_id,
                plan_id=original.plan_id,
                conversation_id=original.conversation_id,
                customer_id=original.customer_id,
                status=status,
                starts_at=original.starts_at,
                ends_at=original.ends_at,
                price_cop=400000,
                amount_paid_cop=0,
                calendar_status="NONE",
                created_at=BookingBalanceClock.instant + timedelta(days=days),
            )
            session.add(row)
            await session.flush()
            candidates.append(row.reservation_id)
        for expected in (candidates[1], candidates[0], candidates[2], original.reservation_id):
            chosen = await payment_reservation_candidate(
                session, original.customer_id, now=BookingBalanceClock.instant
            )
            assert chosen.reservation_id == expected
            if chosen.status == "RESERVED":
                chosen.amount_paid_cop = chosen.price_cop
            else:
                chosen.status = "CANCELLED"
        assert (
            await payment_reservation_candidate(
                session, original.customer_id, now=BookingBalanceClock.instant
            )
            is None
        )
        saved = await session.get(Reservation, original.reservation_id)
        saved.amount_paid_cop = 200000
        saved.starts_at = BookingBalanceClock.instant - timedelta(days=1)
        assert (
            await payment_reservation_candidate(
                session, original.customer_id, now=BookingBalanceClock.instant
            )
            is None
        )


async def test_conflict_resolves_payment_case_but_preserves_new_human_case(
    harness: Harness, api: AsyncClient
) -> None:
    booking = await seed_booking(harness)
    await image(harness, "extended.conflict")
    harness.calendar.add_event("business-main", "exclusividad", booking.starts_at, booking.ends_at)
    evidence = await incoming_evidence(harness, "extended.conflict")
    result = await review(api, evidence, 200000)
    assert result["result"] == "CONFLICT"
    cases = {case.reason: case for case in await harness.rows(Handoff)}
    assert cases["PAYMENT_REVIEW"].status == "RESOLVED"
    assert cases["RESERVATION_CONFIRMATION"].status == "PENDING"
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert (await harness.conversation()).pending_action == "WAIT_FOR_HUMAN"


@pytest.mark.parametrize("unavailable", ["flag_disabled", "draft"])
async def test_last_review_resolves_handoff_even_when_notification_cannot_render(
    harness: Harness, api: AsyncClient, monkeypatch: pytest.MonkeyPatch, unavailable: str
) -> None:
    await seed_booking(harness)
    await image(harness, "extended.no-notification")
    evidence = await incoming_evidence(harness, "extended.no-notification")
    if unavailable == "flag_disabled":
        monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "false")
        get_settings.cache_clear()
    else:
        async with harness.db.begin() as session:
            template = await session.scalar(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.code == "RESP-BOOKING-PARTIAL-001",
                    KnowledgeEntry.version == 100,
                )
            )
            template.status = "DRAFT"
    result = await review(api, evidence, 100000)
    assert result["customer_notification"] == "DEFERRED"
    assert (await harness.rows(Handoff))[0].status == "RESOLVED"
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE" and conversation.pending_action is None
    changes = [
        audit
        for audit in await harness.rows(AuditEvent)
        if audit.action == "CONVERSATION_STATE_TRANSITION"
        and audit.new_value["state"] == "BOT_ACTIVE"
    ]
    assert changes and all(audit.request_id for audit in changes)

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.reservation.models import Reservation
from tests.booking_conversation.test_duplicate_reserved_guard_g2 import (
    PHONE,
    approved_duplicate,  # noqa: F401
    assert_blocked,
    existing_booking,
    send,
)
from tests.integration.helpers import whatsapp_message_payload
from tests.visit_booking_guard.helpers import Harness

pytestmark = pytest.mark.usefixtures("approved_duplicate")


async def test_duplicate_webhook_does_not_repeat_audit_or_notice(harness: Harness) -> None:
    row = await existing_booking(harness)
    text = "Quiero reservar Ritual del Corazón el 7 de noviembre de 2026 a las 3 pm"
    await send(harness, text)
    payload = json.loads(whatsapp_message_payload("pr49.1", phone=PHONE.lstrip("+"), text=text))
    await process_whatsapp_webhook(payload, harness.db, request_id=uuid4())
    await assert_blocked(harness, row)
    assert len(await harness.rows(Outbox)) == 1


async def test_exclusive_own_duplicate_precedes_unavailable(harness: Harness) -> None:
    from app.plan.models import Plan

    row = await existing_booking(harness)
    async with harness.db.begin() as session:
        plan = await session.get(Plan, row.plan_id)
        plan.exclusive = True
    await send(harness, "Quiero reservar Ritual del Corazón el 7 de noviembre de 2026 a las 3 pm")
    await assert_blocked(harness, row)


async def test_reset_preview_reports_all_nonterminal_reservations_without_mutation(
    harness: Harness,
) -> None:
    from app.admin.conversation_reset import reset_conversation_by_phone

    row = await existing_booking(harness)
    async with harness.db.begin() as session:
        original = await session.get(Reservation, row.reservation_id)
        for status in ("PAYMENT_PENDING", "PAYMENT_REVIEW", "CANCELLED", "EXPIRED"):
            session.add(
                Reservation(
                    lead_id=original.lead_id,
                    event_id=original.event_id,
                    plan_id=original.plan_id,
                    customer_id=original.customer_id,
                    status=status,
                    starts_at=original.starts_at,
                    ends_at=original.ends_at,
                    price_cop=original.price_cop,
                )
            )
    before = len(await harness.rows(AuditEvent))
    async with harness.db.begin() as session:
        summary = await reset_conversation_by_phone(
            session,
            raw_phone_number=PHONE,
            dry_run=True,
            actor="TEST_ADMIN",
            reason=None,
            request_id="pr49.preview",
        )
    assert {r["status"] for r in summary.live_reservations} == {
        "RESERVED",
        "PAYMENT_PENDING",
        "PAYMENT_REVIEW",
    }
    assert len(summary.live_reservations) == 3
    assert summary.audit_events_added == 0
    assert len(await harness.rows(AuditEvent)) == before
    async with harness.db() as session:
        assert (
            await session.scalar(
                select(Reservation.status).where(Reservation.reservation_id == row.reservation_id)
            )
        ) == "RESERVED"

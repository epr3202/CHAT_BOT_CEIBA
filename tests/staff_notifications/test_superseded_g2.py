"""PR #49: stale sources must not generate an internal notification."""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.channel.inbound import record_provider_status
from app.config.settings import get_settings
from app.main import app
from app.notifications.models import NotificationRecipient, StaffOutbox
from app.notifications.service import enqueue_for_reservation, intercept_staff_inbound
from app.notifications.worker import process_staff_outbox_once
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence, seed_reservation
from tests.staff_notifications.helpers import NOW, PHONE, audits, recipient, rows


async def pending_alert(**changes: Any) -> tuple[NotificationRecipient, Reservation]:
    target = await recipient(last_inbound_at=NOW, notify_on_payment_pending=True)
    reservation = await seed_reservation()
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(Reservation, reservation.reservation_id)
        await enqueue_for_reservation(
            session,
            reservation=saved,
            event_kind="PAYMENT_PENDING_CREATED",
            source_entity="reservation",
            source_id=str(saved.reservation_id),
            settings=get_settings(),
            request_id="pr49.pending",
        )
    async with app.state.db_sessionmaker.begin() as session:
        row = await session.scalar(select(StaffOutbox))
        # Make the notice recent according to the injected scheduler clock.
        row.created_at = NOW - timedelta(minutes=10)
        row.next_attempt_at = NOW
        for key, value in changes.items():
            setattr(row, key, value)
    return target, reservation


@pytest.mark.parametrize("original_queue", ["PENDING", "DEFERRED", "REOPENED"])
@pytest.mark.parametrize("new_status", ["CANCELLED", "EXPIRED", "PAYMENT_REVIEW", "RESERVED"])
async def test_R_obsolete_pending_alert_never_sends(
    client: AsyncClient, original_queue: str, new_status: str
) -> None:
    _, reservation = await pending_alert(
        status="DEFERRED" if original_queue != "PENDING" else "PENDING"
    )
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(Reservation, reservation.reservation_id)
        saved.status = new_status
    if original_queue == "REOPENED":
        async with app.state.db_sessionmaker.begin() as session:
            assert await intercept_staff_inbound(
                session,
                phone_number=PHONE,
                provider_timestamp=NOW + timedelta(seconds=1),
                external_message_id="pr49.reopen",
                settings=get_settings(),
                request_id="pr49.reopen",
            )
    sender = AsyncMock()
    for _ in range(2):
        await process_staff_outbox_once(app.state.db_sessionmaker, sender, get_settings(), now=NOW)
    sender.send_text.assert_not_called()
    sender.send_template.assert_not_called()
    saved = (await rows(StaffOutbox))[0]
    assert saved.status == "EXPIRED"
    assert saved.claim_token is None and saved.sent_at is None
    events = await audits("STAFF_NOTIFICATION_SUPERSEDED")
    assert len(events) == 1 and events[0].new_value["staff_outbox_id"] == saved.id


@pytest.mark.parametrize("review_status", ["ACCEPTED", "REJECTED"])
async def test_R_reviewed_evidence_alert_never_sends(
    client: AsyncClient, review_status: str
) -> None:
    await recipient(last_inbound_at=NOW)
    reservation = await seed_reservation(status="PAYMENT_REVIEW")
    evidence = await seed_evidence(reservation_id=reservation.reservation_id)
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(Reservation, reservation.reservation_id)
        await enqueue_for_reservation(
            session,
            reservation=saved,
            event_kind="EVIDENCE_RECEIVED",
            source_entity="payment_evidence",
            source_id=str(evidence.id),
            settings=get_settings(),
            request_id="pr49.evidence",
        )
        proof = await session.get(PaymentEvidence, evidence.id)
        proof.review_status = review_status
        queued = await session.scalar(select(StaffOutbox))
        queued.next_attempt_at = NOW
    sender = AsyncMock()
    await process_staff_outbox_once(app.state.db_sessionmaker, sender, get_settings(), now=NOW)
    sender.send_text.assert_not_called()
    sender.send_template.assert_not_called()
    assert (await rows(StaffOutbox))[0].status == "EXPIRED"
    assert len(await audits("STAFF_NOTIFICATION_SUPERSEDED")) == 1


async def test_V_current_pending_alert_still_sends(client: AsyncClient) -> None:
    await pending_alert()
    sender = AsyncMock()
    sender.send_text.return_value = "pr49.current"
    await process_staff_outbox_once(app.state.db_sessionmaker, sender, get_settings(), now=NOW)
    sender.send_text.assert_awaited_once()
    assert (await rows(StaffOutbox))[0].status == "SENT"


async def test_R_expired_alert_cannot_be_revived_by_late_callback(client: AsyncClient) -> None:
    _, reservation = await pending_alert(
        status="DEFERRED", message_kind="TEXT", provider_message_id="pr49.late"
    )
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(Reservation, reservation.reservation_id)
        saved.status = "CANCELLED"
    sender = AsyncMock()
    await process_staff_outbox_once(app.state.db_sessionmaker, sender, get_settings(), now=NOW)
    for status in ("delivered", "failed"):
        await record_provider_status(
            {
                "id": "pr49.late",
                "status": status,
                "timestamp": str(int(NOW.timestamp())),
                "errors": [{"code": 131047}],
            },
            app.state.db_sessionmaker,
        )
    assert (await rows(StaffOutbox))[0].status == "EXPIRED"
    assert len(await audits("STAFF_NOTIFICATION_SUPERSEDED")) == 1

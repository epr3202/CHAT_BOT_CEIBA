"""Sources are checked again after claiming; retired alerts stay terminal."""

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config.settings import get_settings
from app.main import app
from app.notifications import worker
from app.notifications.models import StaffOutbox
from app.notifications.service import enqueue_for_reservation
from app.reservation.models import Reservation
from tests.integration.test_b1a_plan_reservation_admin import seed_reservation
from tests.staff_notifications.helpers import NOW, audits, outbox, recipient, rows
from tests.staff_notifications.test_superseded_g2 import pending_alert


async def test_source_is_rechecked_after_claim_before_http(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, reservation = await pending_alert()
    original_claim = worker.claim_staff_outbox_batch

    async def cancel_after_claim(*args: Any, **kwargs: Any) -> list[worker.StaffClaim]:
        claims = await original_claim(*args, **kwargs)
        async with app.state.db_sessionmaker.begin() as session:
            row = await session.get(Reservation, reservation.reservation_id)
            row.status = "CANCELLED"
        return claims

    monkeypatch.setattr(worker, "claim_staff_outbox_batch", cancel_after_claim)
    sender = AsyncMock()
    await worker.process_staff_outbox_once(
        app.state.db_sessionmaker, sender, get_settings(), now=NOW
    )
    sender.send_text.assert_not_called()
    sender.send_template.assert_not_called()
    assert (await rows(StaffOutbox))[0].status == "EXPIRED"
    events = await audits("STAFF_NOTIFICATION_SUPERSEDED")
    assert len(events) == 1 and events[0].old_value == {"status": "SENDING"}


@pytest.mark.parametrize("parent_cancelled", [False, True])
async def test_evidence_requires_pending_review_and_live_parent(
    client: AsyncClient, parent_cancelled: bool
) -> None:
    target = await recipient(last_inbound_at=NOW)
    await outbox(target, with_source=True)
    if parent_cancelled:
        async with app.state.db_sessionmaker.begin() as session:
            row = await session.scalar(select(Reservation))
            row.status = "CANCELLED"
    sender = AsyncMock()
    sender.send_text.return_value = "pr49.valid-proof"
    await worker.process_staff_outbox_once(
        app.state.db_sessionmaker, sender, get_settings(), now=NOW
    )
    if parent_cancelled:
        sender.send_text.assert_not_called()
        assert (await rows(StaffOutbox))[0].status == "EXPIRED"
    else:
        sender.send_text.assert_awaited_once()
        assert (await rows(StaffOutbox))[0].status == "SENT"


@pytest.mark.parametrize("source_id", ["not-a-uuid", "123"])
async def test_missing_or_malformed_source_fails_closed(
    client: AsyncClient, source_id: str
) -> None:
    target = await recipient(last_inbound_at=NOW)
    await outbox(
        target,
        event_kind="PAYMENT_PENDING_CREATED",
        source_entity="reservation",
        source_id=source_id,
    )
    sender = AsyncMock()
    await worker.process_staff_outbox_once(
        app.state.db_sessionmaker, sender, get_settings(), now=NOW
    )
    sender.send_text.assert_not_called()
    sender.send_template.assert_not_called()
    assert len(await audits("STAFF_NOTIFICATION_SUPERSEDED")) == 1


@pytest.mark.parametrize("paid", [False, True])
async def test_balance_overdue_alert_requires_current_unpaid_balance(
    client: AsyncClient, paid: bool
) -> None:
    await recipient(last_inbound_at=NOW)
    reservation = await seed_reservation(status="RESERVED", balance_overdue_at=NOW)
    async with app.state.db_sessionmaker.begin() as session:
        row = await session.get(Reservation, reservation.reservation_id)
        await enqueue_for_reservation(
            session,
            reservation=row,
            event_kind="BALANCE_OVERDUE",
            source_entity="reservation",
            source_id=str(row.reservation_id),
            settings=get_settings(),
            request_id="pr49.overdue",
        )
        alert = await session.scalar(select(StaffOutbox))
        alert.next_attempt_at = NOW
        if paid:
            row.amount_paid_cop = row.price_cop
            row.balance_overdue_at = None
    sender = AsyncMock()
    sender.send_text.return_value = "pr49.current-overdue"
    await worker.process_staff_outbox_once(
        app.state.db_sessionmaker, sender, get_settings(), now=NOW
    )
    if paid:
        sender.send_text.assert_not_called()
        assert len(await audits("STAFF_NOTIFICATION_SUPERSEDED")) == 1
    else:
        sender.send_text.assert_awaited_once()
        assert (await rows(StaffOutbox))[0].status == "SENT"


async def test_literal_staff10_cancelled_d79893e0_never_sends(client: AsyncClient) -> None:
    target = await recipient(last_inbound_at=NOW)
    reservation = await seed_reservation(
        status="CANCELLED", reservation_id=UUID("d79893e0-105c-4211-8c1f-3cc1f138dc26")
    )
    await outbox(
        target,
        id=10,
        event_kind="PAYMENT_PENDING_CREATED",
        status="DEFERRED",
        source_entity="reservation",
        source_id=str(reservation.reservation_id),
    )
    sender = AsyncMock()
    await worker.process_staff_outbox_once(
        app.state.db_sessionmaker, sender, get_settings(), now=NOW
    )
    sender.send_text.assert_not_called()
    sender.send_template.assert_not_called()
    assert (await rows(StaffOutbox))[0].status == "EXPIRED"
    event = (await audits("STAFF_NOTIFICATION_SUPERSEDED"))[0]
    assert event.new_value["staff_outbox_id"] == 10
    assert event.new_value["source"]["id"] == str(reservation.reservation_id)


async def test_manual_staff_test_does_not_require_domain_source(client: AsyncClient) -> None:
    target = await recipient(last_inbound_at=NOW)
    await outbox(target, event_kind="TEST", source_entity="manual_test", source_id="pr49.manual")
    sender = AsyncMock()
    sender.send_text.return_value = "pr49.manual-test"
    await worker.process_staff_outbox_once(
        app.state.db_sessionmaker, sender, get_settings(), now=NOW
    )
    sender.send_text.assert_awaited_once()
    assert (await rows(StaffOutbox))[0].status == "SENT"

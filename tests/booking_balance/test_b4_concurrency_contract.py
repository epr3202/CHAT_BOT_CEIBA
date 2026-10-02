"""B4 extension: scans respect the inbound Customer → Reservation lock order."""

import asyncio
from contextlib import suppress
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.channel.inbound import get_or_create_customer
from app.customer.models import Customer
from app.main import app
from app.reservation.models import Reservation
from tests.booking_balance.b4_helpers import EARLY, config, entries, reminder_contract, reserved


async def test_inbound_customer_lock_does_not_block_scan_or_lock_its_reservation(
    client: Any,
) -> None:
    scheduler, _, notification_model = reminder_contract()
    blocked = await reserved()
    unblocked = await reserved()
    sm = app.state.db_sessionmaker
    async with sm() as session:
        phone = await session.scalar(
            select(Customer.phone_number).where(Customer.id == blocked.customer_id)
        )

    # This is the real inbound helper: its FOR UPDATE lock remains held as the
    # webhook transaction proceeds towards attaching an evidence to a reservation.
    async with sm() as inbound_session, inbound_session.begin():
        customer = await get_or_create_customer(inbound_session, phone)
        assert customer.id == blocked.customer_id
        scan = asyncio.create_task(scheduler(sm, config(), EARLY))
        try:
            done, _ = await asyncio.wait({scan}, timeout=2)
            reservation_lock_free = True
            try:
                async with sm() as observer, observer.begin():
                    observed = await observer.scalar(
                        select(Reservation.reservation_id)
                        .where(Reservation.reservation_id == blocked.reservation_id)
                        .with_for_update(nowait=True)
                    )
                    assert observed == blocked.reservation_id
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "55P03"
                reservation_lock_free = False
            assert reservation_lock_free, (
                "B4: el programador bloqueó la reserva mientras esperaba el cliente del inbound"
            )
            assert scan in done, "B4: el programador espera el Customer FOR UPDATE del inbound"
            assert await scan == 1
            queued = await entries(notification_model)
            assert [item.reservation_id for item in queued] == [unblocked.reservation_id]
        finally:
            if not scan.done():
                scan.cancel()
            with suppress(asyncio.CancelledError):
                await scan

    # Once the inbound transaction commits, the next scan can process the skipped
    # customer's reservation, while UNIQUE still prevents repeating the first one.
    assert await scheduler(sm, config(), EARLY) == 1
    queued = await entries(notification_model)
    assert {item.reservation_id for item in queued} == {
        blocked.reservation_id,
        unblocked.reservation_id,
    }

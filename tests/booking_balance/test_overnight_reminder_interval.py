from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient

from app.main import app
from app.reservation.reminders import enqueue_balance_reminders
from tests.booking_balance.b4_helpers import (
    DUE_AT,
    EARLY,
    START,
    config,
    reload_reservation,
    reserved,
)
from tests.staff_notifications.helpers import audits


async def test_overnight_reminder_audits_checkout_and_keeps_due_before_entry(
    client: AsyncClient,
) -> None:
    checkout = datetime.combine(
        START.astimezone(ZoneInfo("America/Bogota")).date() + timedelta(days=1),
        time(11),
        tzinfo=ZoneInfo("America/Bogota"),
    )
    row = await reserved(ends_at=checkout)
    await enqueue_balance_reminders(app.state.db_sessionmaker, config(), EARLY)
    await enqueue_balance_reminders(app.state.db_sessionmaker, config(), EARLY)
    recorded = await audits("BALANCE_REMINDER_INTERVAL_CAPTURED")
    assert len(recorded) == 1
    assert datetime.fromisoformat(recorded[0].new_value["starts_at"]) == START
    assert datetime.fromisoformat(recorded[0].new_value["ends_at"]) == checkout
    assert (await reload_reservation(row)).balance_due_at == DUE_AT == START - timedelta(days=1)

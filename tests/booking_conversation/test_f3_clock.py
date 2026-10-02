from datetime import date, time

import pytest

from app.config.settings import get_settings
from app.orchestrator.booking_flow import consume_date_time, resolve_booking_clock
from tests.booking_conversation.test_d1_clock import seed_booking


@pytest.mark.parametrize(
    "message,expected",
    [
        ("mañana a las 7", time(19)),
        ("manana a las 7", time(19)),
        ("a las 7 de la mañana", time(7)),
        ("7 am", time(7)),
        ("7 a.m.", time(7)),
        ("7 de la noche", time(19)),
    ],
)
def test_f3_tomorrow_is_date_not_am(message, expected):
    assert (
        resolve_booking_clock(
            message, only_time_expected=False, hours_start="12:00", latest_start="21:00"
        )
        == expected
    )


def test_f3_tomorrow_consumes_next_day_and_evening():
    draft = {}
    assert consume_date_time(draft, "mañana a las 7", date(2026, 10, 2), settings=get_settings())
    assert draft["date"] == "2026-10-03"
    assert draft["time"] == "19:00"


@pytest.mark.parametrize("message", ["a las 7 de la mañana", "7 am"])
async def test_f3_morning_remains_outside_booking_hours(harness, message):
    await seed_booking(harness)
    await harness.send(message)
    await harness.assert_completed()
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_TIME"
    assert harness.codes == ["RESP-BOOKING-TIME-001"]

from datetime import time

import pytest

from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.plan.models import Plan
from tests.b1a_contracts import require_symbol
from tests.booking_conversation.helpers import code


@pytest.mark.parametrize(
    "message,expected",
    [
        ("7", time(19)),
        ("7 pm", time(19)),
        ("a las 7", time(19)),
        ("las 8", time(20)),
        ("7:30", time(19, 30)),
        ("12", time(12)),
        ("1", time(13)),
        ("9", time(21)),
        ("10", time(10)),
        ("7 am", time(7)),
        ("11 am", time(11)),
        ("7 de la tarde", time(19)),
        ("7 de la mañana", time(7)),
    ],
)
def test_d1_clock_resolution(message, expected):
    resolve = require_symbol("app.orchestrator.booking_flow", "resolve_booking_clock")
    assert (
        resolve(message, only_time_expected=True, hours_start="12:00", latest_start="21:00")
        == expected
    )


def test_d1_datetime_never_takes_the_day_as_time():
    resolve = require_symbol("app.orchestrator.booking_flow", "resolve_booking_clock")
    assert (
        resolve("7 de octubre", only_time_expected=False, hours_start="12:00", latest_start="21:00")
        is None
    )
    assert resolve(
        "el 7 de octubre a las 7",
        only_time_expected=False,
        hours_start="12:00",
        latest_start="21:00",
    ) == time(19)


async def seed_booking(harness, *, full_name="Cliente", clock=None):
    await harness.seed(full_name=full_name)
    selected = (await harness.rows(Plan))[0]
    async with harness.db.begin() as session:
        conversation = await session.get(Conversation, (await harness.conversation()).id)
        conversation.pending_action = "SELECT_BOOKING_TIME"
        conversation.booking_draft = {
            "plan_id": str(selected.plan_id),
            "date": "2026-10-07",
            **({"time": clock} if clock else {}),
        }
    return selected


@pytest.mark.parametrize(
    "message,expected", [("7", "CONFIRM_BOOKING"), ("7 am", "SELECT_BOOKING_TIME")]
)
async def test_d1_conversation_with_meta_double(harness, monkeypatch, message, expected):
    monkeypatch.setenv("BOOKING_HOURS_END", "23:59")
    get_settings.cache_clear()
    await seed_booking(harness)
    await harness.send(message)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.pending_action == expected
    assert harness.codes == [code("CONFIRM" if expected == "CONFIRM_BOOKING" else "TIME")]
    assert code("UNAVAILABLE") not in harness.codes and not harness.classifier_calls

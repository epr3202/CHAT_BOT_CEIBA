from app.conversation.models import Conversation
from tests.booking_conversation.helpers import code
from tests.booking_conversation.test_d1_clock import seed_booking


async def test_minimum_lead_time_requests_date_without_claiming_calendar_conflict(harness):
    await seed_booking(harness)
    async with harness.db.begin() as session:
        conversation = await session.get(Conversation, (await harness.conversation()).id)
        conversation.booking_draft = {
            **conversation.booking_draft,
            "date": "2026-09-29",
        }
    await harness.send("7 pm")
    await harness.assert_completed()
    assert harness.codes == [code("DATETIME")]
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_DATETIME"

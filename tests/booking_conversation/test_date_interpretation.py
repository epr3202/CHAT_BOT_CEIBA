import json
from datetime import datetime

import pytest

from app.channel.inbound import process_whatsapp_webhook
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import code
from tests.booking_conversation.test_prefilled_experience import EXPERIENCE_FORM, converse
from tests.clock import FreezeAppClock
from tests.integration.helpers import whatsapp_message_payload
from tests.unit.test_ai_client import valid_classification
from tests.visit_booking_guard.helpers import BOGOTA, PHONE, Harness


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("22 deNoviembre  de 2026", "2026-11-22"),
        ("7deDiciembrede2026", "2026-12-07"),
        ("31 deOctubre de 2026", "PAST"),
    ],
)
async def test_glued_month_in_form(
    harness: Harness, freeze_app_clock: FreezeAppClock, value: str, expected: str
) -> None:
    freeze_app_clock(datetime(2026, 11, 20, 20, 25, tzinfo=BOGOTA))
    await converse(harness, EXPERIENCE_FORM.replace("31 de octubre de 2026", value))
    if expected != "PAST":
        assert harness.codes == [code("TIME")]
        assert (await harness.conversation()).booking_draft["date"] == expected
    else:
        assert harness.codes == ["RESP-DATE-PAST-001"]
    assert not harness.classifier_calls


@pytest.mark.parametrize(
    ("proposal", "reply", "confirmed"),
    [
        ("2026-11-22", False, True),
        ("2026-11-22", True, False),
        ("2027-11-22", False, False),
        (None, False, False),
    ],
)
async def test_form_date_interpretation_requires_customer_confirmation(
    harness: Harness,
    freeze_app_clock: FreezeAppClock,
    proposal: str | None,
    reply: bool,
    confirmed: bool,
) -> None:
    freeze_app_clock(datetime(2026, 11, 20, 20, 25, tzinfo=BOGOTA))
    raw = "el veintidós del undécimo mes de 2026"
    if reply:
        await converse(harness, EXPERIENCE_FORM.replace("31 de octubre de 2026", ""))
        assert harness.codes == [code("DATETIME")]
    entity = dict(
        entity="event_date",
        raw_value=raw,
        normalized_value=proposal,
        quality_status="PROVIDED",
        confidence=0.97,
    )
    harness.ai_result = (
        dict(valid_classification(), extracted_entities=[entity]) if proposal else {}
    )
    payload = whatsapp_message_payload(
        "synthetic-date-form",
        phone=PHONE.removeprefix("+"),
        text=raw if reply else EXPERIENCE_FORM.replace("31 de octubre de 2026", raw),
    )
    harness.codes.clear()  # Record templates for this inbound turn only.
    await process_whatsapp_webhook(json.loads(payload), harness.db)
    await harness.assert_completed()
    assert len(harness.classifier_calls) == 1
    sent = harness.classifier_calls[0]["messages"][-1]["content"]
    assert raw in sent and "Romance entre Copas" not in sent
    assert not await harness.rows(Reservation)
    assert not harness.calendar.create_call_count
    if proposal == "2026-11-22":
        assert harness.codes == ["RESP-EVENT-DATA-003"]
        assert "22 de noviembre" in (await harness.bodies())[-1]
        if not confirmed:
            await converse(harness, "No")
            draft = (await harness.conversation()).booking_draft
            assert draft["plan_code"] == "ROMANCE_COPAS"
            assert "suggested_date" not in draft and "date" not in draft
            assert harness.codes == [code("DATETIME")]
            return
        await converse(harness, "Sí")
        assert harness.codes == [code("TIME")]
        assert (await harness.conversation()).booking_draft["date"] == proposal
    else:
        assert harness.codes == [code("DATETIME")]

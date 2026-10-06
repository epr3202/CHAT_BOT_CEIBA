import json
from datetime import date, datetime, time
from uuid import uuid4

import pytest

from app.ai.models import AIExecution
from app.appointment.models import Appointment
from app.channel.inbound import process_whatsapp_webhook
from app.conversation.knowledge import render_response
from app.conversation.presentation import format_date_natural
from app.orchestrator import service as orchestrator
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import code
from tests.integration.helpers import whatsapp_message_payload
from tests.visit_booking_guard.helpers import BOGOTA, PHONE, Harness

# Literal parsed_output 3455 supplied for the incident; do not reconstruct it.
PAYLOAD_3455 = '{"entities": {}, "priority": "NORMAL", "confidence": 0.7, "sub_intent": null, "needs_human": false, "handoff_reason": null, "missing_fields": [], "primary_intent": "SCHEDULE_VISIT", "reasoning_code": "USER_INITIATED_SCHEDULE", "requested_action": null, "context_reference": {"pending_action": null, "last_question_code": null}, "secondary_intents": [], "extracted_entities": [{"entity": "event_date", "raw_value": "el 14", "confidence": 0.9, "quality_status": "PROVIDED", "normalized_value": "14", "validation_errors": [], "needs_confirmation": true}], "needs_confirmation": false, "information_category": null}'  # noqa: E501


async def test_g2_5_visit_without_fixed_context_confirms_initial_day(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = date(2026, 10, 5)
    candidate = date(2026, 10, 14)
    monkeypatch.setattr(
        orchestrator,
        "current_bogota_datetime",
        lambda: datetime.combine(today, time(10), tzinfo=BOGOTA),
    )
    await harness.seed(event_type=None)
    harness.ai_result = json.loads(PAYLOAD_3455)
    payload = json.loads(
        whatsapp_message_payload(
            f"fixed-date.3455.{uuid4().hex}",
            phone=PHONE.lstrip("+"),
            text="Me gustaría agendar para el 14",
        )
    )
    await process_whatsapp_webhook(payload, harness.db, request_id=uuid4())
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_APPOINTMENT_DATE"
    assert conversation.pending_action == "CONFIRM_VISIT_DATE"
    assert conversation.last_question_code == "RESP-EVENT-DATA-003"
    assert "RESP-VISIT-003" not in harness.codes
    assert (await harness.bodies())[-1] == await render_response(
        harness.db, "RESP-EVENT-DATA-003", {"resolved_date": candidate}
    )
    assert harness.calendar.queried_dates == []
    assert await harness.rows(Appointment) == []
    executions = await harness.rows(AIExecution)
    assert len(harness.classifier_calls) == len(executions) == 1
    assert executions[0].parsed_output == json.loads(PAYLOAD_3455)
    assert executions[0].validation_status == "VALID"

    await harness.send("sí")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_APPOINTMENT_SELECTION"
    assert conversation.pending_action == "SELECT_VISIT_TIME"
    assert conversation.visit_draft["visit_date"] == candidate.isoformat()
    assert harness.calendar.queried_dates == [candidate]
    assert len(harness.classifier_calls) == len(await harness.rows(AIExecution)) == 1
    assert "RESP-VISIT-003" not in harness.codes


@pytest.mark.parametrize(
    "today,candidate",
    [
        (date(2026, 10, 5), date(2026, 10, 14)),
        (date(2026, 10, 22), date(2026, 11, 14)),
        (date(2026, 12, 22), date(2027, 1, 14)),
    ],
)
async def test_r3_booking_confirms_day_before_requesting_time(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    today: date,
    candidate: date,
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "current_bogota_datetime",
        lambda: datetime.combine(today, time(10), tzinfo=BOGOTA),
    )
    await harness.seed()
    await harness.send("quiero reservar")
    await harness.send("1")
    await harness.send("el 14")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.pending_action == "SELECT_BOOKING_DATETIME"
    assert conversation.booking_draft.get("date") == candidate.isoformat()
    assert conversation.booking_draft.get("date_confirmation") is True
    assert harness.codes == ["RESP-EVENT-DATA-003"]
    assert (await harness.bodies())[-1] == await render_response(
        harness.db, "RESP-EVENT-DATA-003", {"resolved_date": candidate}
    )
    assert harness.classifier_calls == []
    assert await harness.rows(AIExecution) == []
    assert await harness.rows(Reservation) == []

    await harness.send("sí")
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_TIME"
    assert harness.codes == [code("TIME")]
    await harness.send("7 pm")
    await harness.assert_completed()
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    assert harness.codes == [code("CONFIRM")]
    assert format_date_natural(candidate) in (await harness.bodies())[-1]
    assert harness.classifier_calls == []
    assert await harness.rows(Reservation) == []

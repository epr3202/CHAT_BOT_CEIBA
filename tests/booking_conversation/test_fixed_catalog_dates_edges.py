import json
from datetime import date, datetime
from uuid import uuid4

import pytest

from app.appointment.models import Appointment
from app.appointment.service import resolve_visit_date_text
from app.channel.inbound import process_whatsapp_webhook
from app.conversation.knowledge import render_response
from app.orchestrator import service as orchestrator
from tests.booking_conversation.test_fixed_catalog_dates_g2 import PAYLOAD_3455
from tests.integration.helpers import whatsapp_message_payload
from tests.visit_booking_guard.helpers import BOGOTA, PHONE, Harness


@pytest.mark.parametrize(
    "today,text,expected",
    [
        (date(9999, 11, 22), "el 31", date(9999, 12, 31)),
        (date(9999, 12, 22), "el 31", date(9999, 12, 31)),
        (date(9999, 12, 22), "el 14", None),
    ],
)
def test_inferred_month_stays_within_calendar_range(
    today: date, text: str, expected: date | None
) -> None:
    result = resolve_visit_date_text(text, today=today, require_absolute_confirmation=True)
    assert result.resolved_date == expected


@pytest.mark.parametrize("text", ["mañana", "lunes 7 de octubre"])
def test_other_confirmation_reasons_are_not_inferred_months(text: str) -> None:
    result = resolve_visit_date_text(
        text, today=date(2026, 9, 29), require_absolute_confirmation=True
    )
    assert result.needs_confirmation is True
    assert result.inferred_month is False


async def start_day_confirmation(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "current_bogota_datetime",
        lambda: datetime(2026, 10, 5, 10, tzinfo=BOGOTA),
    )
    await harness.seed(event_type=None)
    harness.ai_result = json.loads(PAYLOAD_3455)
    payload = json.loads(
        whatsapp_message_payload(
            f"inferred-day.{uuid4().hex}",
            phone=PHONE.lstrip("+"),
            text="Me gustaría agendar para el 14",
        )
    )
    await process_whatsapp_webhook(payload, harness.db, request_id=uuid4())
    await harness.assert_completed()
    assert (await harness.conversation()).pending_action == "CONFIRM_VISIT_DATE"


async def test_denied_inferred_visit_date_cannot_be_confirmed_later(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start_day_confirmation(harness, monkeypatch)
    await harness.send("no")
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_APPOINTMENT_DATE"
    assert conversation.pending_action == "SELECT_VISIT_DATE"
    assert conversation.last_question_code == "RESP-VISIT-003"
    assert "candidate_visit_date" not in conversation.visit_draft
    assert harness.calendar.queried_dates == []
    await harness.send("sí")
    await harness.assert_completed()
    assert (await harness.conversation()).pending_action == "SELECT_VISIT_DATE"
    assert harness.calendar.queried_dates == []
    assert await harness.rows(Appointment) == []


async def test_unknown_reply_preserves_inferred_visit_date_and_repeats_question(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start_day_confirmation(harness, monkeypatch)
    before = await harness.conversation()
    draft = dict(before.visit_draft)
    await harness.send("todavía no sé")
    conversation = await harness.conversation()
    assert conversation.state == before.state
    assert conversation.pending_action == "CONFIRM_VISIT_DATE"
    assert conversation.last_question_code == "RESP-EVENT-DATA-003"
    assert conversation.failed_understanding_count == before.failed_understanding_count
    assert conversation.visit_draft == draft
    assert harness.codes == ["RESP-EVENT-DATA-003"]
    assert (await harness.bodies())[-1] == await render_response(
        harness.db, "RESP-EVENT-DATA-003", {"resolved_date": date(2026, 10, 14)}
    )
    assert harness.calendar.queried_dates == []
    await harness.send("sí")
    await harness.assert_completed()
    assert harness.calendar.queried_dates == [date(2026, 10, 14)]
    assert (await harness.conversation()).pending_action == "SELECT_VISIT_TIME"


@pytest.mark.parametrize("replacement,inferred", [("el 21", True), ("21 de octubre", False)])
async def test_new_date_replaces_inferred_visit_candidate(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
    inferred: bool,
) -> None:
    await start_day_confirmation(harness, monkeypatch)
    candidate = date(2026, 10, 21)
    await harness.send(replacement)
    conversation = await harness.conversation()
    if inferred:
        assert conversation.pending_action == "CONFIRM_VISIT_DATE"
        assert (await harness.bodies())[-1] == await render_response(
            harness.db, "RESP-EVENT-DATA-003", {"resolved_date": candidate}
        )
        assert harness.calendar.queried_dates == []
        await harness.send("sí")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_APPOINTMENT_SELECTION"
    assert conversation.pending_action == "SELECT_VISIT_TIME"
    assert conversation.visit_draft["visit_date"] == candidate.isoformat()
    assert "candidate_visit_date" not in conversation.visit_draft
    assert harness.calendar.queried_dates == [candidate]

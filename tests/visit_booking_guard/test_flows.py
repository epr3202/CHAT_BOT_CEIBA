from __future__ import annotations

from datetime import time

import pytest

from app.ai.models import AIExecution
from app.appointment.models import Appointment
from app.audit.models import AuditEvent
from app.channel import inbound
from app.channel.models import InboxJob
from app.conversation.catalog_event_type import FIXED_PRICE_EVENT_TYPES
from app.conversation.knowledge import render_response
from app.event.models import Event
from app.handoff.models import Handoff
from app.scheduling.availability import slot_datetime
from tests.visit_booking_guard.conftest import set_human_clock
from tests.visit_booking_guard.helpers import (
    ATTENDEES,
    BOOK_ABSOLUTE,
    CONFIRM,
    DATE_TIME,
    REASON,
    TIME_ONLY,
    VISIT_DATE,
    Harness,
    date_draft,
    time_draft,
)

pytestmark = pytest.mark.asyncio

BOOKING_CASES = [BOOK_ABSOLUTE, "quiero reservar para el sábado", "quiero separar la fecha"]


@pytest.mark.parametrize("event_type", ["ROMANTIC_DINNER", "PROPOSAL"])
@pytest.mark.parametrize("message", BOOKING_CASES)
@pytest.mark.parametrize("outside", [False, True], ids=["business-hours", "outside-hours"])
async def test_r1_booking_handoff_precedes_classifier(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    message: str,
    outside: bool,
) -> None:
    assert event_type in FIXED_PRICE_EVENT_TYPES
    set_human_clock(monkeypatch, outside=outside)
    await harness.seed(event_type)
    # Reproduce the incorrect classifier intent. The new guard must never ask for it.
    await harness.send(message, intent="SCHEDULE_VISIT", confidence=0.8)
    await harness.assert_completed()
    conversation = await harness.conversation()
    cases = await harness.rows(Handoff)
    expected_code = "RESP-HANDOFF-002" if outside else "RESP-HANDOFF-001"
    assert harness.classifier_calls == [], "Fixed-price booking must be decided before the LLM"
    assert await harness.rows(AIExecution) == []
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.visit_draft is None
    assert conversation.last_question_code == expected_code
    assert not any(code.startswith("RESP-VISIT-") for code in harness.codes)
    assert await harness.bodies() == [await render_response(harness.db, expected_code, {})]
    assert len(cases) == 1 and cases[0].reason == "RESERVATION_CONFIRMATION"
    assert message in cases[0].summary
    assert await harness.rows(Appointment) == []


@pytest.mark.parametrize("event_type", ["ROMANTIC_DINNER", "PROPOSAL"])
@pytest.mark.parametrize("relative", [False, True], ids=["absolute", "relative"])
async def test_r1_booking_date_persisted_on_event_and_handoff(
    harness: Harness,
    event_type: str,
    relative: bool,
) -> None:
    message = BOOKING_CASES[1] if relative else BOOK_ABSOLUTE
    await harness.seed(event_type)
    await harness.send(message, intent="SCHEDULE_VISIT", confidence=0.8)
    await harness.assert_completed()
    event = (await harness.rows(Event))[0]
    assert (
        event.event_date_raw and ("sábado" if relative else "7 de octubre") in event.event_date_raw
    )
    assert event.event_type == event_type
    if relative:
        # G3-J: a relative date must never be persisted as EXACT before confirmation.
        assert event.event_date is None
        assert event.event_date_type == "UNKNOWN"
    else:
        assert event.event_date == VISIT_DATE and event.event_date_type == "EXACT"
    cases = await harness.rows(Handoff)
    assert len(cases) == 1
    audit = [row for row in await harness.rows(AuditEvent) if row.action == "HANDOFF_CREATED"]
    assert len(audit) == 1
    detail = str(audit[0].new_value.get("detail", "")).casefold()
    assert ("2026-10-03" if relative else "2026-10-07") in detail or (
        "3 de octubre" if relative else "7 de octubre"
    ) in detail
    if relative:
        assert "pendiente" in detail and "confirm" in detail
        assert "pendiente" in cases[0].summary.casefold()
    assert (await harness.conversation()).visit_draft is None


# D1's closed vocabulary is deliberately specified here, independent of future product constants.
@pytest.mark.parametrize(
    "expression",
    [
        "AGÉNDAR",
        "reservar",
        "separar",
        "apartar",
        "programar",
        "cuadrar",
        "quiero la fecha",
    ],
)
async def test_r1_closed_booking_vocabulary(harness: Harness, expression: str) -> None:
    await harness.seed()
    await harness.send(expression, intent="UNKNOWN")
    await harness.assert_completed()
    assert harness.classifier_calls == []
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert (await harness.rows(Handoff))[0].reason == "RESERVATION_CONFIRMATION"


@pytest.mark.parametrize(
    "message", ["para el 7 de octubre", "información de precios", "reservatorio"]
)
async def test_r1_closed_vocabulary_does_not_match_unlisted_words(
    harness: Harness,
    message: str,
) -> None:
    await harness.seed()
    await harness.send(message, intent="GREETING")
    await harness.assert_completed()
    assert len(harness.classifier_calls) == 1
    assert await harness.rows(Handoff) == []


@pytest.mark.parametrize(
    "message",
    [
        "quiero agendar una visita para conocer el lugar",
        "quiero reservar para visitar",
        "quiero programar para conocer el lugar",
        "quiero cuadrar para ir a ver",
    ],
)
async def test_r1b_explicit_visit_overrides_fixed_price_guard(
    harness: Harness, message: str
) -> None:
    await harness.seed()
    await harness.send(message, intent="SCHEDULE_VISIT")
    await harness.assert_completed()
    assert (await harness.conversation()).pending_action == "SELECT_VISIT_DATE"
    assert "RESP-VISIT-003" in harness.codes
    assert await harness.rows(Handoff) == []


@pytest.mark.parametrize("with_lead,event_type", [(True, "WEDDING"), (True, None), (False, None)])
async def test_r1b_generic_booking_keeps_current_visit_flow(
    harness: Harness,
    with_lead: bool,
    event_type: str | None,
) -> None:
    await harness.seed(event_type, with_lead=with_lead)
    await harness.send("quiero agendar", intent="SCHEDULE_VISIT")
    await harness.assert_completed()
    assert (await harness.conversation()).pending_action == "SELECT_VISIT_DATE"
    assert "RESP-VISIT-003" in harness.codes
    assert await harness.rows(Handoff) == []


async def test_r2_opening_message_consumes_explicit_date(harness: Harness) -> None:
    await harness.seed("WEDDING")
    await harness.send("quiero visitar el 7 de octubre", intent="SCHEDULE_VISIT")
    await harness.assert_completed()
    assert "RESP-VISIT-003" not in harness.codes
    assert set(harness.calendar.queried_dates) == {VISIT_DATE}
    conversation = await harness.conversation()
    assert conversation.visit_draft["visit_date"] == "2026-10-07"
    assert conversation.pending_action == "SELECT_VISIT_TIME"


@pytest.mark.parametrize("message,expected", [(DATE_TIME, "08:00"), ("el 7/10 a las 9", "09:00")])
async def test_r3_date_and_time_advance_directly_to_attendees(
    harness: Harness,
    message: str,
    expected: str,
) -> None:
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_DATE", pending="SELECT_VISIT_DATE", draft=date_draft()
    )
    await harness.send(message)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.visit_draft.get("visit_time") == expected
    assert conversation.visit_draft["visit_date"] == "2026-10-07"
    assert conversation.pending_action == "COLLECT_VISIT_ATTENDEES"
    assert conversation.last_question_code == "RESP-VISIT-DATA-001"
    assert "RESP-VISIT-TIME-001" not in harness.codes
    assert set(harness.calendar.queried_dates) == {VISIT_DATE}


async def test_r3_occupied_time_offers_remaining_slots(harness: Harness) -> None:
    harness.calendar.add_busy(
        "business-main", slot_datetime(VISIT_DATE, time(8)), slot_datetime(VISIT_DATE, time(9))
    )
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_DATE", pending="SELECT_VISIT_DATE", draft=date_draft()
    )
    await harness.send(DATE_TIME)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.pending_action == "SELECT_VISIT_TIME"
    assert conversation.visit_draft["offered_slots"] == ["09:00", "10:00", "11:00"]
    assert conversation.visit_draft.get("visit_time") is None
    assert conversation.last_question_code == "RESP-VISIT-TIME-001"


@pytest.mark.parametrize(
    "message,code",
    [
        ("4 de octubre a las 8 am", "RESP-VISIT-006"),
        ("5 de octubre a las 8 am", "RESP-VISIT-006"),
        ("30 de septiembre a las 8 am", "RESP-VISIT-005"),
        ("1 de octubre a las 8 am", "RESP-VISIT-004"),
    ],
)
async def test_r3_invalid_date_keeps_existing_response(
    harness: Harness,
    message: str,
    code: str,
) -> None:
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_DATE", pending="SELECT_VISIT_DATE", draft=date_draft()
    )
    await harness.send(message)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.last_question_code == code
    assert conversation.pending_action == "SELECT_VISIT_DATE"
    assert "visit_time" not in conversation.visit_draft
    assert harness.calendar.queried_dates == []


async def test_r4_time_only_still_collects_attendees(harness: Harness) -> None:
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_SELECTION", pending="SELECT_VISIT_TIME", draft=time_draft()
    )
    await harness.send(TIME_ONLY)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.visit_draft["visit_time"] == "08:00"
    assert conversation.pending_action == "COLLECT_VISIT_ATTENDEES"
    assert conversation.last_question_code == "RESP-VISIT-DATA-001"


@pytest.mark.parametrize("reason", [REASON, "sí, una boda", "sí, es para una boda"])
async def test_r7_reason_summary_uses_label_and_retains_original(
    harness: Harness, reason: str
) -> None:
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_SELECTION",
        pending="COLLECT_VISIT_REASON",
        draft=time_draft(visit_time="08:00", attendee_count=int(ATTENDEES)),
    )
    await harness.send(reason)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.state == "APPOINTMENT_PENDING_CONFIRMATION"
    assert conversation.visit_draft["visit_reason"] == reason
    assert (await harness.rows(Event))[0].event_type == "ROMANTIC_DINNER"
    bodies = await harness.bodies()
    assert bodies[-1] == await render_response(harness.db, "RESP-VISIT-CONFIRM-001", {
        "visit_date": "7 de octubre de 2026", "visit_time": "08:00",
        "visit_attendee_count": "3", "event_type": "una boda",
    })
    await harness.send(CONFIRM, intent="CONFIRM")
    await harness.assert_completed()
    appointment = (await harness.rows(Appointment))[0]
    external = await harness.calendar.get_event(appointment.appointment_id.hex)
    assert f"Motivo de la visita: {reason}" in external.description
    assert appointment.visit_reason == reason
    assert (await harness.rows(Event))[0].event_type == "ROMANTIC_DINNER"


async def confirmed_incident(harness: Harness) -> None:
    # Start immediately before the literal final turn; parser changes cannot mask R8.
    await harness.seed(
        state="APPOINTMENT_PENDING_CONFIRMATION",
        pending="CONFIRM_APPOINTMENT",
        draft=time_draft(visit_time="08:00", attendee_count=3, visit_reason=REASON),
    )
    await harness.send(CONFIRM, intent="CONFIRM")
    await harness.assert_completed()
    assert (await harness.conversation()).state == "APPOINTMENT_CONFIRMED"
    assert len(await harness.rows(Appointment)) == 1


async def test_r8_confirmation_clears_pending_action(harness: Harness) -> None:
    await confirmed_incident(harness)
    conversation = await harness.conversation()
    assert conversation.pending_action is None
    assert conversation.visit_draft is None


async def test_r7_calendar_retains_literal_reason_and_lead_type(harness: Harness) -> None:
    await confirmed_incident(harness)
    appointment = (await harness.rows(Appointment))[0]
    external = await harness.calendar.get_event(appointment.appointment_id.hex)
    assert f"Motivo de la visita: {REASON}" in external.description
    assert appointment.visit_reason == REASON
    assert (await harness.rows(Event))[0].event_type == "ROMANTIC_DINNER"


async def test_r8_second_yes_completes_without_duplicate_appointment(harness: Harness) -> None:
    await confirmed_incident(harness)
    await harness.send("sí", intent="CONFIRM")
    await harness.assert_completed()
    assert len(await harness.rows(Appointment)) == 1
    assert harness.calendar.create_call_count == 1


async def test_g3_a_booking_words_in_visit_reason_keep_visit_flow(harness: Harness) -> None:
    """Added in G3 at Emerson's explicit request (A), not part of G2."""
    await harness.seed(state="WAITING_FOR_APPOINTMENT_SELECTION", pending="COLLECT_VISIT_REASON",
                       draft=time_draft(visit_time="08:00", attendee_count=3))
    await harness.send("para reservar la terraza", intent="SCHEDULE_VISIT")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.visit_draft["visit_reason"] == "para reservar la terraza"
    assert conversation.state == "APPOINTMENT_PENDING_CONFIRMATION"
    assert conversation.pending_action == "CONFIRM_APPOINTMENT"
    assert await harness.rows(Handoff) == []
    assert (await harness.rows(Event))[0].event_type == "ROMANTIC_DINNER"


async def test_g3_a_changed_lead_type_retries_before_applying_guard(
    harness: Harness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await harness.seed()
    original = inbound.classify_message

    async def change_type_after_decision(*args: object, **kwargs: object) -> object:
        decision = await original(*args, **kwargs)
        event = (await harness.rows(Event))[0]
        async with harness.db() as session, session.begin():
            stored = await session.get(Event, event.event_id)
            stored.event_type = "WEDDING"
        return decision

    monkeypatch.setattr(inbound, "classify_message", change_type_after_decision)
    await harness.send(BOOK_ABSOLUTE, intent="SCHEDULE_VISIT")
    assert await harness.rows(Handoff) == []
    assert (await harness.conversation()).state == "BOT_ACTIVE"
    job = (await harness.rows(InboxJob))[0]
    assert job.status == "PENDING" and job.last_error == "CONTEXT_CHANGED_RECLASSIFY"

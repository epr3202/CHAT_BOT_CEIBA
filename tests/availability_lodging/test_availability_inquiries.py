from datetime import datetime, timedelta
from typing import Any

import pytest

from app.audit.models import AuditEvent
from app.conversation.models import Conversation
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.availability_lodging.helpers import (
    AGENDA_ERROR,
    AVAILABLE,
    CONFIRM_AVAILABILITY,
    START,
    pending_request,
    require_inquiry_pending,
    seed_booking,
    symbol,
)
from tests.booking_conversation.helpers import code, draft_of
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize(
    "message",
    [
        "hay disponibilidad el 17 de noviembre a las 7",
        "tienen el 20 de diciembre libre?",
        "esta disponible ritual del corazon el sabado",
        "hay cupo para el 14 a las 8pm",
        "disponibles",
        "libres",
        "cupos",
        "hay espacio",
        "hay agenda",
        "tienen agenda",
        "está ocupado",
        "ocupada",
        "tienen fecha",
        "hay fecha",
        "puedo reservar el 17",
        "se puede el 17",
    ],
)
def test_R_availability_vocabulary(message: str) -> None:
    predicate = symbol("app.conversation.fixed_price_booking", "is_availability_inquiry")
    assert predicate(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "quiero reservar",
        "me interesa confesion bajo la luna",
        "cuanto cuesta",
        "donde quedan",
        "libreta",
        "ocupadosx",
        "disponibilidadx",
    ],
)
def test_V_other_requests_and_substrings_are_not_inquiries(message: str) -> None:
    predicate = symbol(
        "app.conversation.fixed_price_booking", "is_availability_inquiry", lambda _: False
    )
    assert predicate(message) is False


async def test_R_inquiry_reports_availability_without_name_payment_or_calendar(
    harness: Harness,
) -> None:
    await seed_booking(harness, pending=None, full_name=None, catalog=True)
    await harness.send("hay disponibilidad el 17 de noviembre a las 7")
    await harness.assert_completed()
    assert harness.codes == [AVAILABLE]
    conversation = await harness.conversation()
    assert conversation.pending_action == CONFIRM_AVAILABILITY
    draft = draft_of(conversation)
    assert draft["inquiry_only"] is True
    assert draft["date"] == START.date().isoformat()
    assert draft["time"] == "19:00"
    assert {"price_cop", "duration_minutes"} <= set(draft)
    assert code("PAYMENT") not in harness.codes
    assert "RESP-CUSTOMER-001" not in harness.codes
    assert await harness.rows(Reservation) == []
    assert harness.calendar.created_event_ids == []
    assert harness.classifier_calls == []
    answers = [
        row
        for row in await harness.rows(AuditEvent)
        if row.action == "AVAILABILITY_INQUIRY_ANSWERED"
    ]
    assert len(answers) == 1
    assert answers[0].new_value["plan_code"] == "PETALOS_ESTRELLAS"
    assert datetime.fromisoformat(answers[0].new_value["starts_at"]) == START
    assert answers[0].new_value["available"] is True
    assert answers[0].new_value["blockers_count"] == 0


async def seed_answered_inquiry(harness: Harness, *, full_name: str | None = None) -> Plan:
    require_inquiry_pending()
    plan = await seed_booking(
        harness, pending=CONFIRM_AVAILABILITY, inquiry=True, full_name=full_name
    )
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        row = await session.get(Conversation, conversation.id)
        row.booking_draft = {
            **row.booking_draft,
            "price_cop": plan.price_cop,
            "duration_minutes": plan.duration_minutes,
        }
    return plan


async def test_R_yes_revalidates_before_collecting_name(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_answered_inquiry(harness)
    calls = []
    original = harness.calendar.list_events

    async def observe(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return await original(*args, **kwargs)

    monkeypatch.setattr(harness.calendar, "list_events", observe)
    await harness.send("sí")
    await harness.assert_completed()
    assert len(calls) == 1, "La conversión debe revalidar la agenda"
    conversation = await harness.conversation()
    assert conversation.pending_action == "COLLECT_BOOKING_NAME"
    assert not draft_of(conversation).get("inquiry_only")
    assert harness.codes == ["RESP-CUSTOMER-001"]
    assert await harness.rows(Reservation) == []
    assert harness.calendar.created_event_ids == []
    conversions = [
        row
        for row in await harness.rows(AuditEvent)
        if row.action == "AVAILABILITY_INQUIRY_CONVERTED"
    ]
    assert len(conversions) == 1


async def test_R_yes_with_existing_name_goes_to_confirmation(harness: Harness) -> None:
    await seed_answered_inquiry(harness, full_name="Cliente Sintético")
    await harness.send("sí")
    await harness.assert_completed()
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    assert harness.codes == [code("CONFIRM")]
    assert await harness.rows(Reservation) == []


async def test_R_yes_with_previous_payment_request_keeps_final_duplicate_guard(
    harness: Harness,
) -> None:
    plan = await seed_answered_inquiry(harness)
    existing = await pending_request(harness, plan)
    await harness.send("sí")
    await harness.assert_completed()
    assert harness.codes == [code("PENDING")]
    assert [row.reservation_id for row in await harness.rows(Reservation)] == [
        existing.reservation_id
    ]
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert harness.calendar.created_event_ids == []


async def test_R_inquiry_skips_initial_duplicate_guard(harness: Harness) -> None:
    plan = await seed_booking(harness, pending=None, full_name=None)
    existing = await pending_request(harness, plan)
    await harness.send("hay disponibilidad entre pétalos y estrellas el 17 de noviembre 7 pm")
    await harness.assert_completed()
    assert harness.codes == [AVAILABLE]
    assert (await harness.conversation()).pending_action == CONFIRM_AVAILABILITY
    assert [row.reservation_id for row in await harness.rows(Reservation)] == [
        existing.reservation_id
    ]


async def test_R_negative_correction_reenters_with_preserved_plan(harness: Harness) -> None:
    plan = await seed_answered_inquiry(harness)
    await harness.send("no, mejor el 20")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.pending_action != CONFIRM_AVAILABILITY
    draft = draft_of(conversation)
    assert not draft.get("inquiry_only")
    assert draft["plan_id"] == str(plan.plan_id)
    assert draft["plan_code"] == plan.code
    await harness.send("hay disponibilidad el 20 de noviembre a las 7 pm")
    await harness.assert_completed()
    assert harness.codes == [AVAILABLE]
    assert (await harness.conversation()).pending_action == CONFIRM_AVAILABILITY
    assert (
        draft_of(await harness.conversation())["date"]
        == (START + timedelta(days=3)).date().isoformat()
    )
    assert await harness.rows(Reservation) == []


async def test_V_birthday_has_no_booking_agenda(harness: Harness) -> None:
    await harness.seed(event_type="BIRTHDAY")
    await harness.send("hay disponibilidad el 17 de noviembre a las 7")
    await harness.assert_completed()
    assert harness.classifier_calls
    conversation = await harness.conversation()
    assert conversation.booking_draft is None
    assert not any(
        value.startswith("RESP-BOOKING-") or value == AVAILABLE for value in harness.codes
    )
    assert await harness.rows(Reservation) == []


async def test_R_unavailable_inquiry_keeps_unavailable_response(harness: Harness) -> None:
    await seed_booking(harness, pending=None, full_name=None, catalog=True)
    harness.calendar.add_event("business-main", "exclusividad", START, START + timedelta(hours=3))
    await harness.send("hay disponibilidad el 17 de noviembre a las 7 pm")
    await harness.assert_completed()
    assert harness.codes == [code("UNAVAILABLE")]
    answers = [
        row
        for row in await harness.rows(AuditEvent)
        if row.action == "AVAILABILITY_INQUIRY_ANSWERED"
    ]
    assert len(answers) == 1
    assert answers[0].new_value["available"] is False
    assert answers[0].new_value["blockers_count"] == 1
    assert await harness.rows(Reservation) == []


async def test_R_conversion_revalidation_detects_new_blocker(harness: Harness) -> None:
    await seed_answered_inquiry(harness)
    harness.calendar.add_event("business-main", "exclusividad", START, START + timedelta(hours=3))
    await harness.send("sí")
    await harness.assert_completed()
    assert harness.codes == [code("UNAVAILABLE")]
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_DATETIME"
    assert await harness.rows(Reservation) == []


@pytest.mark.parametrize("conversion", [False, True], ids=["initial", "conversion"])
async def test_R_inquiry_calendar_failure_uses_observable_handoff(
    harness: Harness, conversion: bool
) -> None:
    if conversion:
        await seed_answered_inquiry(harness)
    else:
        await seed_booking(harness, pending=None, full_name=None, catalog=True)
    harness.calendar.raise_on.add("list_events")
    await harness.send("sí" if conversion else "hay disponibilidad el 17 de noviembre a las 7 pm")
    await harness.assert_completed()
    assert harness.codes == [AGENDA_ERROR]
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert {"plan_code", "date", "time"} <= set(draft_of(conversation))
    failures = [
        row for row in await harness.rows(AuditEvent) if row.action == "BOOKING_AVAILABILITY_FAILED"
    ]
    assert len(failures) == 1
    assert failures[0].reason == "CALENDAR_UNAVAILABLE"
    assert await harness.rows(Reservation) == []


async def test_V_inquiry_without_plan_asks_plan(harness: Harness) -> None:
    await harness.seed(event_type="PROPOSAL")
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        (
            await session.get(Conversation, conversation.id)
        ).last_question_code = "RESP-EVENTS-PROPOSAL-001"
    await harness.send("hay disponibilidad el 17 de noviembre a las 7 pm")
    await harness.assert_completed()
    assert harness.codes == [code("PLAN")]
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_PLAN"
    assert await harness.rows(Reservation) == []

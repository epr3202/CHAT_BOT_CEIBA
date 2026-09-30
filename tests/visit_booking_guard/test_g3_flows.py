from __future__ import annotations

from datetime import date, time
from uuid import uuid4

import pytest

from app.appointment.models import Appointment, AppointmentChange
from app.audit.models import AuditEvent
from app.channel import inbound
from app.channel.models import InboxJob
from app.conversation.knowledge import render_response
from app.event.models import Event
from app.handoff.models import Handoff
from app.orchestrator import service as orchestrator
from app.scheduling.availability import slot_datetime
from tests.visit_booking_guard.helpers import (
    ATTENDEES,
    BOOK_ABSOLUTE,
    CONFIRM,
    REASON,
    VISIT_DATE,
    Harness,
    time_draft,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("reason", [REASON, "sí, una boda", "sí, es para una boda"])
async def test_g3_h_reason_summary_matches_approved_template(
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


async def test_g3_c5_confirmed_appointment_survives_turn_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await harness.seed(state="APPOINTMENT_PENDING_CONFIRMATION", pending="CONFIRM_APPOINTMENT",
                       draft=time_draft(visit_time="08:00", attendee_count=3, visit_reason=REASON))
    original = orchestrator.enqueue_template

    async def fail_confirmation_notice(*args: object, **kwargs: object) -> None:
        if args[5] == "RESP-VISIT-CONFIRM-003":
            raise RuntimeError("G3 synthetic settlement failure after Calendar")
        await original(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "enqueue_template", fail_confirmation_notice)
    await harness.send(CONFIRM, intent="CONFIRM")
    assert harness.calendar.create_call_count == 1
    appointment = (await harness.rows(Appointment))[0]
    assert appointment.appointment_status == "CONFIRMED"
    assert appointment.external_calendar_id == appointment.appointment_id.hex
    assert appointment.requires_reconciliation is False
    job = (await harness.rows(InboxJob))[0]
    assert (job.status, job.last_error) == ("REVIEW", "EXTERNAL_OUTCOME_UNCERTAIN")
    conversation = await harness.conversation()
    assert conversation.state == "APPOINTMENT_PENDING_CONFIRMATION"
    assert conversation.pending_action == "CONFIRM_APPOINTMENT"
    assert conversation.visit_draft["visit_reason"] == REASON
    assert not any(row.action == "VISIT_CONFIRMED" for row in await harness.rows(AuditEvent))


@pytest.mark.parametrize("fail_notice", [False, True], ids=["commit", "rollback"])
async def test_g3_c5_reschedule_closes_before_conversation_turn(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fail_notice: bool,
) -> None:
    appointment_id = uuid4()
    new_date = date(2026, 10, 8)
    await harness.seed(
        state="APPOINTMENT_PENDING_CONFIRMATION", pending="CONFIRM_RESCHEDULE",
        draft={"mode": "RESCHEDULE", "resume": None, "appointment_id": str(appointment_id),
               "visit_date": new_date.isoformat(), "visit_time": "09:00"},
    )
    conversation = await harness.conversation()
    async with harness.db() as session, session.begin():
        session.add(Appointment(
            appointment_id=appointment_id, customer_id=conversation.customer_id,
            lead_id=conversation.active_lead_id, appointment_date=VISIT_DATE,
            start_time=time(8), attendee_count=3, visit_reason=REASON,
            appointment_status="CONFIRMED", external_calendar_id=appointment_id.hex,
        ))
    await harness.calendar.create_event(
        appointment_id.hex, "Visita comercial La Ceiba Club House",
        slot_datetime(VISIT_DATE, time(8)), slot_datetime(VISIT_DATE, time(8, 45)),
    )
    original = orchestrator.enqueue_template

    async def maybe_fail_notice(*args: object, **kwargs: object) -> None:
        if fail_notice and args[5] == "RESP-RESCHEDULE-004":
            raise RuntimeError("G3 synthetic reschedule settlement failure")
        await original(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "enqueue_template", maybe_fail_notice)
    await harness.send(CONFIRM, intent="CONFIRM")
    appointment = (await harness.rows(Appointment))[0]
    conversation = await harness.conversation()
    if fail_notice:
        assert appointment.appointment_date == new_date
        assert appointment.appointment_status == "RESCHEDULED"
        assert appointment.external_calendar_id == appointment_id.hex
        assert appointment.requires_reconciliation is False
        assert len(await harness.rows(AppointmentChange)) == 1
        assert (await harness.rows(InboxJob))[0].status == "REVIEW"
        assert harness.calendar.create_call_count == 1
        assert harness.calendar.update_call_count == 1
        assert conversation.state == "APPOINTMENT_PENDING_CONFIRMATION"
        assert conversation.pending_action == "CONFIRM_RESCHEDULE"
        assert conversation.visit_draft["visit_date"] == new_date.isoformat()
    else:
        await harness.assert_completed()
        assert appointment.appointment_date == new_date
        assert appointment.appointment_status == "RESCHEDULED"
        assert appointment.requires_reconciliation is False
        assert len(await harness.rows(AppointmentChange)) == 1
        assert conversation.state == "APPOINTMENT_CONFIRMED"
        assert conversation.pending_action is None and conversation.visit_draft is None


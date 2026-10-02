from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.ai.models import AIExecution
from app.appointment.models import Appointment
from app.audit.models import AuditEvent
from app.channel.models import Outbox
from app.conversation.knowledge import render_response
from app.event.models import Event
from app.handoff.models import Handoff
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import CONFIRM, VISIT_DATE, Harness, date_draft, time_draft

pytestmark = pytest.mark.asyncio


async def test_g3_c1_attendee_number_is_not_a_visit_time(harness: Harness) -> None:
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_DATE", pending="SELECT_VISIT_DATE", draft=date_draft()
    )
    await harness.send("quiero visitar el 7 de octubre, somos 10", intent="SCHEDULE_VISIT")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.visit_draft["visit_date"] == "2026-10-07"
    assert conversation.visit_draft.get("visit_time") is None
    assert conversation.pending_action == "SELECT_VISIT_TIME"
    assert conversation.last_question_code == "RESP-VISIT-TIME-001"
    assert conversation.visit_draft["offered_slots"] == ["08:00", "09:00", "10:00", "11:00"]


async def test_g3_c1_bare_hour_still_works_in_time_selection(harness: Harness) -> None:
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_SELECTION", pending="SELECT_VISIT_TIME", draft=time_draft()
    )
    await harness.send("8")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.visit_draft["visit_time"] == "08:00"
    assert conversation.pending_action == "COLLECT_VISIT_ATTENDEES"


@pytest.mark.parametrize(
    "reason",
    [
        "para conocer el salón",
        "sí, es para conocer el salón",
        "es para conocer el salón",
    ],
)
async def test_g3_c2_reason_prefix_is_display_only(harness: Harness, reason: str) -> None:
    await harness.seed(
        state="WAITING_FOR_APPOINTMENT_SELECTION",
        pending="COLLECT_VISIT_REASON",
        draft=time_draft(visit_time="08:00", attendee_count=3),
    )
    with capture_logs() as logs:
        await harness.send(reason)
    await harness.assert_completed()
    assert (await harness.conversation()).visit_draft["visit_reason"] == reason
    body = (await harness.bodies())[-1]
    assert "pensando en tu celebración" in body
    assert "conocer el salón" not in body
    assert any(
        log.get("event") == "event_type_presentation_fallback"
        and log.get("log_level") == "warning"
        and log.get("discarded_value") == reason
        for log in logs
    )
    await harness.send(CONFIRM, intent="CONFIRM")
    await harness.assert_completed()
    appointment = (await harness.rows(Appointment))[0]
    assert appointment.visit_reason == reason
    external = await harness.calendar.get_event(appointment.appointment_id.hex)
    assert f"Motivo de la visita: {reason}" in external.description
    assert (await harness.rows(Event))[0].event_type == "ROMANTIC_DINNER"


@pytest.mark.parametrize("initial_type", [None, "UNKNOWN", "EXACT"])
@pytest.mark.parametrize(
    "message,raw,candidate",
    [
        ("quiero reservar para el sábado", "el sábado", "3 de octubre de 2026"),
        ("quiero reservar para lunes 7 de octubre", "7 de octubre", "7 de octubre de 2026"),
    ],
)
async def test_g3_c3_unconfirmed_date_preserves_existing_fields(
    harness: Harness,
    initial_type: str | None,
    message: str,
    raw: str,
    candidate: str,
) -> None:
    await harness.seed()
    event = (await harness.rows(Event))[0]
    initial_date = VISIT_DATE if initial_type == "EXACT" else None
    initial_month = None if initial_type == "EXACT" else "2026-11"
    async with harness.db() as session, session.begin():
        stored = await session.get(Event, event.event_id)
        stored.event_date = initial_date
        stored.event_date_type = initial_type
        stored.event_month = initial_month
    await harness.send(message, intent="SCHEDULE_VISIT")
    await harness.assert_completed()
    stored = (await harness.rows(Event))[0]
    assert (stored.event_date, stored.event_date_type, stored.event_month) == (
        initial_date,
        initial_type,
        initial_month,
    )
    assert stored.event_date_raw == raw
    handoff = (await harness.rows(Handoff))[0]
    assert candidate in handoff.summary
    assert "pendiente de confirmación" in handoff.summary
    audit = [row for row in await harness.rows(AuditEvent) if row.action == "EVENT_DATE_CAPTURED"]
    assert len(audit) == 1
    assert audit[0].old_value["event_date"] == audit[0].new_value["event_date"]
    assert audit[0].old_value["event_date_type"] == audit[0].new_value["event_date_type"]
    assert (await harness.conversation()).visit_draft is None


@pytest.mark.parametrize(
    "message,raw",
    [
        ("quiero reservar el 7/10", "7/10"),
        ("me gustria agendar para el miercoles 7 de octubre", "7 de octubre"),
    ],
)
async def test_g3_c3_absolute_date_stores_only_matched_expression(
    harness: Harness,
    message: str,
    raw: str,
) -> None:
    await harness.seed()
    await harness.send(message, intent="SCHEDULE_VISIT")
    await harness.assert_completed()
    event = (await harness.rows(Event))[0]
    assert (event.event_date, event.event_date_type, event.event_date_raw) == (
        date(2026, 10, 7),
        "EXACT",
        raw,
    )
    assert "pendiente de confirmación" not in (await harness.rows(Handoff))[0].summary


async def test_g3_c4_catalog_label_skips_ai_and_preserves_catalog_caption(
    harness: Harness,
    tmp_path: Path,
) -> None:
    asset_id = await seed_catalog(harness.db, tmp_path, event_type="WEDDING")
    await harness.seed(None, pending="COLLECT_CATALOG_EVENT_TYPE")
    await harness.send("boda")
    await harness.assert_completed()
    assert harness.classifier_calls == []
    assert await harness.rows(AIExecution) == []
    assert (await harness.conversation()).pending_action is None
    outboxes = await harness.rows(Outbox)
    assert len(outboxes) == 1 and outboxes[0].message_kind == "DOCUMENT"
    assert outboxes[0].catalog_asset_id == asset_id
    assert outboxes[0].payload["document"]["caption"] == await render_response(
        harness.db,
        "RESP-CATALOG-001",
        {"event_type": "una boda"},
    )
    resolved = [
        row for row in await harness.rows(AuditEvent) if row.action == "CATALOG_EVENT_TYPE_RESOLVED"
    ]
    assert len(resolved) == 1 and resolved[0].new_value["event_type"] == "WEDDING"
    assert resolved[0].new_value["outcome"] == "SENT"

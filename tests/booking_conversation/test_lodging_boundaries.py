from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.channel.delivery import eligibility
from app.channel.models import Outbox
from app.conversation.models import Conversation, KnowledgeEntry
from app.handoff.models import Handoff
from app.orchestrator.service import deterministic_booking_or_catalog_classification
from app.plan.models import Plan
from app.reservation.models import Reservation
from data.knowledge_seed import extract_seed_entries, iter_seed_entries
from tests.availability_lodging.helpers import AGENDA_ERROR, LODGING, seed_booking
from tests.booking_backend.helpers import settings
from tests.booking_conversation.helpers import draft_of
from tests.integration.helpers import login_headers
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize(
    "pending",
    [
        "COLLECT_SERVICES",
        "COLLECT_EVENT_TYPE",
        "COLLECT_CATALOG_EVENT_TYPE",
        "SELECT_VISIT_DATE",
        "CONFIRM_VISIT_DATE",
        "SELECT_VISIT_TIME",
        "COLLECT_VISIT_ATTENDEES",
        "COLLECT_VISIT_REASON",
        "CONFIRM_APPOINTMENT",
        "SELECT_BOOKING_PLAN",
        "SELECT_BOOKING_DATETIME",
        "CONFIRM_BOOKING",
    ],
)
def test_lodging_does_not_capture_protected_pending(pending: str) -> None:
    context = {
        "state": "COLLECTING_EVENT_DATA",
        "bot_enabled": True,
        "pending_action": pending,
        "booking_event": {"event_type": "ROMANTIC_DINNER"},
    }
    result = deterministic_booking_or_catalog_classification(
        "hay hotel también?",
        context,
        settings(SELF_SERVICE_BOOKING_ENABLED=True),
    )
    assert result is None or result.reasoning_code != "LODGING_ALIAS"


@pytest.mark.parametrize(
    "change",
    [
        {"pending_confirmation": {"kind": "CLASSIFICATION"}},
        {"booking_draft_active": True},
        {"state": "HUMAN_ACTIVE"},
        {"bot_enabled": False},
    ],
)
def test_lodging_respects_confirmations_drafts_and_humans(change: dict[str, Any]) -> None:
    context = {"state": "BOT_ACTIVE", "bot_enabled": True, "pending_action": None, **change}
    result = deterministic_booking_or_catalog_classification("hotel", context, settings())
    assert result is None or result.reasoning_code != "LODGING_ALIAS"


async def test_agenda_error_notice_is_deliverable_while_paused(harness: Harness) -> None:
    await seed_booking(harness)
    harness.calendar.raise_on.add("list_events")
    await harness.send("17 de noviembre 7 pm")
    await harness.assert_completed()
    assert harness.codes == [AGENDA_ERROR]
    current = await harness.conversation()
    async with harness.db() as session:
        conversation = await session.get(Conversation, current.id)
        outbox = await session.scalar(select(Outbox))
        assert outbox.delivery_context["origin"] == "HANDOFF_NOTICE"
        assert (await eligibility(session, conversation, outbox))[0] == "ELIGIBLE"


async def test_unapproved_agenda_copy_preserves_system_error_draft(harness: Harness) -> None:
    await seed_booking(harness)
    before = draft_of(await harness.conversation())
    async with harness.db.begin() as session:
        session.add(
            KnowledgeEntry(
                code=AGENDA_ERROR,
                category="G3",
                question_summary="Latest copy awaiting approval",
                answer_template="[DRAFT] {plan_name} {date} {time}",
                allowed_variables=["plan_name", "date", "time"],
                version=101,
                status="DRAFT",
            )
        )
    harness.calendar.raise_on.add("list_events")
    await harness.send("17 de noviembre 7 pm")
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert draft_of(conversation) == before
    assert [row.reason for row in await harness.rows(Handoff)] == ["SYSTEM_ERROR"]
    assert len(await harness.rows(Outbox)) == 1
    assert any(a.action == "TEMPLATE_RENDER_FAILED" for a in await harness.rows(AuditEvent))


async def test_plan_editor_validates_hours_audits_and_exposes_draft(
    harness: Harness,
    api: AsyncClient,
) -> None:
    await seed_booking(harness)
    headers = await login_headers(api, document_id="90000000")
    plan = next(p for p in await harness.rows(Plan) if p.code == "REFUGIO_DOS")
    response = await api.patch(
        f"/admin/plans/{plan.plan_id}",
        headers=headers,
        json={"overnight": True, "checkin_from": "16:30", "checkout_time": "10:30"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["overnight"] is True
    assert response.json()["checkin_from"] == "16:30:00"
    assert response.json()["checkout_time"] == "10:30:00"
    invalid = await api.patch(
        f"/admin/plans/{plan.plan_id}",
        headers=headers,
        json={"checkout_time": None},
    )
    assert invalid.status_code == 422
    audits = [row for row in await harness.rows(AuditEvent) if row.action == "PLAN_UPDATED"]
    assert len(audits) == 1
    assert audits[0].new_value["checkout_time"] == "10:30:00"
    rows = await api.get("/admin/conversations", headers=headers)
    assert rows.status_code == 200
    assert rows.json()[0]["booking_draft"] == draft_of(await harness.conversation())
    assert await harness.rows(Reservation) == []


def test_leandro_approval_record_matches_seed_and_literal_variables() -> None:
    recorded = {
        e.code: e
        for e in extract_seed_entries(Path("docs/product/approved-responses.md").read_text())
    }
    seeded = {e.code: e for e in iter_seed_entries()}
    assert set(recorded) == {LODGING, "RESP-AVAILABILITY-AVAILABLE-001", AGENDA_ERROR}
    for code, entry in recorded.items():
        assert seeded[code].answer_template == entry.answer_template
        assert seeded[code].version == 1
        assert seeded[code].status == "APPROVED"

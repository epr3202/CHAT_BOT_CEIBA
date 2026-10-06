"""Fixed-price catalog requests establish the same context as approved information."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ai.models import AIExecution
from app.audit.models import AuditEvent
from app.catalog.models import CatalogSend
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.conversation.fixed_price_booking import BOOKING_ACTIONS
from app.conversation.models import KnowledgeEntry
from app.event.models import Event
from app.lead.models import Lead
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import code, draft_of
from tests.integration.helpers import whatsapp_message_payload
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.unit.test_ai_client import completion_payload, valid_classification
from tests.visit_booking_guard.helpers import BOGOTA, PHONE, Harness

PROPOSAL_CATALOG = "Hola quiero ver el catálogo de pedidas de mano"
ROMANTIC_CATALOG = "quiero ver el catálogo de planes románticos"
BOOK_DAY_ONLY = "Me gustaría agendar para el 14"

# Literal production parsed_output from execution 3455. Preserve spelling and order.
PAYLOAD_3455 = '{"entities": {}, "priority": "NORMAL", "confidence": 0.7, "sub_intent": null, "needs_human": false, "handoff_reason": null, "missing_fields": [], "primary_intent": "SCHEDULE_VISIT", "reasoning_code": "USER_INITIATED_SCHEDULE", "requested_action": null, "context_reference": {"pending_action": null, "last_question_code": null}, "secondary_intents": [], "extracted_entities": [{"entity": "event_date", "raw_value": "el 14", "confidence": 0.9, "quality_status": "PROVIDED", "normalized_value": "14", "validation_errors": [], "needs_confirmation": true}], "needs_confirmation": false, "information_category": null}'  # noqa: E501


def classifier_output(
    *, event_type: str | None = None, quality: str = "PROVIDED", catalog: bool = True
) -> str:
    return json.dumps(
        dict(
            valid_classification(),
            primary_intent="GENERAL_INFORMATION",
            confidence=0.95,
            requested_action=None,
            information_category="catalog_request" if catalog else "tipos de eventos",
            extracted_entities=(
                [
                    {
                        "entity": "event_type",
                        "raw_value": event_type,
                        "normalized_value": event_type,
                        "quality_status": quality,
                        "confidence": 0.95,
                        "needs_confirmation": False,
                    }
                ]
                if event_type
                else []
            ),
        )
    )


async def send(harness: Harness, message: str, *, output: str = PAYLOAD_3455) -> dict[str, Any]:
    # The existing harness records calls and owns the respx HTTP route.
    harness.ai_result = {"literal_output": output}
    harness.turn += 1
    harness.codes.clear()
    payload = json.loads(
        whatsapp_message_payload(
            f"fixed.catalog.g2.{uuid4().hex}", phone=PHONE.removeprefix("+"), text=message
        )
    )
    await process_whatsapp_webhook(payload, harness.db)
    await harness.assert_completed()
    return payload


@pytest.fixture(autouse=True)
def literal_classifier(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tests.visit_booking_guard.helpers.completion_payload",
        lambda arguments: completion_payload(arguments["literal_output"]),
    )


async def seed_assets(harness: Harness, tmp_path: Path) -> dict[str, UUID]:
    return {
        event_type: await seed_catalog(
            harness.db, tmp_path, event_type=event_type, send_mode="PROACTIVE"
        )
        for event_type in ("PROPOSAL", "ROMANTIC_DINNER")
    }


async def text_bodies(harness: Harness) -> list[str]:
    return [
        row.payload["text"]["body"]
        for row in sorted(await harness.rows(Outbox), key=lambda row: row.id)
        if row.message_kind == "TEXT"
    ]


async def assert_fixed_price_context(harness: Harness, event_type: str, asset_id: UUID) -> None:
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None
    assert conversation.pending_fields == []
    assert conversation.booking_draft is None
    assert conversation.active_lead_id is not None
    lead = (await harness.rows(Lead))[0]
    event = (await harness.rows(Event))[0]
    assert len(await harness.rows(Lead)) == len(await harness.rows(Event)) == 1
    assert event.event_type == event_type
    assert event.lead_id == lead.lead_id == conversation.active_lead_id
    expected_code = (
        "RESP-EVENTS-PROPOSAL-001" if event_type == "PROPOSAL" else "RESP-EVENTS-ROMANTIC-001"
    )
    entries = [entry for entry in await harness.rows(KnowledgeEntry) if entry.code == expected_code]
    approved = max(entries, key=lambda entry: entry.version)
    assert approved.status == "APPROVED"
    assert harness.codes == [expected_code]
    outboxes = sorted(await harness.rows(Outbox), key=lambda row: row.id)
    assert [row.message_kind for row in outboxes] == ["TEXT", "DOCUMENT"]
    assert outboxes[0].payload["text"]["body"] == approved.answer_template
    assert outboxes[1].catalog_asset_id == asset_id
    assert outboxes[1].delivery_context["after_outbox_id"] == outboxes[0].id
    sends = await harness.rows(CatalogSend)
    assert len(sends) == 1
    assert sends[0].trigger == "PROACTIVE"
    assert sends[0].lead_id == lead.lead_id
    assert sends[0].catalog_asset_id == asset_id
    assert sends[0].outbound_message_id == outboxes[1].id
    audits = [
        audit
        for audit in await harness.rows(AuditEvent)
        if audit.action == "FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO"
    ]
    assert len(audits) == 1
    assert audits[0].actor == "SYSTEM"
    assert audits[0].new_value["event_type"] == event_type
    assert audits[0].new_value["lead_id"] == str(lead.lead_id)
    assert audits[0].new_value["sent_count"] == 1


async def assert_plan_options(harness: Harness, event_type: str, count: int) -> None:
    conversation = await harness.conversation()
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action == "SELECT_BOOKING_PLAN"
    assert harness.codes == [code("PLAN")]
    plans = sorted(
        [plan for plan in await harness.rows(Plan) if plan.event_type == event_type],
        key=lambda plan: (plan.sort_order, plan.code),
    )
    assert len(plans) == count
    body = (await text_bodies(harness))[-1]
    assert all(f"{index}. {plan.name}" in body for index, plan in enumerate(plans, 1))
    assert all(
        plan.name not in body for plan in await harness.rows(Plan) if plan.event_type != event_type
    )


async def test_g2_1_proposal_catalog_sets_booking_context(harness: Harness, tmp_path: Path) -> None:
    await harness.seed(event_type=None, with_lead=False)
    assets = await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    await assert_fixed_price_context(harness, "PROPOSAL", assets["PROPOSAL"])
    assert not harness.classifier_calls
    assert not await harness.rows(AIExecution)
    await send(harness, BOOK_DAY_ONLY, output=PAYLOAD_3455)
    await assert_plan_options(harness, "PROPOSAL", 3)
    assert not harness.classifier_calls
    assert not await harness.rows(AIExecution)
    draft = draft_of(await harness.conversation())
    assert draft.get("date") == "2026-10-14"
    assert draft.get("date_confirmation") is True


async def test_g2_2_romantic_catalog_sets_booking_context(harness: Harness, tmp_path: Path) -> None:
    await harness.seed(event_type=None, with_lead=False)
    assets = await seed_assets(harness, tmp_path)
    await send(harness, ROMANTIC_CATALOG)
    await assert_fixed_price_context(harness, "ROMANTIC_DINNER", assets["ROMANTIC_DINNER"])
    assert not harness.classifier_calls
    await send(harness, BOOK_DAY_ONLY, output=PAYLOAD_3455)
    await assert_plan_options(harness, "ROMANTIC_DINNER", 5)
    assert not harness.classifier_calls
    assert not await harness.rows(AIExecution)


async def test_g2_3_non_fixed_catalog_keeps_existing_route(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    asset_id = await seed_catalog(
        harness.db, tmp_path, event_type="GENDER_REVEAL", send_mode="PROACTIVE"
    )
    before = await harness.conversation()
    await send(harness, "quiero ver el catálogo de revelación de género")
    conversation = await harness.conversation()
    assert (conversation.state, conversation.pending_action, conversation.last_question_code) == (
        before.state,
        before.pending_action,
        before.last_question_code,
    )
    assert not await harness.rows(Lead)
    assert not await harness.rows(Event)
    assert not await harness.rows(CatalogSend)
    assert not harness.classifier_calls
    assert not await harness.rows(AIExecution)
    assert not harness.codes
    outboxes = await harness.rows(Outbox)
    assert len(outboxes) == 1 and outboxes[0].message_kind == "DOCUMENT"
    assert outboxes[0].catalog_asset_id == asset_id
    assert not any(
        audit.action == "FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO"
        for audit in await harness.rows(AuditEvent)
    )


@pytest.mark.parametrize("event_type", ["PROPOSAL", "ROMANTIC_DINNER"])
@pytest.mark.parametrize(
    "message",
    [
        "quiero una visita para conocer el lugar",
        "quiero una visita para conocer el lugar el 14 de octubre a las 8 am",
    ],
)
async def test_g2_4_explicit_visit_precedes_fixed_booking(
    harness: Harness, tmp_path: Path, event_type: str, message: str
) -> None:
    await harness.seed(event_type=event_type)
    await seed_assets(harness, tmp_path)
    await send(
        harness,
        "Cuéntame sobre esa experiencia",
        output=classifier_output(event_type=event_type, catalog=False),
    )
    async with harness.db.begin() as session:
        for row in await harness.rows(Outbox):
            if row.message_kind == "DOCUMENT":
                saved = await session.get(Outbox, row.id)
                saved.status = "SENT"
    before = len(harness.classifier_calls)
    output = json.dumps(
        dict(
            valid_classification(),
            primary_intent="SCHEDULE_VISIT",
            confidence=0.95,
            requested_action=None,
        )
    )
    await send(harness, message, output=output)
    conversation = await harness.conversation()
    assert len(harness.classifier_calls) == before + 1
    assert conversation.pending_action not in BOOKING_ACTIONS
    assert conversation.state in {
        "WAITING_FOR_APPOINTMENT_DATE",
        "WAITING_FOR_APPOINTMENT_SELECTION",
    }
    assert conversation.visit_draft["mode"] == "SCHEDULE"
    assert conversation.booking_draft is None
    assert "RESP-VISIT-002" in harness.codes
    assert not any(response.startswith("RESP-BOOKING-") for response in harness.codes)
    assert not await harness.rows(Reservation)


@pytest.mark.parametrize("event_type", ["PROPOSAL", "ROMANTIC_DINNER"])
@pytest.mark.parametrize("quality", ["PROVIDED", "CORRECTED"])
async def test_g2_classifier_catalog_entity_sets_fixed_price_context(
    harness: Harness, tmp_path: Path, event_type: str, quality: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    assets = await seed_assets(harness, tmp_path)
    output = classifier_output(event_type=event_type, quality=quality)
    await send(harness, "Me compartes el PDF de esa experiencia", output=output)
    await assert_fixed_price_context(harness, event_type, assets[event_type])
    assert len(harness.classifier_calls) == 1
    executions = await harness.rows(AIExecution)
    assert len(executions) == 1
    assert executions[0].raw_output == output
    assert executions[0].parsed_output == json.loads(output)


@pytest.mark.parametrize("event_type", ["PROPOSAL", "ROMANTIC_DINNER"])
async def test_g2_classifier_catalog_uses_existing_fixed_price_context(
    harness: Harness, tmp_path: Path, event_type: str
) -> None:
    await harness.seed(event_type=event_type)
    assets = await seed_assets(harness, tmp_path)
    await send(harness, "Me compartes el PDF de esa experiencia", output=classifier_output())
    await assert_fixed_price_context(harness, event_type, assets[event_type])
    assert len(harness.classifier_calls) == 1


@pytest.mark.parametrize(
    "message,event_type", [(PROPOSAL_CATALOG, "PROPOSAL"), (ROMANTIC_CATALOG, "ROMANTIC_DINNER")]
)
async def test_g2_catalog_replay_and_repeat_deduplicate_proactive_pdf(
    harness: Harness, tmp_path: Path, message: str, event_type: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    assets = await seed_assets(harness, tmp_path)
    payload = await send(harness, message)
    await assert_fixed_price_context(harness, event_type, assets[event_type])
    outbox_ids = [row.id for row in await harness.rows(Outbox)]
    await process_whatsapp_webhook(payload, harness.db)
    await harness.assert_completed()
    assert [row.id for row in await harness.rows(Outbox)] == outbox_ids
    await send(harness, message)
    documents = [row for row in await harness.rows(Outbox) if row.message_kind == "DOCUMENT"]
    assert len(documents) == 1 and documents[0].catalog_asset_id == assets[event_type]
    sends = await harness.rows(CatalogSend)
    assert len(sends) == 1 and sends[0].trigger == "PROACTIVE"
    assert len(await harness.rows(Lead)) == len(await harness.rows(Event)) == 1
    assert not harness.classifier_calls
    assert not await harness.rows(AIExecution)


@pytest.mark.parametrize(
    "event_type,plan_code,price,deposit,exclusive",
    [
        ("ROMANTIC_DINNER", "RITUAL_CORAZON", 250000, "125.000", False),
        ("PROPOSAL", "PETALOS_ESTRELLAS", 450000, "225.000", False),
        ("PROPOSAL", "NOCHE_INOLVIDABLE", 2500000, "1.250.000", True),
    ],
)
async def test_g2_6_fixed_price_information_reaches_payment_instructions(
    harness: Harness,
    tmp_path: Path,
    event_type: str,
    plan_code: str,
    price: int,
    deposit: str,
    exclusive: bool,
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    assets = await seed_assets(harness, tmp_path)
    await send(
        harness,
        "Cuéntame sobre esa experiencia",
        output=classifier_output(event_type=event_type, catalog=False),
    )
    await assert_fixed_price_context(harness, event_type, assets[event_type])
    before = len(harness.classifier_calls)
    await send(harness, "quiero reservar para el 14 de octubre a las 7 pm")
    await assert_plan_options(harness, event_type, 3 if event_type == "PROPOSAL" else 5)
    selected = next(plan for plan in await harness.rows(Plan) if plan.code == plan_code)
    assert selected.exclusive is exclusive
    await send(harness, selected.name)
    assert harness.codes == [code("CONFIRM")]
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    await send(harness, "sí")
    assert harness.codes == [code("PAYMENT")]
    assert len(harness.classifier_calls) == before
    reservations = await harness.rows(Reservation)
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.status == "PAYMENT_PENDING"
    assert reservation.plan_id == selected.plan_id and reservation.price_cop == price
    assert reservation.starts_at == datetime(2026, 10, 14, 19, tzinfo=BOGOTA)
    assert reservation.amount_paid_cop == 0 and reservation.calendar_status == "NONE"
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None and conversation.booking_draft is None
    assert not harness.calendar.created_event_ids
    body = (await text_bodies(harness))[-1]
    assert all(
        value in body
        for value in (deposit, "Banco Ficticio", "Ahorros", "000123456", "Club de Prueba")
    )
    assert "{" not in body
    assert len(await harness.rows(CatalogSend)) == 1
    assert any(audit.action == "RESERVATION_CREATED" for audit in await harness.rows(AuditEvent))

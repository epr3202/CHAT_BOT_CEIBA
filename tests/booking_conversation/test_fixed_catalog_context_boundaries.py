"""Catalog source precedence and pending proposals retain backend authority."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.models import AIExecution
from app.audit.models import AuditEvent
from app.catalog.models import CatalogSend
from app.channel.models import Outbox
from app.conversation.fixed_price_booking import BOOKING_ACTIONS
from app.event.models import Event
from app.lead.models import Lead
from app.reservation.models import Reservation
from tests.booking_conversation.test_fixed_price_catalog_context_g2 import (
    PROPOSAL_CATALOG,
    assert_fixed_price_context,
    classifier_output,
    seed_assets,
    send,
)
from tests.booking_conversation.test_fixed_price_catalog_context_g2 import (
    literal_classifier as literal_classifier,
)
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize("quality", ["PROVIDED", "PENDING_CONFIRMATION"])
async def test_pending_classifier_type_keeps_explicit_catalog_without_firm_context(
    harness: Harness, tmp_path: Path, quality: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    assets = await seed_assets(harness, tmp_path)
    classification = json.loads(classifier_output(event_type="PROPOSAL", quality=quality))
    classification["extracted_entities"][0]["needs_confirmation"] = True
    output = json.dumps(classification)
    await send(harness, "Me compartes el PDF de esa experiencia", output=output)
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None
    assert conversation.active_lead_id is None
    assert not await harness.rows(Lead)
    assert not await harness.rows(Event)
    assert not await harness.rows(CatalogSend)
    assert not harness.codes
    outboxes = await harness.rows(Outbox)
    assert len(outboxes) == 1 and outboxes[0].message_kind == "DOCUMENT"
    assert outboxes[0].catalog_asset_id == assets["PROPOSAL"]
    assert not any(
        audit.action == "FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO"
        for audit in await harness.rows(AuditEvent)
    )
    catalog_audit = next(
        audit for audit in await harness.rows(AuditEvent) if audit.action == "CATALOG_SEND_ENQUEUED"
    )
    assert catalog_audit.new_value["trigger"] == "EXPLICIT_REQUEST"
    assert len(harness.classifier_calls) == 1
    executions = await harness.rows(AIExecution)
    assert len(executions) == 1
    assert executions[0].raw_output == output
    assert executions[0].parsed_output == classification


@pytest.mark.parametrize("classified_type", ["ROMANTIC_DINNER", "GENDER_REVEAL"])
async def test_unique_proposal_match_precedes_conflicting_classifier_entity(
    harness: Harness, tmp_path: Path, classified_type: str
) -> None:
    await harness.seed(
        event_type=None, state="COLLECTING_EVENT_DATA", pending="COLLECT_GUEST_COUNT"
    )
    assets = await seed_assets(harness, tmp_path)
    await seed_catalog(harness.db, tmp_path, event_type="GENDER_REVEAL", send_mode="PROACTIVE")
    await send(harness, PROPOSAL_CATALOG, output=classifier_output(event_type=classified_type))
    await assert_fixed_price_context(harness, "PROPOSAL", assets["PROPOSAL"])
    assert len(harness.classifier_calls) == 1
    resolved = [
        audit
        for audit in await harness.rows(AuditEvent)
        if audit.action == "CATALOG_EVENT_TYPE_RESOLVED"
    ]
    assert len(resolved) == 1
    assert resolved[0].new_value["event_type"] == "PROPOSAL"
    assert resolved[0].new_value["matched_label"] == "pedidas de mano"
    assert resolved[0].new_value["source"] == "EXPLICIT_CATALOG_MENTION"
    assert resolved[0].new_value["decision_source"] == "DETERMINISTIC"


async def test_non_fixed_match_precedes_classifier_proposal_without_fixed_capture(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(
        event_type=None, state="COLLECTING_EVENT_DATA", pending="COLLECT_GUEST_COUNT"
    )
    await seed_assets(harness, tmp_path)
    asset_id = await seed_catalog(
        harness.db, tmp_path, event_type="GENDER_REVEAL", send_mode="PROACTIVE"
    )
    await send(
        harness,
        "quiero ver el catálogo de revelación de género",
        output=classifier_output(event_type="PROPOSAL"),
    )
    conversation = await harness.conversation()
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action == "COLLECT_GUEST_COUNT"
    assert conversation.booking_draft is None
    assert (await harness.rows(Event))[0].event_type is None
    assert not harness.codes
    outboxes = await harness.rows(Outbox)
    assert len(outboxes) == 1 and outboxes[0].message_kind == "DOCUMENT"
    assert outboxes[0].catalog_asset_id == asset_id
    sends = await harness.rows(CatalogSend)
    assert len(sends) == 1 and sends[0].trigger == "EXPLICIT_REQUEST"
    assert not any(
        audit.action == "FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO"
        for audit in await harness.rows(AuditEvent)
    )
    assert len(harness.classifier_calls) == 1


@pytest.mark.parametrize(
    "known_type,classified_type",
    [("ROMANTIC_DINNER", "PROPOSAL"), ("PROPOSAL", "ROMANTIC_DINNER")],
)
async def test_firm_classifier_type_precedes_existing_backend_type(
    harness: Harness, tmp_path: Path, known_type: str, classified_type: str
) -> None:
    await harness.seed(event_type=known_type)
    assets = await seed_assets(harness, tmp_path)
    await send(
        harness,
        "Me compartes el PDF de esa experiencia",
        output=classifier_output(event_type=classified_type),
    )
    await assert_fixed_price_context(harness, classified_type, assets[classified_type])
    assert len(harness.classifier_calls) == 1


@pytest.mark.parametrize(
    "message",
    [
        "quiero una visita para conocer el lugar de la pedida de mano",
        "quiero una visita para conocer el lugar de la pedida de mano el 14 de octubre a las 8 am",
    ],
)
async def test_explicit_visit_with_proposal_phrase_precedes_catalog_shortcuts(
    harness: Harness, tmp_path: Path, message: str
) -> None:
    await harness.seed(event_type="PROPOSAL")
    await seed_assets(harness, tmp_path)
    await send(
        harness,
        "Cuéntame sobre esa experiencia",
        output=classifier_output(event_type="PROPOSAL", catalog=False),
    )
    outboxes = await harness.rows(Outbox)
    async with harness.db.begin() as session:
        for row in outboxes:
            if row.message_kind == "DOCUMENT":
                saved = await session.get(Outbox, row.id)
                saved.status = "SENT"
    before = len(harness.classifier_calls)
    visit = json.loads(classifier_output())
    visit["primary_intent"] = "SCHEDULE_VISIT"
    visit["information_category"] = None
    await send(harness, message, output=json.dumps(visit))
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

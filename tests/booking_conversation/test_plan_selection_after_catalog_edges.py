"""G3: catalog plan selection preserves interruptions and webhook idempotency."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.ai.models import AIExecution
from app.catalog.models import CatalogSend
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Message, Outbox
from app.config.settings import get_settings
from app.conversation.fixed_price_booking import BOOKING_ACTIONS
from app.conversation.models import Conversation
from app.event.models import Event
from app.handoff.models import Handoff
from app.lead.models import Lead
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import code, draft_of
from tests.booking_conversation.test_fixed_price_catalog_context_g2 import (
    PROPOSAL_CATALOG,
    ROMANTIC_CATALOG,
    classifier_output,
    seed_assets,
    send,
)
from tests.booking_conversation.test_fixed_price_catalog_context_g2 import (
    literal_classifier as literal_classifier,
)
from tests.booking_conversation.test_plan_selection_after_catalog_g2 import (
    INCIDENT_T1,
    INCIDENT_T2,
    assert_no_ai_or_handoff,
    assert_plan_options,
    assert_selected_plan,
)
from tests.booking_conversation.test_plan_selection_after_catalog_g2 import (
    incident_clock as incident_clock,
)
from tests.unit.test_ai_client import valid_classification
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize("catalog", [PROPOSAL_CATALOG, ROMANTIC_CATALOG])
@pytest.mark.parametrize(
    "message",
    [
        "quiero una visita para conocer el lugar",
        "quiero una visita para conocer el lugar el 14 de octubre a las 8 am",
        "quiero una visita para conocer el lugar de Confesión bajo la Luna",
    ],
)
async def test_g3_explicit_visit_after_catalog_keeps_visit_route(
    harness: Harness, tmp_path: Path, catalog: str, message: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, catalog)
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
    assert len(harness.classifier_calls) == len(await harness.rows(AIExecution)) == 1
    assert conversation.pending_action not in BOOKING_ACTIONS
    assert conversation.state in {
        "WAITING_FOR_APPOINTMENT_DATE",
        "WAITING_FOR_APPOINTMENT_SELECTION",
    }
    assert conversation.visit_draft["mode"] == "SCHEDULE"
    assert conversation.booking_draft is None
    assert "RESP-VISIT-002" in harness.codes
    assert not any(response.startswith("RESP-BOOKING-") for response in harness.codes)
    assert await harness.rows(Reservation) == []
    assert await harness.rows(Handoff) == []


@pytest.mark.parametrize("catalog", [PROPOSAL_CATALOG, ROMANTIC_CATALOG])
async def test_g3_explicit_human_after_catalog_precedes_plan_fallback(
    harness: Harness, tmp_path: Path, catalog: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, catalog)
    await send(harness, "quiero hablar con un asesor")
    conversation = await harness.conversation()
    assert conversation.state == "WAITING_FOR_HUMAN"
    handoffs = await harness.rows(Handoff)
    assert len(handoffs) == 1
    assert handoffs[0].reason == "CUSTOMER_REQUEST"
    assert harness.classifier_calls == []
    assert await harness.rows(AIExecution) == []
    assert code("PLAN") not in harness.codes
    assert await harness.rows(Reservation) == []


@pytest.mark.parametrize(
    "message,category,expected_response",
    [
        ("¿Dónde están ubicados?", "ubicacion", "RESP-LOCATION-001"),
        ("quiero informacion de la ubicacion", "ubicacion", "RESP-LOCATION-001"),
        ("¿Cuáles son los horarios?", "horarios", "RESP-EVENT-HOURS-001"),
        ("quiero informacion de horarios", "horarios", "RESP-EVENT-HOURS-001"),
        ("espacios", "espacios", "RESP-SPACES-001"),
        ("servicios", "servicios", "RESP-SERVICES-001"),
        ("seguridad", "seguridad", "RESP-SECURITY-001"),
        ("aceptan tarjetas", "pagos", "RESP-PAYMENT-METHODS-001"),
        ("Me compartes el PDF de esa experiencia", "catalog_request", None),
    ],
)
async def test_g3_faq_or_pdf_after_catalog_keeps_classifier_route(
    harness: Harness,
    tmp_path: Path,
    message: str,
    category: str,
    expected_response: str | None,
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    classification = json.loads(classifier_output(catalog=False))
    classification["information_category"] = category
    await send(harness, message, output=json.dumps(classification))
    executions = await harness.rows(AIExecution)
    assert len(harness.classifier_calls) == len(executions) == 1
    assert executions[0].parsed_output == classification
    if expected_response:
        assert expected_response in harness.codes
    assert code("PLAN") not in harness.codes
    assert (await harness.conversation()).pending_action not in BOOKING_ACTIONS
    assert await harness.rows(Handoff) == []
    assert await harness.rows(Reservation) == []


@pytest.mark.parametrize("message", ["plan desconocido?", "el de otro nombre?"])
async def test_g3_unknown_plan_with_question_mark_stays_in_selection(
    harness: Harness, tmp_path: Path, message: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    await send(harness, message)
    await assert_plan_options(harness, "PROPOSAL")


async def test_g3_repeated_unknown_catalog_choices_never_handoff(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    for message in (
        "me interesa un plan desconocido",
        "plan inexistente",
        "me interesa Confesión bajo la Luna o Noche Inolvidable",
    ):
        await send(harness, message)
        await assert_plan_options(harness, "PROPOSAL")


@pytest.mark.parametrize(
    "message",
    [
        "me interesa un plan desconocido para el 14",
        "me interesa Confesión bajo la Luna o Noche Inolvidable para el 14",
        "Confesión bajo la Luna o Noche Inolvidable para el 14",
    ],
)
async def test_g3_unknown_or_ambiguous_plan_with_date_keeps_selection_and_candidate(
    harness: Harness, tmp_path: Path, message: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    await send(harness, message)
    await assert_plan_options(harness, "PROPOSAL")
    draft = draft_of(await harness.conversation())
    assert draft.get("date") == "2026-10-14"
    assert draft.get("date_confirmation") is True


async def test_g3_catalog_with_date_replay_and_repeat_preserve_single_pdf_and_context(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    payload = await send(harness, INCIDENT_T1)
    initial = await harness.conversation()
    initial_draft = deepcopy(draft_of(initial))
    lead_id = initial.active_lead_id
    assert initial_draft["date"] == "2026-10-14"
    assert initial_draft["date_confirmation"] is True
    outbox_ids = [row.id for row in await harness.rows(Outbox)]
    message_ids = [row.id for row in await harness.rows(Message)]

    await process_whatsapp_webhook(payload, harness.db)
    await harness.assert_completed()
    assert [row.id for row in await harness.rows(Outbox)] == outbox_ids
    assert [row.id for row in await harness.rows(Message)] == message_ids
    assert draft_of(await harness.conversation()) == initial_draft

    await send(harness, PROPOSAL_CATALOG + " para el 14")
    conversation = await harness.conversation()
    assert conversation.active_lead_id == lead_id
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None
    assert draft_of(conversation) == initial_draft
    assert len(await harness.rows(Lead)) == len(await harness.rows(Event)) == 1
    assert len(await harness.rows(CatalogSend)) == 1
    assert len([row for row in await harness.rows(Outbox) if row.message_kind == "DOCUMENT"]) == 1
    await assert_no_ai_or_handoff(harness)


async def test_g3_plan_turn_replay_preserves_draft_and_single_response(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, INCIDENT_T1)
    payload = await send(harness, INCIDENT_T2)
    await assert_selected_plan(harness, "CONFESION_LUNA")
    conversation = await harness.conversation()
    draft = deepcopy(draft_of(conversation))
    marker = (conversation.state, conversation.pending_action, conversation.last_question_code)
    outbox_ids = [row.id for row in await harness.rows(Outbox)]
    message_ids = [row.id for row in await harness.rows(Message)]
    await process_whatsapp_webhook(payload, harness.db)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert (
        conversation.state,
        conversation.pending_action,
        conversation.last_question_code,
    ) == marker
    assert draft_of(conversation) == draft
    assert [row.id for row in await harness.rows(Outbox)] == outbox_ids
    assert [row.id for row in await harness.rows(Message)] == message_ids
    assert len(await harness.rows(Lead)) == len(await harness.rows(Event)) == 1
    await assert_no_ai_or_handoff(harness)


@pytest.mark.parametrize(
    "message,classifier_calls",
    [(INCIDENT_T2, 1), ("quiero reservar confesión bajo la luna", 0)],
)
async def test_g3_disabled_self_service_preserves_previous_human_route(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    classifier_calls: int,
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "false")
    get_settings.cache_clear()
    output = json.dumps(
        dict(
            valid_classification(),
            primary_intent="HUMAN_REQUEST",
            confidence=0.95,
            requested_action="CREATE_HANDOFF",
            needs_human=True,
            handoff_reason="RESERVATION_CONFIRMATION",
        )
    )
    await send(harness, message, output=output)
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert len(await harness.rows(Handoff)) == 1
    assert len(harness.classifier_calls) == len(await harness.rows(AIExecution)) == classifier_calls
    assert code("PLAN") not in harness.codes
    assert await harness.rows(Reservation) == []


@pytest.mark.parametrize("state", ["WAITING_FOR_HUMAN", "HUMAN_ACTIVE"])
async def test_g3_paused_catalog_conversation_stays_silent_on_plan_name(
    harness: Harness, tmp_path: Path, state: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, INCIDENT_T1)
    before = await harness.conversation()
    draft = deepcopy(draft_of(before))
    outbox_ids = [row.id for row in await harness.rows(Outbox)]
    async with harness.db.begin() as session:
        conversation = await session.get(Conversation, before.id)
        assert conversation is not None
        conversation.state = state
    await send(harness, INCIDENT_T2)
    conversation = await harness.conversation()
    assert conversation.state == state
    assert draft_of(conversation) == draft
    assert [row.id for row in await harness.rows(Outbox)] == outbox_ids
    assert harness.codes == []
    assert await harness.rows(Reservation) == []
    assert await harness.rows(Handoff) == []

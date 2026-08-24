from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.models import AIExecution
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.audit.models import AuditEvent
from app.channel import inbound as inbound_module
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.channel.states import Channel
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    configure_test_environment,
    reset_test_database,
    whatsapp_message_payload,
)

PHONE = "+573001112233"
RESCUE_HELPER_NAME = "uncertain_event_type_entity_rescue_classification"

# R-B2-5: verbatim JSON values from production ai_execution row 3120.
ROW_3120_INPUT_PAYLOAD_TEXT = """{"context": {"last_intent": "GREETING", "known_fields": {}, "pending_action": null, "last_question_code": "RESP-GREETING-001", "pending_confirmation": null, "failed_understanding_count": 0}, "message_text": "La boda"}"""  # noqa: E501
ROW_3120_PARSED_OUTPUT_TEXT = """{"entities": {}, "priority": "NORMAL", "confidence": 0.65, "sub_intent": null, "needs_human": false, "handoff_reason": null, "missing_fields": [], "primary_intent": "EVENT_INFORMATION", "reasoning_code": "CONTEXTUAL_EVENT_TYPE", "requested_action": null, "context_reference": {"pending_action": null, "last_question_code": "RESP-GREETING-001"}, "secondary_intents": [], "extracted_entities": [{"entity": "event_type", "raw_value": "boda", "confidence": 0.9, "quality_status": "PROVIDED", "normalized_value": "wedding", "validation_errors": [], "needs_confirmation": false}], "needs_confirmation": false, "information_category": null}"""  # noqa: E501
ROW_3120_INPUT_PAYLOAD: dict[str, Any] = json.loads(ROW_3120_INPUT_PAYLOAD_TEXT)
ROW_3120_PARSED_OUTPUT: dict[str, Any] = json.loads(ROW_3120_PARSED_OUTPUT_TEXT)


@pytest.fixture
async def sessionmaker_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await configure_test_environment(monkeypatch)
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    yield sessionmaker


def event_type_entity(
    *,
    confidence: float = 0.9,
    normalized_value: str = "wedding",
    quality_status: str = "PROVIDED",
    needs_confirmation: bool = False,
) -> ExtractedEntity:
    return ExtractedEntity.model_validate(
        {
            "entity": "event_type",
            "raw_value": "boda",
            "normalized_value": normalized_value,
            "quality_status": quality_status,
            "confidence": confidence,
            "needs_confirmation": needs_confirmation,
            "validation_errors": [],
        }
    )


def uncertain_classification(
    *,
    intent: str = "EVENT_INFORMATION",
    global_confidence: float = 0.65,
    entity: ExtractedEntity | None = None,
    needs_human: bool = False,
    handoff_reason: str | None = None,
) -> IntentClassification:
    return IntentClassification.model_validate(
        {
            "entities": {},
            "priority": "NORMAL",
            "confidence": global_confidence,
            "sub_intent": None,
            "needs_human": needs_human,
            "handoff_reason": handoff_reason,
            "missing_fields": [],
            "primary_intent": intent,
            "reasoning_code": "CONTEXTUAL_EVENT_TYPE",
            "requested_action": None,
            "context_reference": {
                "pending_action": None,
                "last_question_code": "RESP-GREETING-001",
            },
            "secondary_intents": [],
            "extracted_entities": [entity or event_type_entity()],
            "needs_confirmation": False,
            "information_category": None,
        }
    )


async def seed_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    last_question_code: str = "RESP-GREETING-001",
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
                last_intent="GREETING",
                pending_action=None,
                last_question_code=last_question_code,
                pending_confirmation=None,
                failed_understanding_count=0,
            )
            session.add(conversation)
            await session.flush()
            return conversation.id


async def seed_row_3120(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
    request_id: UUID,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            session.add(
                AIExecution(
                    task="INTENT_CLASSIFICATION",
                    model="openai/test-model",
                    latency_ms=123,
                    success=True,
                    error_reason=None,
                    prompt_version="intent_v4",
                    conversation_id=conversation_id,
                    input_character_count=len("La boda"),
                    request_id=request_id,
                    external_message_id="tc-b2-001",
                    input_payload=ROW_3120_INPUT_PAYLOAD,
                    raw_output=ROW_3120_PARSED_OUTPUT_TEXT,
                    parsed_output=ROW_3120_PARSED_OUTPUT,
                    validation_status="VALID",
                    error=None,
                )
            )


async def send_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    message_id: str,
    text: str = "La boda",
    request_id: UUID | None = None,
) -> None:
    payload = json.loads(
        whatsapp_message_payload(
            message_id,
            phone=PHONE.removeprefix("+"),
            text=text,
        ).decode()
    )
    await process_whatsapp_webhook(
        payload,
        sessionmaker,
        request_id=request_id or uuid4(),
    )


async def conversation_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
) -> Conversation:
    async with sessionmaker() as session:
        conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    return conversation


async def rescue_audits(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[AuditEvent]:
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.action == "AI_CONFIDENCE_DECISION")
                .order_by(AuditEvent.id)
            )
        )
    return [
        row
        for row in rows
        if (row.new_value or {}).get("decision") == "UNCERTAIN_ENTITY_RESCUE"
    ]


def assert_rescue_contract_is_available() -> None:
    assert callable(getattr(inbound_module, RESCUE_HELPER_NAME, None)), (
        "PR-B.2 must expose the bounded deterministic rescue helper"
    )


@pytest.mark.asyncio
async def test_tc_b2_001_replays_literal_row_3120_and_rescues_strong_entity(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = uuid4()
    conversation_id = await seed_conversation(sessionmaker_fixture)
    await seed_row_3120(sessionmaker_fixture, conversation_id, request_id)

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return IntentClassification.model_validate(ROW_3120_PARSED_OUTPUT)

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-b2-001",
        request_id=request_id,
    )

    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
        execution = await session.scalar(
            select(AIExecution).where(AIExecution.external_message_id == "tc-b2-001")
        )
    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    audits = await rescue_audits(sessionmaker_fixture)

    assert event is not None
    assert event.event_type == "WEDDING"
    assert conversation.pending_action == "COLLECT_GUEST_COUNT"
    assert conversation.last_question_code == "RESP-EVENT-DATA-004"
    assert conversation.last_intent == "EVENT_INFORMATION"
    assert execution is not None
    assert execution.input_payload == ROW_3120_INPUT_PAYLOAD
    assert execution.parsed_output == ROW_3120_PARSED_OUTPUT
    assert execution.parsed_output["confidence"] == 0.65
    assert len(audits) == 1
    assert audits[0].request_id == str(request_id)
    assert audits[0].new_value == {
        "conversation_id": conversation_id,
        "decision": "UNCERTAIN_ENTITY_RESCUE",
        "original_global_confidence": 0.65,
        "rescued_entity_confidence": 0.9,
        "last_question_code": "RESP-GREETING-001",
        "original_reasoning_code": "CONTEXTUAL_EVENT_TYPE",
    }
    assert_rescue_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b2_002_rejects_entity_confidence_below_safe(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_conversation(sessionmaker_fixture)

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return uncertain_classification(entity=event_type_entity(confidence=0.7))

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    await send_turn(sessionmaker_fixture, message_id="tc-b2-002")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert event is None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert conversation.pending_confirmation is not None
    assert await rescue_audits(sessionmaker_fixture) == []
    assert_rescue_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b2_003_rejects_uncertain_entity_outside_directed_position(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_conversation(
        sessionmaker_fixture,
        last_question_code="RESP-LOCATION-001",
    )

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return uncertain_classification()

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    await send_turn(sessionmaker_fixture, message_id="tc-b2-003")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert event is None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert await rescue_audits(sessionmaker_fixture) == []
    assert_rescue_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b2_004_probable_classification_uses_normal_trusted_path(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_conversation(sessionmaker_fixture)

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return uncertain_classification(global_confidence=0.7)

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    await send_turn(sessionmaker_fixture, message_id="tc-b2-004")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert event is not None and event.event_type == "WEDDING"
    assert conversation.pending_action == "COLLECT_GUEST_COUNT"
    assert conversation.last_question_code == "RESP-EVENT-DATA-004"
    assert await rescue_audits(sessionmaker_fixture) == []
    assert_rescue_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b2_005_rejects_non_normalizable_event_type(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_conversation(sessionmaker_fixture)

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return uncertain_classification(
            entity=event_type_entity(normalized_value="evento marciano")
        )

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    await send_turn(sessionmaker_fixture, message_id="tc-b2-005")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert event is None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert await rescue_audits(sessionmaker_fixture) == []
    assert_rescue_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b2_006_sensitive_intent_is_never_reinterpreted(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_conversation(sessionmaker_fixture)

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return uncertain_classification(
            intent="PAYMENT_MESSAGE",
            needs_human=True,
            handoff_reason="PAYMENT_REVIEW",
        )

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    await send_turn(sessionmaker_fixture, message_id="tc-b2-006", text="Ya pagué")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
        handoff = await session.scalar(select(Handoff))
    assert event is None
    assert handoff is None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert conversation.pending_confirmation is not None
    assert conversation.pending_confirmation["original_intent"] == "PAYMENT_MESSAGE"
    assert await rescue_audits(sessionmaker_fixture) == []
    assert_rescue_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b2_007_rejects_inferred_event_type(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_conversation(sessionmaker_fixture)

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return uncertain_classification(
            entity=event_type_entity(quality_status="INFERRED")
        )

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    await send_turn(sessionmaker_fixture, message_id="tc-b2-007")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert event is None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert await rescue_audits(sessionmaker_fixture) == []
    assert_rescue_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b2_008_rejects_entity_that_needs_confirmation(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await seed_conversation(sessionmaker_fixture)

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return uncertain_classification(
            entity=event_type_entity(needs_confirmation=True)
        )

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    await send_turn(sessionmaker_fixture, message_id="tc-b2-008")

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
        outbox = await session.scalar(
            select(Outbox).where(Outbox.conversation_id == conversation_id)
        )
    assert event is None
    assert outbox is not None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert await rescue_audits(sessionmaker_fixture) == []
    assert_rescue_contract_is_available()

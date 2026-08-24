from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import fields, is_dataclass
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.models import AIExecution
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.knowledge import render_response
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.orchestrator import service as orchestrator_module
from app.orchestrator.service import OrchestrationInput, orchestrate_inbound_message
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import DATABASE_URL, reset_test_database

PHONE = "+573001112233"


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    yield sessionmaker


@pytest.fixture
def settings() -> Settings:
    return Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-meta-access-token",
        OPENROUTER_API_KEY="test-openrouter-key",
        ENVIRONMENT="testing",
        _env_file=None,
    )


def event_type_entity(event_type: str = "WEDDING") -> ExtractedEntity:
    return ExtractedEntity(
        entity="event_type",
        raw_value="boda",
        normalized_value=event_type,
        quality_status="PROVIDED",
        confidence=0.9,
        needs_confirmation=False,
        validation_errors=[],
    )


def classification(
    intent: str,
    *,
    confidence: float = 0.91,
    extracted_entities: list[ExtractedEntity] | None = None,
    information_category: str | None = None,
    needs_human: bool = False,
    handoff_reason: str | None = None,
    priority: str = "NORMAL",
    reasoning_code: str = "TC_B3_FRESH",
) -> IntentClassification:
    return IntentClassification.model_validate(
        {
            "primary_intent": intent,
            "secondary_intents": [],
            "sub_intent": None,
            "confidence": confidence,
            "information_category": information_category,
            "entities": {},
            "extracted_entities": extracted_entities or [],
            "requested_action": None,
            "missing_fields": [],
            "needs_confirmation": False,
            "needs_human": needs_human,
            "handoff_reason": handoff_reason,
            "priority": priority,
            "context_reference": {},
            "reasoning_code": reasoning_code,
        }
    )


def stored_event_classification() -> IntentClassification:
    return classification(
        "EVENT_INFORMATION",
        confidence=0.65,
        extracted_entities=[event_type_entity()],
        reasoning_code="TC_B3_STORED_EVENT",
    )


def pending_payload(stored: IntentClassification) -> dict[str, Any]:
    return {
        "classification": stored.model_dump(mode="json"),
        "original_intent": stored.primary_intent,
        "original_confidence": stored.confidence,
        "entities": stored.entities,
    }


async def seed_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    stored: IntentClassification | None = None,
) -> int:
    fallback_body = (
        await render_response(sessionmaker, "RESP-FALLBACK-004", {})
        if stored is not None
        else None
    )
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
                last_intent=stored.primary_intent if stored is not None else "GREETING",
                pending_action="CLASSIFY_MESSAGE" if stored is not None else None,
                last_question_code=(
                    "RESP-FALLBACK-004" if stored is not None else "RESP-GREETING-001"
                ),
                pending_confirmation=(
                    pending_payload(stored) if stored is not None else None
                ),
                failed_understanding_count=0,
            )
            session.add(conversation)
            await session.flush()

            if stored is not None:
                original_message = Message(
                    external_message_id=f"seed-b3-{uuid4().hex}",
                    conversation_id=conversation.id,
                    customer_id=customer.id,
                    channel=Channel.WHATSAPP,
                    direction="INBOUND",
                    message_type="text",
                    content={"text": {"body": "Es una boda"}},
                    provider_timestamp=None,
                )
                session.add(original_message)
                await session.flush()
                session.add(
                    Outbox(
                        conversation_id=conversation.id,
                        message_id=original_message.id,
                        channel=Channel.WHATSAPP,
                        recipient_phone_number=customer.phone_number,
                        payload={"type": "text", "text": {"body": fallback_body}},
                        status="PENDING",
                    )
                )
                session.add(
                    AuditEvent(
                        actor="SYSTEM",
                        action="AI_CONFIDENCE_DECISION",
                        entity="conversation",
                        old_value=None,
                        new_value={
                            "conversation_id": conversation.id,
                            "original_intent": stored.primary_intent,
                            "original_confidence": stored.confidence,
                            "threshold": 0.7,
                            "decision": "ASK_CONFIRMATION",
                        },
                        reason="ASK_CONFIRMATION",
                        request_id="req-b3-original",
                    )
                )
            return conversation.id


async def orchestrate_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    conversation_id: int,
    *,
    message_id: str,
    text: str,
    fresh: IntentClassification,
    request_id: str,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            conversation = await session.get(
                Conversation,
                conversation_id,
                with_for_update=True,
            )
            assert conversation is not None
            customer = await session.get(Customer, conversation.customer_id)
            assert customer is not None
            message = Message(
                external_message_id=message_id,
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": text}},
                provider_timestamp=None,
            )
            session.add(message)
            await session.flush()
            await orchestrate_inbound_message(
                session,
                settings,
                sessionmaker,
                OrchestrationInput(
                    conversation=conversation,
                    customer=customer,
                    inbound_message=message,
                    message_text=text,
                    request_id=request_id,
                ),
                classification=fresh,
            )


async def conversation_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
) -> Conversation:
    async with sessionmaker() as session:
        conversation = await session.get(Conversation, conversation_id)
    assert conversation is not None
    return conversation


async def audit_rows(
    sessionmaker: async_sessionmaker[AsyncSession],
    action: str,
) -> list[AuditEvent]:
    async with sessionmaker() as session:
        return list(
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.action == action)
                .order_by(AuditEvent.id)
            )
        )


async def decision_audits(
    sessionmaker: async_sessionmaker[AsyncSession],
    decision: str,
) -> list[AuditEvent]:
    return [
        row
        for row in await audit_rows(sessionmaker, "AI_CONFIDENCE_DECISION")
        if (row.new_value or {}).get("decision") == decision
    ]


async def outbox_bodies(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
) -> list[str]:
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(
                select(Outbox)
                .where(Outbox.conversation_id == conversation_id)
                .order_by(Outbox.id)
            )
        )
    return [str(row.payload["text"]["body"]) for row in rows]


def assert_resolution_contract_is_available() -> None:
    contract = getattr(orchestrator_module, "PendingConfirmationResolution", None)
    assert contract is not None and is_dataclass(contract), (
        "PR-B.3 must expose the structured pending-confirmation result"
    )
    assert {field.name for field in fields(contract)} == {
        "classification",
        "confirmation_uplifted",
    }


@pytest.mark.asyncio
async def test_tc_b3_001_confirmed_uncertain_event_dispatches_once_with_uplift(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await seed_conversation(
        sessionmaker_fixture,
        stored=stored_event_classification(),
    )
    request_id = "req-b3-001-confirm"

    await orchestrate_turn(
        sessionmaker_fixture,
        settings,
        conversation_id,
        message_id="tc-b3-001-confirm",
        text="sí",
        fresh=classification("UNKNOWN"),
        request_id=request_id,
    )

    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    accepted = await audit_rows(sessionmaker_fixture, "AI_CONFIRMATION_ACCEPTED")
    uplift = await decision_audits(sessionmaker_fixture, "CONFIRMATION_UPLIFT")
    ask_confirmation = await decision_audits(sessionmaker_fixture, "ASK_CONFIRMATION")
    fallback_body = await render_response(
        sessionmaker_fixture,
        "RESP-FALLBACK-004",
        {},
    )

    assert event is not None and event.event_type == "WEDDING"
    assert conversation.pending_confirmation is None
    assert conversation.pending_action == "COLLECT_GUEST_COUNT"
    assert conversation.last_question_code == "RESP-EVENT-DATA-004"
    assert len(accepted) == 1
    assert len(ask_confirmation) == 1
    assert (await outbox_bodies(sessionmaker_fixture, conversation_id)).count(
        fallback_body
    ) == 1
    assert len(uplift) == 1
    assert uplift[0].reason == "CONFIRMATION_UPLIFT"
    assert uplift[0].request_id == request_id
    assert uplift[0].new_value == {
        "conversation_id": conversation_id,
        "decision": "CONFIRMATION_UPLIFT",
        "confirmed_intent": "EVENT_INFORMATION",
        "original_global_confidence": 0.65,
        "original_reasoning_code": "TC_B3_STORED_EVENT",
        "last_question_code": "RESP-FALLBACK-004",
    }


@pytest.mark.asyncio
async def test_tc_b3_002_second_yes_without_pending_is_fresh_and_not_reuplifted(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await seed_conversation(
        sessionmaker_fixture,
        stored=stored_event_classification(),
    )
    await orchestrate_turn(
        sessionmaker_fixture,
        settings,
        conversation_id,
        message_id="tc-b3-002-first",
        text="sí",
        fresh=classification("UNKNOWN"),
        request_id="req-b3-002-first",
    )
    await orchestrate_turn(
        sessionmaker_fixture,
        settings,
        conversation_id,
        message_id="tc-b3-002-second",
        text="sí",
        fresh=classification(
            "GENERAL_INFORMATION",
            information_category="parqueadero",
        ),
        request_id="req-b3-002-second",
    )

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert event is not None and event.event_type == "WEDDING"
    assert conversation.pending_confirmation is None
    assert conversation.pending_action == "COLLECT_GUEST_COUNT"
    assert conversation.last_question_code == "RESP-PARKING-001"
    assert len(await audit_rows(sessionmaker_fixture, "AI_CONFIRMATION_ACCEPTED")) == 1
    assert len(await decision_audits(sessionmaker_fixture, "CONFIRMATION_UPLIFT")) == 1


@pytest.mark.asyncio
async def test_tc_b3_003_non_affirmative_discards_pending_and_fresh_turn_governs(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await seed_conversation(
        sessionmaker_fixture,
        stored=stored_event_classification(),
    )
    await orchestrate_turn(
        sessionmaker_fixture,
        settings,
        conversation_id,
        message_id="tc-b3-003",
        text="es para diciembre",
        fresh=classification("UNKNOWN"),
        request_id="req-b3-003",
    )

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        event = await session.scalar(select(Event))
    assert event is None
    assert conversation.pending_confirmation is None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-001"
    assert len(await audit_rows(sessionmaker_fixture, "AI_CONFIRMATION_DISCARDED")) == 1
    assert await decision_audits(sessionmaker_fixture, "CONFIRMATION_UPLIFT") == []
    assert_resolution_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b3_004_confirmed_uncertain_emergency_reaches_sensitive_flow(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    stored = classification(
        "EMERGENCY",
        confidence=0.6,
        needs_human=True,
        handoff_reason="URGENT_EVENT",
        priority="CRITICAL",
        reasoning_code="TC_B3_STORED_EMERGENCY",
    )
    conversation_id = await seed_conversation(sessionmaker_fixture, stored=stored)
    await orchestrate_turn(
        sessionmaker_fixture,
        settings,
        conversation_id,
        message_id="tc-b3-004",
        text="sí",
        fresh=classification("UNKNOWN"),
        request_id="req-b3-004",
    )

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    async with sessionmaker_fixture() as session:
        handoff = await session.scalar(select(Handoff))
    uplift = await decision_audits(sessionmaker_fixture, "CONFIRMATION_UPLIFT")
    assert handoff is not None
    assert handoff.reason == "URGENT_EVENT"
    assert handoff.priority == "CRITICAL"
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN.value
    assert conversation.pending_action == "WAIT_FOR_HUMAN"
    assert conversation.pending_confirmation is None
    assert len(uplift) == 1
    assert uplift[0].new_value["confirmed_intent"] == "EMERGENCY"
    assert uplift[0].new_value["original_global_confidence"] == 0.6
    assert len(await decision_audits(sessionmaker_fixture, "ASK_CONFIRMATION")) == 1


@pytest.mark.asyncio
async def test_tc_b3_005_fresh_uncertain_classification_keeps_existing_band_gate(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await seed_conversation(sessionmaker_fixture)
    await orchestrate_turn(
        sessionmaker_fixture,
        settings,
        conversation_id,
        message_id="tc-b3-005",
        text="quiero saber algo",
        fresh=classification(
            "GENERAL_INFORMATION",
            confidence=0.65,
            information_category="parqueadero",
        ),
        request_id="req-b3-005",
    )

    conversation = await conversation_snapshot(sessionmaker_fixture, conversation_id)
    assert conversation.pending_confirmation is not None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert len(await decision_audits(sessionmaker_fixture, "ASK_CONFIRMATION")) == 1
    assert await decision_audits(sessionmaker_fixture, "CONFIRMATION_UPLIFT") == []
    assert_resolution_contract_is_available()


@pytest.mark.asyncio
async def test_tc_b3_006_ai_execution_rows_remain_literal_after_backend_uplift(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    stored = stored_event_classification()
    fresh = classification("UNKNOWN", reasoning_code="TC_B3_AFFIRMATIVE_LLM")
    conversation_id = await seed_conversation(sessionmaker_fixture, stored=stored)
    original_input = {
        "message_text": "Es una boda",
        "context": {"pending_action": None, "last_question_code": "RESP-GREETING-001"},
    }
    affirmative_input = {
        "message_text": "sí",
        "context": {
            "pending_action": "CLASSIFY_MESSAGE",
            "last_question_code": "RESP-FALLBACK-004",
        },
    }
    original_output = stored.model_dump(mode="json")
    affirmative_output = fresh.model_dump(mode="json")
    expected_rows = [
        (original_input, original_output),
        (affirmative_input, affirmative_output),
    ]

    async with sessionmaker_fixture() as session:
        async with session.begin():
            for index, (input_payload, parsed_output) in enumerate(expected_rows, start=1):
                session.add(
                    AIExecution(
                        task="INTENT_CLASSIFICATION",
                        model="openai/test-model",
                        latency_ms=100 + index,
                        success=True,
                        error_reason=None,
                        prompt_version="intent_v4",
                        conversation_id=conversation_id,
                        input_character_count=len(str(input_payload["message_text"])),
                        request_id=uuid4(),
                        external_message_id=f"tc-b3-006-ai-{index}",
                        input_payload=input_payload,
                        raw_output=json.dumps(parsed_output),
                        parsed_output=parsed_output,
                        validation_status="VALID",
                        error=None,
                    )
                )

    await orchestrate_turn(
        sessionmaker_fixture,
        settings,
        conversation_id,
        message_id="tc-b3-006-confirm",
        text="sí",
        fresh=fresh,
        request_id="req-b3-006",
    )

    async with sessionmaker_fixture() as session:
        rows = list(await session.scalars(select(AIExecution).order_by(AIExecution.id)))
    assert [(row.input_payload, row.parsed_output) for row in rows] == expected_rows
    assert rows[0].parsed_output["confidence"] == 0.65
    assert rows[1].parsed_output["reasoning_code"] == "TC_B3_AFFIRMATIVE_LLM"
    assert len(await decision_audits(sessionmaker_fixture, "CONFIRMATION_UPLIFT")) == 1

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.models import AIExecution
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.channel.inbound import process_whatsapp_webhook
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    DATABASE_URL,
    configure_test_environment,
    reset_test_database,
    whatsapp_message_payload,
)

PHONE = "+573001112233"
ORIGINAL_CLASSIFY_INTENT = OpenRouterIntentClient.classify_intent


@pytest.fixture
async def sessionmaker_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await configure_test_environment(monkeypatch)
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
        OPENROUTER_MODEL_INTENT="openai/test-model",
        OPENROUTER_TIMEOUT_SECONDS=0.2,
        OPENROUTER_MAX_RETRIES=0,
        AI_PROMPT_VERSION="intent_v4",
        ENVIRONMENT="testing",
        _env_file=None,
    )


def completion_payload(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-event-type-test",
        "choices": [{"message": {"role": "assistant", "content": json.dumps(arguments)}}],
    }


def classification(
    entity: ExtractedEntity | None = None,
    *,
    intent: str = "EVENT_INFORMATION",
) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        information_category=None,
        entities={},
        extracted_entities=[entity] if entity is not None else [],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TC_PR_B_EVENT_TYPE",
    )


def event_type_entity(raw_value: str, normalized_value: str) -> ExtractedEntity:
    return ExtractedEntity(
        entity="event_type",
        raw_value=raw_value,
        normalized_value=normalized_value,
        quality_status="PROVIDED",
        confidence=0.95,
        needs_confirmation=False,
        validation_errors=[],
    )


async def seed_event_type_pending(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Event:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=PHONE, full_name="Natalia Pérez")
            session.add(customer)
            await session.flush()
            lead = Lead(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                lead_status="QUALIFYING",
                budget_data_status="NOT_ASKED",
            )
            session.add(lead)
            await session.flush()
            event = Event(lead_id=lead.lead_id)
            session.add(event)
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.COLLECTING_EVENT_DATA,
                active_lead_id=lead.lead_id,
                pending_action="COLLECT_EVENT_TYPE",
                pending_fields=["event_type"],
                last_question_code="RESP-EVENT-DATA-013",
            )
            session.add(conversation)
            await session.flush()
            return event


async def send_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    message_id: str,
    text: str,
) -> None:
    payload = json.loads(
        whatsapp_message_payload(
            message_id,
            phone=PHONE.removeprefix("+"),
            text=text,
        ).decode()
    )
    await process_whatsapp_webhook(payload, sessionmaker, request_id=uuid4())


async def current_event_type(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> str | None:
    async with sessionmaker() as session:
        event = await session.scalar(select(Event))
    assert event is not None
    return event.event_type


@pytest.mark.asyncio
@respx.mock
async def test_tc_ext_001_phrase_uses_directed_extraction_and_records_normalized(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload({"event_type": "boda"}))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        result = await client.extract_event_type(
            "la boda de siglo que quiero realizar",
            context={"pending_action": "COLLECT_EVENT_TYPE"},
            request_id=uuid4(),
        )

    async with sessionmaker_fixture() as session:
        execution = await session.scalar(
            select(AIExecution).where(AIExecution.task == "EVENT_TYPE_EXTRACTION")
        )
    assert result == "WEDDING"
    assert execution is not None
    assert execution.validation_status == "NORMALIZED"
    assert execution.prompt_version == "event_type_extraction_v1"


@pytest.mark.asyncio
@respx.mock
async def test_tc_ext_002_unknown_extraction_is_discarded_without_domain_contamination(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    raw_value = "fiesta intergaláctica"
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload({"event_type": raw_value}))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        result = await client.extract_event_type(
            "quiero algo nunca visto",
            context={"pending_action": "COLLECT_EVENT_TYPE"},
            request_id=uuid4(),
        )

    async with sessionmaker_fixture() as session:
        execution = await session.scalar(
            select(AIExecution).where(AIExecution.task == "EVENT_TYPE_EXTRACTION")
        )
        events = list(await session.scalars(select(Event)))
    assert result is None
    assert execution is not None
    assert execution.validation_status == "DISCARDED"
    assert events == []
    assert execution.parsed_output == {"event_type": raw_value}


@pytest.mark.asyncio
@respx.mock
async def test_tc_ext_003_civil_wedding_does_not_collapse_to_wedding(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=completion_payload({"event_type": "boda civil"}))
    )

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        result = await client.extract_event_type(
            "quiero celebrar mi boda civil",
            context={"pending_action": "COLLECT_EVENT_TYPE"},
            request_id=uuid4(),
        )

    assert result == "CIVIL_WEDDING"


@pytest.mark.asyncio
async def test_tc_ext_004_pending_event_without_valid_general_entity_triggers_extraction(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_event_type_pending(sessionmaker_fixture)
    extraction_calls: list[tuple[str, dict[str, Any]]] = []

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification(intent="EVENT_INFORMATION")

    async def extract(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, Any],
        *_args: object,
        **_kwargs: object,
    ) -> str | None:
        extraction_calls.append((message_text, context))
        return "WEDDING"

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "extract_event_type", extract)

    await send_turn(
        sessionmaker_fixture,
        message_id="tc-ext-004",
        text="la boda de siglo que quiero realizar",
    )

    assert len(extraction_calls) == 1
    assert extraction_calls[0][1]["pending_action"] == "COLLECT_EVENT_TYPE"
    assert await current_event_type(sessionmaker_fixture) == "WEDDING"


@pytest.mark.asyncio
async def test_tc_ext_005_valid_general_entity_skips_directed_extraction(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(OpenRouterIntentClient, "_execute_task")
    await seed_event_type_pending(sessionmaker_fixture)
    extraction_calls: list[str] = []

    async def classify_general(*_args: object, **_kwargs: object) -> IntentClassification:
        return classification(event_type_entity("boda", "WEDDING"))

    async def extract(
        _client: OpenRouterIntentClient,
        message_text: str,
        *_args: object,
        **_kwargs: object,
    ) -> str | None:
        extraction_calls.append(message_text)
        return "WEDDING"

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_general)
    monkeypatch.setattr(OpenRouterIntentClient, "extract_event_type", extract)

    await send_turn(sessionmaker_fixture, message_id="tc-ext-005", text="es una boda")

    assert extraction_calls == []
    assert await current_event_type(sessionmaker_fixture) == "WEDDING"


@pytest.mark.asyncio
@respx.mock
async def test_tc_ext_006_each_ai_task_records_its_own_prompt_version(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", ORIGINAL_CLASSIFY_INTENT)
    responses = [
        httpx.Response(200, json=completion_payload({"service_codes": ["VENUE"]})),
        httpx.Response(200, json=completion_payload({"event_type": "boda"})),
        httpx.Response(
            200,
            json=completion_payload(
                {
                    "primary_intent": "GREETING",
                    "secondary_intents": [],
                    "sub_intent": None,
                    "confidence": 0.95,
                    "entities": {},
                    "requested_action": "SEND_GREETING",
                    "missing_fields": [],
                    "needs_confirmation": False,
                    "needs_human": False,
                    "handoff_reason": None,
                    "priority": "NORMAL",
                    "context_reference": {},
                    "reasoning_code": "TC_EXT_006",
                }
            ),
        ),
    ]
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=responses)

    async with OpenRouterIntentClient(settings, sessionmaker_fixture) as client:
        await client.classify_services(
            "solo espacio",
            context={"pending_action": "COLLECT_SERVICES"},
            request_id=uuid4(),
        )
        await client.extract_event_type(
            "es una boda",
            context={"pending_action": "COLLECT_EVENT_TYPE"},
            request_id=uuid4(),
        )
        await client.classify_intent("hola", context={}, request_id=uuid4())

    async with sessionmaker_fixture() as session:
        executions = list(await session.scalars(select(AIExecution).order_by(AIExecution.id)))
    versions = {execution.task: execution.prompt_version for execution in executions}
    assert versions == {
        "SERVICES_CLASSIFICATION": "services_v1",
        "EVENT_TYPE_EXTRACTION": "event_type_extraction_v1",
        "INTENT_CLASSIFICATION": "intent_v4",
    }

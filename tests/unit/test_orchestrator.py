from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.schemas import IntentClassification
from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.models import Conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.orchestrator.service import OrchestrationInput, orchestrate_inbound_message
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import DATABASE_URL, reset_test_database


@dataclass
class StaticClassifier:
    result: IntentClassification | AIUnavailable

    async def classify_intent(
        self,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> IntentClassification:
        if isinstance(self.result, AIUnavailable):
            raise self.result
        return self.result


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


def classification(
    intent: str,
    confidence: float = 0.91,
    entities: dict[str, object] | None = None,
    information_category: str | None = None,
    needs_human: bool = False,
    handoff_reason: str | None = None,
    priority: str = "NORMAL",
) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=confidence,
        information_category=information_category,
        entities=entities or {},
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=needs_human,
        handoff_reason=handoff_reason,
        priority=priority,
        context_reference={},
        reasoning_code="TEST",
    )


async def seed_message(
    session: AsyncSession,
    state: ConversationState = ConversationState.BOT_ACTIVE,
    failed_count: int = 0,
) -> tuple[Customer, Conversation, Message]:
    customer = Customer(phone_number="+573001112233")
    session.add(customer)
    await session.flush()
    conversation = Conversation(
        customer_id=customer.id,
        channel=Channel.WHATSAPP,
        state=state,
        failed_understanding_count=failed_count,
    )
    session.add(conversation)
    await session.flush()
    message = Message(
        external_message_id=f"wamid.test.{state.value}.{failed_count}",
        conversation_id=conversation.id,
        customer_id=customer.id,
        channel=Channel.WHATSAPP,
        direction="INBOUND",
        message_type="text",
        content={"text": {"body": "Hola"}},
        provider_timestamp=None,
    )
    session.add(message)
    await session.flush()
    return customer, conversation, message


async def run_orchestrator(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    classifier: StaticClassifier,
    state: ConversationState = ConversationState.BOT_ACTIVE,
    failed_count: int = 0,
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            customer, conversation, message = await seed_message(session, state, failed_count)
            await orchestrate_inbound_message(
                session,
                settings,
                sessionmaker,
                OrchestrationInput(conversation, customer, message, "Hola", "req-test"),
                classification=None
                if isinstance(classifier.result, AIUnavailable)
                else classifier.result,
                ai_error_reason=classifier.result.reason
                if isinstance(classifier.result, AIUnavailable)
                else None,
            )
            return conversation.id


@pytest.mark.asyncio
async def test_ai_unavailable_uses_deterministic_menu(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await run_orchestrator(
        sessionmaker_fixture,
        settings,
        StaticClassifier(AIUnavailable(AIErrorReason.TIMEOUT)),
    )

    async with sessionmaker_fixture() as session:
        outbox = await session.scalar(select(Outbox))
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "AI_UNAVAILABLE")
        )

    assert outbox is not None
    assert "nuestros espacios" in outbox.payload["text"]["body"]
    assert audit is not None


@pytest.mark.asyncio
async def test_human_request_creates_handoff_and_pauses(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await run_orchestrator(
        sessionmaker_fixture,
        settings,
        StaticClassifier(
            classification(
                "HUMAN_REQUEST",
                needs_human=True,
                handoff_reason="CUSTOMER_REQUEST",
            )
        ),
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation_id)
        handoff = await session.scalar(select(Handoff))
        outbox = await session.scalar(select(Outbox))

    assert conversation is not None
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert handoff is not None
    assert handoff.reason == "CUSTOMER_REQUEST"
    assert outbox is not None
    assert "asesor" in outbox.payload["text"]["body"]


@pytest.mark.asyncio
async def test_waiting_for_human_generates_no_auto_response(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await run_orchestrator(
        sessionmaker_fixture,
        settings,
        StaticClassifier(classification("GREETING")),
        state=ConversationState.WAITING_FOR_HUMAN,
    )

    async with sessionmaker_fixture() as session:
        outbox = await session.scalar(select(Outbox))
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "MESSAGE_RECEIVED_DURING_HANDOFF")
        )

    assert outbox is None
    assert audit is not None


@pytest.mark.asyncio
async def test_general_information_without_category_asks_clarification_without_handoff(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await run_orchestrator(
        sessionmaker_fixture,
        settings,
        StaticClassifier(classification("GENERAL_INFORMATION", information_category=None)),
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation_id)
        handoff = await session.scalar(select(Handoff))
        outbox = await session.scalar(select(Outbox))

    assert conversation is not None
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.failed_understanding_count == 1
    assert conversation.last_question_code == "RESP-FALLBACK-001"
    assert handoff is None
    assert outbox is not None
    assert "¿Buscas información" in outbox.payload["text"]["body"]


@pytest.mark.asyncio
async def test_general_information_valid_category_without_answer_escalates(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.orchestrator.service.response_code_for_category",
        lambda category: "NO_APPROVED_ANSWER" if category == "seguridad" else "RESP-TEST",
    )
    await run_orchestrator(
        sessionmaker_fixture,
        settings,
        StaticClassifier(classification("GENERAL_INFORMATION", information_category="seguridad")),
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.scalar(select(Conversation))
        handoff = await session.scalar(select(Handoff))

    assert conversation is not None
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert handoff is not None
    assert handoff.reason == "OTHER"
    assert "seguridad" in handoff.summary

    async with sessionmaker_fixture() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "HANDOFF_CREATED")
        )

    assert audit is not None
    assert audit.new_value["detail"] == "NO_APPROVED_ANSWER category=seguridad"


@pytest.mark.asyncio
async def test_third_unknown_creates_low_confidence_handoff(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await run_orchestrator(
        sessionmaker_fixture,
        settings,
        StaticClassifier(classification("UNKNOWN")),
        failed_count=2,
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation_id)
        handoff = await session.scalar(select(Handoff))
        outbox = await session.scalar(select(Outbox))

    assert conversation is not None
    assert conversation.failed_understanding_count == 3
    assert conversation.state == "WAITING_FOR_HUMAN"
    assert handoff is not None
    assert handoff.reason == "LOW_CONFIDENCE"
    assert outbox is not None
    assert "personalmente" in outbox.payload["text"]["body"]


@pytest.mark.asyncio
async def test_intermediate_confidence_persists_pending_confirmation_and_audit(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    conversation_id = await run_orchestrator(
        sessionmaker_fixture,
        settings,
        StaticClassifier(classification("GENERAL_INFORMATION", confidence=0.65)),
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation_id)
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "AI_CONFIDENCE_DECISION")
        )

    assert conversation is not None
    assert conversation.pending_action == "CLASSIFY_MESSAGE"
    assert conversation.pending_confirmation["original_intent"] == "GENERAL_INFORMATION"
    assert conversation.pending_confirmation["original_confidence"] == 0.65
    assert conversation.last_question_code == "RESP-FALLBACK-004"
    assert audit is not None
    assert audit.new_value["decision"] == "ASK_CONFIRMATION"
    assert audit.new_value["original_confidence"] == 0.65


@pytest.mark.asyncio
async def test_affirmative_message_uses_pending_confirmation(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            customer, conversation, message = await seed_message(session)
            tentative = classification(
                "GENERAL_INFORMATION",
                confidence=0.72,
                information_category="parqueadero",
            )
            conversation.pending_confirmation = {
                "classification": tentative.model_dump(mode="json"),
                "original_intent": tentative.primary_intent,
                "original_confidence": tentative.confidence,
                "entities": tentative.entities,
            }
            await orchestrate_inbound_message(
                session,
                settings,
                sessionmaker_fixture,
                OrchestrationInput(conversation, customer, message, "sí", "req-test"),
                classification("UNKNOWN", confidence=0.91),
            )
            conversation_id = conversation.id

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation_id)
        outbox = await session.scalar(select(Outbox))
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "AI_CONFIRMATION_ACCEPTED")
        )

    assert conversation is not None
    assert conversation.pending_confirmation is None
    assert conversation.last_question_code == "RESP-PARKING-001"
    assert outbox is not None
    assert audit is not None

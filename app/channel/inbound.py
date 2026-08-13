from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.schemas import IntentClassification
from app.audit.models import AuditEvent
from app.channel.models import Message, MessageProviderStatus, Outbox, WebhookEvent
from app.channel.states import Channel
from app.config.settings import get_settings
from app.conversation.confirmation import resolve_contextual_confirmation
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.orchestrator.service import OrchestrationInput, orchestrate_inbound_message

logger = structlog.get_logger(__name__)

ACTIVE_CONVERSATION_EXCLUDED_STATUSES = ("RESOLVED", "CLOSED")
SYSTEM_ACTOR = "SYSTEM"


@dataclass(frozen=True)
class InboundWhatsAppMessage:
    external_message_id: str
    phone_number: str
    message_type: str
    content: dict[str, Any]
    provider_timestamp: datetime | None


@dataclass(frozen=True)
class PersistedInboundMessage:
    message_id: int
    conversation_id: int
    customer_id: int
    message_text: str
    context: dict[str, Any]


def normalize_phone_number(phone_number: str) -> str:
    digits = "".join(character for character in phone_number if character.isdigit())
    if not digits:
        raise ValueError("phone_number must contain at least one digit")
    if phone_number.strip().startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+57{digits}"
    return f"+{digits}"


async def process_whatsapp_webhook(
    payload: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> None:
    persisted_messages = await persist_payload_phase_a(payload, sessionmaker, request_id=request_id)
    await classify_and_orchestrate_phase_b_c(
        persisted_messages,
        sessionmaker,
        request_id=request_id,
        webhook_event_id=None,
    )


async def store_webhook_event(
    payload: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            webhook_event = WebhookEvent(
                payload=payload,
                status="RECEIVED",
                request_id=request_id,
            )
            session.add(webhook_event)
            await session.flush()
            return webhook_event.id


async def process_webhook_event(
    webhook_event_id: int,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    payload: dict[str, Any] | None = None
    request_id: str | None = None
    try:
        async with sessionmaker() as session:
            async with session.begin():
                webhook_event = await session.get(WebhookEvent, webhook_event_id)
                if webhook_event is None:
                    logger.error("webhook_event_missing", webhook_event_id=webhook_event_id)
                    return
                if webhook_event.status == "PROCESSED":
                    return
                payload = webhook_event.payload
                request_id = webhook_event.request_id

        persisted_messages = await persist_payload_phase_a(
            payload,
            sessionmaker,
            request_id=request_id,
        )
        await classify_and_orchestrate_phase_b_c(
            persisted_messages,
            sessionmaker,
            request_id=request_id,
            webhook_event_id=webhook_event_id,
        )
    except Exception as error:
        await mark_webhook_event_failed(webhook_event_id, sessionmaker, error)
        logger.error(
            "webhook_event_processing_failed",
            webhook_event_id=webhook_event_id,
            error=str(error),
        )


async def mark_webhook_event_processed(
    webhook_event_id: int | None,
    session: AsyncSession,
) -> None:
    if webhook_event_id is None:
        return
    webhook_event = await session.get(WebhookEvent, webhook_event_id, with_for_update=True)
    if webhook_event is None:
        return
    webhook_event.status = "PROCESSED"
    webhook_event.error = None
    webhook_event.processed_at = datetime.now(UTC)


async def mark_webhook_event_failed(
    webhook_event_id: int,
    sessionmaker: async_sessionmaker[AsyncSession],
    error: Exception,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            webhook_event = await session.get(
                WebhookEvent,
                webhook_event_id,
                with_for_update=True,
            )
            if webhook_event is None:
                return
            webhook_event.status = "FAILED"
            webhook_event.error = str(error)[:4000]


async def process_whatsapp_payload_in_session(
    session: AsyncSession,
    payload: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    request_id: str | None = None,
) -> None:
    persisted_messages: list[PersistedInboundMessage] = []
    inbound_messages = list(extract_inbound_messages(payload))
    provider_statuses = list(extract_provider_statuses(payload))

    if not inbound_messages and not provider_statuses:
        logger.info(
            "whatsapp_webhook_ignored",
            reason="no_messages_or_statuses",
            request_id=request_id,
        )
        return

    for status in provider_statuses:
        await record_provider_status_in_session(status, session, request_id=request_id)

    for inbound_message in inbound_messages:
        persisted = await persist_inbound_message_in_session(
            inbound_message,
            session,
            sessionmaker=sessionmaker,
            request_id=request_id,
        )
        if persisted is not None:
            persisted_messages.append(persisted)


async def persist_payload_phase_a(
    payload: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> list[PersistedInboundMessage]:
    async with sessionmaker() as session:
        async with session.begin():
            return await persist_payload_phase_a_in_session(session, payload, request_id=request_id)


async def persist_payload_phase_a_in_session(
    session: AsyncSession,
    payload: dict[str, Any],
    request_id: str | None = None,
) -> list[PersistedInboundMessage]:
    inbound_messages = list(extract_inbound_messages(payload))
    provider_statuses = list(extract_provider_statuses(payload))

    if not inbound_messages and not provider_statuses:
        logger.info(
            "whatsapp_webhook_ignored",
            reason="no_messages_or_statuses",
            request_id=request_id,
        )
        return []

    for status in provider_statuses:
        await record_provider_status_in_session(status, session, request_id=request_id)

    persisted_messages: list[PersistedInboundMessage] = []
    for inbound_message in inbound_messages:
        persisted = await persist_inbound_message_in_session(
            inbound_message,
            session,
            sessionmaker=None,
            request_id=request_id,
        )
        if persisted is not None:
            persisted_messages.append(persisted)
    return persisted_messages


async def classify_and_orchestrate_phase_b_c(
    persisted_messages: list[PersistedInboundMessage],
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str | None,
    webhook_event_id: int | None,
) -> None:
    if not persisted_messages:
        async with sessionmaker() as session:
            async with session.begin():
                await mark_webhook_event_processed(webhook_event_id, session)
        return

    settings = get_settings()
    for persisted in persisted_messages:
        if await message_already_orchestrated(sessionmaker, persisted.message_id):
            continue

        classification = deterministic_confirmation_classification(
            persisted.message_text,
            persisted.context,
        )
        ai_error_reason: AIErrorReason | None = None
        if classification is None:
            async with OpenRouterIntentClient(settings, sessionmaker) as classifier:
                try:
                    classification = await classifier.classify_intent(
                        persisted.message_text,
                        context=persisted.context,
                        conversation_id=persisted.conversation_id,
                    )
                except AIUnavailable as error:
                    ai_error_reason = error.reason

        async with sessionmaker() as session:
            async with session.begin():
                if await outbox_exists_for_message(session, persisted.message_id):
                    continue
                message = await session.get(Message, persisted.message_id)
                conversation = await session.get(
                    Conversation,
                    persisted.conversation_id,
                    with_for_update=True,
                )
                customer = await session.get(Customer, persisted.customer_id)
                if message is None or conversation is None or customer is None:
                    raise ValueError("Persisted inbound message cannot be reloaded")
                await orchestrate_inbound_message(
                    session,
                    settings,
                    sessionmaker,
                    OrchestrationInput(
                        conversation=conversation,
                        customer=customer,
                        inbound_message=message,
                        message_text=persisted.message_text,
                        request_id=request_id,
                    ),
                    classification=classification,
                    ai_error_reason=ai_error_reason,
                )

    async with sessionmaker() as session:
        async with session.begin():
            await mark_webhook_event_processed(webhook_event_id, session)


async def message_already_orchestrated(
    sessionmaker: async_sessionmaker[AsyncSession],
    message_id: int,
) -> bool:
    async with sessionmaker() as session:
        return await outbox_exists_for_message(session, message_id)


async def outbox_exists_for_message(session: AsyncSession, message_id: int) -> bool:
    outbox_id = await session.scalar(select(Outbox.id).where(Outbox.message_id == message_id))
    return outbox_id is not None


def extract_inbound_messages(payload: dict[str, Any]) -> list[InboundWhatsAppMessage]:
    messages: list[InboundWhatsAppMessage] = []
    for value in iter_whatsapp_change_values(payload):
        for message in value.get("messages", []):
            external_message_id = message.get("id")
            sender = message.get("from")
            message_type = message.get("type")
            if not external_message_id or not sender or not message_type:
                logger.info(
                    "whatsapp_message_ignored",
                    reason="missing_required_documented_fields",
                    has_id=bool(external_message_id),
                    has_from=bool(sender),
                    has_type=bool(message_type),
                )
                continue

            messages.append(
                InboundWhatsAppMessage(
                    external_message_id=external_message_id,
                    phone_number=normalize_phone_number(sender),
                    message_type=message_type,
                    content=extract_message_content(message, message_type),
                    provider_timestamp=parse_provider_timestamp(message.get("timestamp")),
                )
            )
    return messages


def extract_provider_statuses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for value in iter_whatsapp_change_values(payload):
        for status in value.get("statuses", []):
            provider_message_id = status.get("id")
            provider_status = status.get("status")
            if not provider_message_id or not provider_status:
                logger.info(
                    "whatsapp_status_ignored",
                    reason="missing_required_documented_fields",
                    has_id=bool(provider_message_id),
                    has_status=bool(provider_status),
                )
                continue
            statuses.append(status)
    return statuses


def iter_whatsapp_change_values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("object") != "whatsapp_business_account":
        return []

    values: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value")
            if isinstance(value, dict):
                values.append(value)
    return values


def extract_message_content(message: dict[str, Any], message_type: str) -> dict[str, Any]:
    typed_content = message.get(message_type)
    if isinstance(typed_content, dict):
        return {message_type: typed_content}
    return {"raw": message}


def parse_provider_timestamp(timestamp: Any) -> datetime | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), UTC)
    except (TypeError, ValueError, OSError):
        logger.info("whatsapp_timestamp_ignored", reason="invalid_timestamp", timestamp=timestamp)
        return None


async def persist_inbound_message(
    inbound_message: InboundWhatsAppMessage,
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> PersistedInboundMessage | None:
    async with sessionmaker() as session:
        async with session.begin():
            return await persist_inbound_message_in_session(
                inbound_message,
                session,
                sessionmaker=None,
                request_id=request_id,
            )


async def persist_inbound_message_in_session(
    inbound_message: InboundWhatsAppMessage,
    session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    request_id: str | None = None,
) -> PersistedInboundMessage | None:
    try:
        async with session.begin_nested():
            customer = await get_or_create_customer(session, inbound_message.phone_number)
            conversation = await get_or_create_active_conversation(session, customer)
            message = Message(
                external_message_id=inbound_message.external_message_id,
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type=inbound_message.message_type,
                content=inbound_message.content,
                provider_timestamp=inbound_message.provider_timestamp,
            )
            session.add(message)
            await session.flush()
            return persisted_message_from_models(message, conversation)
    except IntegrityError:
        logger.info(
            "whatsapp_message_duplicate",
            external_message_id=inbound_message.external_message_id,
            request_id=request_id,
        )
        return None


def persisted_message_from_models(
    message: Message,
    conversation: Conversation,
) -> PersistedInboundMessage:
    return PersistedInboundMessage(
        message_id=message.id,
        conversation_id=conversation.id,
        customer_id=message.customer_id,
        message_text=extract_text_body(message.content),
        context={
            "last_intent": conversation.last_intent,
            "pending_action": conversation.pending_action,
            "last_question_code": conversation.last_question_code,
            "known_fields": {},
            "failed_understanding_count": conversation.failed_understanding_count,
            "pending_confirmation": conversation.pending_confirmation,
        },
    )


def deterministic_confirmation_classification(
    message_text: str,
    context: dict[str, Any],
) -> IntentClassification | None:
    resolved = resolve_contextual_confirmation(
        message_text,
        pending_action=context.get("pending_action")
        if isinstance(context.get("pending_action"), str)
        else None,
        last_question_code=context.get("last_question_code")
        if isinstance(context.get("last_question_code"), str)
        else None,
    )
    if resolved is None:
        return None
    return IntentClassification(
        primary_intent=resolved,
        secondary_intents=[],
        sub_intent=None,
        confidence=1.0,
        information_category=None,
        entities={},
        extracted_entities=[],
        requested_action="RESOLVE_CONTEXTUAL_CONFIRMATION",
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={
            "pending_action": context.get("pending_action"),
            "last_question_code": context.get("last_question_code"),
        },
        reasoning_code=f"DETERMINISTIC_{resolved}",
    )


def extract_text_body(content: dict[str, Any]) -> str:
    text = content.get("text")
    if isinstance(text, dict):
        body = text.get("body")
        if isinstance(body, str):
            return body
    return ""


async def get_or_create_customer(session: AsyncSession, phone_number: str) -> Customer:
    customer = await session.scalar(select(Customer).where(Customer.phone_number == phone_number))
    if customer is not None:
        return customer

    customer = Customer(phone_number=phone_number)
    session.add(customer)
    await session.flush()
    return customer


async def get_or_create_active_conversation(
    session: AsyncSession,
    customer: Customer,
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation)
        .where(
            Conversation.customer_id == customer.id,
            Conversation.channel == Channel.WHATSAPP,
            Conversation.state.not_in(ACTIVE_CONVERSATION_EXCLUDED_STATUSES),
        )
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    if conversation is not None:
        return conversation

    conversation = Conversation(
        customer_id=customer.id,
        channel=Channel.WHATSAPP,
        state=ConversationState.NEW,
    )
    session.add(conversation)
    await session.flush()
    await transition_conversation(
        session,
        conversation,
        ConversationState.BOT_ACTIVE,
        actor=SYSTEM_ACTOR,
        reason="Initial valid WhatsApp message stored",
    )
    return conversation


async def record_provider_status(
    status_payload: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            await record_provider_status_in_session(status_payload, session, request_id=request_id)


async def record_provider_status_in_session(
    status_payload: dict[str, Any],
    session: AsyncSession,
    request_id: str | None = None,
) -> None:
    provider_message_id = status_payload["id"]
    try:
        async with session.begin_nested():
            message = await session.scalar(
                select(Message).where(Message.external_message_id == provider_message_id)
            )
            if message is None:
                logger.info(
                    "whatsapp_status_without_message",
                    provider_message_id=provider_message_id,
                    request_id=request_id,
                )
                return

            session.add(
                MessageProviderStatus(
                    provider_message_id=provider_message_id,
                    message_id=message.id,
                    status=status_payload["status"],
                    recipient_id=status_payload.get("recipient_id"),
                    provider_timestamp=parse_provider_timestamp(status_payload.get("timestamp")),
                    payload=status_payload,
                )
            )
    except IntegrityError:
        logger.info(
            "whatsapp_status_duplicate",
            provider_message_id=provider_message_id,
            status=status_payload["status"],
            request_id=request_id,
        )


async def record_invalid_signature_attempt(
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            session.add(
                AuditEvent(
                    actor="INTEGRATION",
                    action="WHATSAPP_WEBHOOK_INVALID_SIGNATURE",
                    entity="webhook",
                    old_value=None,
                    new_value=None,
                    reason="Invalid X-Hub-Signature-256",
                    request_id=request_id,
                )
            )

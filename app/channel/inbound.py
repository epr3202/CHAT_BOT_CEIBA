from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIErrorReason, AIUnavailable
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.audit.models import AuditEvent
from app.channel.models import Message, MessageProviderStatus, Outbox, WebhookEvent
from app.channel.schemas import InboundWhatsAppMessage
from app.channel.states import Channel
from app.config.settings import Settings, get_settings
from app.conversation.confirmation import resolve_contextual_confirmation
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation
from app.conversation.services_catalog import match_requested_services
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.event_type import normalize_event_type
from app.handoff.models import Handoff
from app.handoff.service import create_handoff
from app.orchestrator.service import (
    SENSITIVE_HANDOFF_INTENTS,
    VISIT_INTENTS,
    OrchestrationInput,
    enqueue_template,
    orchestrate_inbound_message,
)

logger = structlog.get_logger(__name__)

ACTIVE_CONVERSATION_EXCLUDED_STATUSES = ("RESOLVED", "CLOSED")
SYSTEM_ACTOR = "SYSTEM"
# RESP-DISCOVERY-* and RESP-PRICE-002 are documented but not emitted today. Review this
# set if those templates become active. RESP-CATALOG-002 intentionally remains excluded.
EVENT_TYPE_QUESTION_CODES = frozenset(
    {"RESP-GREETING-001", "RESP-EVENT-DATA-013", "RESP-PRICE-001"}
)


@dataclass(frozen=True)
class PersistedInboundMessage:
    message_id: int
    conversation_id: int
    customer_id: int
    message_text: str
    context: dict[str, Any]
    external_message_id: str
    message_type: str
    content: dict[str, Any]


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
    request_id: uuid.UUID | None = None,
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
    request_id: uuid.UUID | None,
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            webhook_event = WebhookEvent(
                payload=payload,
                status="RECEIVED",
                request_id=str(request_id) if request_id is not None else None,
            )
            session.add(webhook_event)
            await session.flush()
            return webhook_event.id


async def process_webhook_event(
    webhook_event_id: int,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    payload: dict[str, Any] | None = None
    request_id: uuid.UUID | None = None
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
                request_id = parse_request_id(webhook_event.request_id)

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
    request_id: uuid.UUID | None = None,
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
    request_id: uuid.UUID | None,
) -> list[PersistedInboundMessage]:
    async with sessionmaker() as session:
        async with session.begin():
            return await persist_payload_phase_a_in_session(session, payload, request_id=request_id)


async def persist_payload_phase_a_in_session(
    session: AsyncSession,
    payload: dict[str, Any],
    request_id: uuid.UUID | None,
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
    request_id: uuid.UUID | None,
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
        if await route_non_text_message(
            persisted,
            sessionmaker,
            settings=settings,
            request_id=request_id,
        ):
            continue

        classification: IntentClassification | None = None
        ai_error_reason: AIErrorReason | None = None
        services_resolution_failed = False
        services_pending = persisted.context.get("pending_action") == "COLLECT_SERVICES"
        if services_pending:
            service_codes = match_requested_services(persisted.message_text)
            decision_source: Literal["DETERMINISTIC", "LLM", "FALLBACK"] = (
                "DETERMINISTIC" if service_codes is not None else "LLM"
            )
            if service_codes is None:
                async with OpenRouterIntentClient(settings, sessionmaker) as classifier:
                    try:
                        classification = await classifier.classify_intent(
                            persisted.message_text,
                            context=persisted.context,
                            conversation_id=persisted.conversation_id,
                            request_id=request_id,
                            external_message_id=persisted.external_message_id,
                        )
                    except AIUnavailable as error:
                        ai_error_reason = error.reason
                        decision_source = "FALLBACK"
                    if (
                        classification is not None
                        and classification.primary_intent
                        not in SENSITIVE_HANDOFF_INTENTS | VISIT_INTENTS
                    ):
                        try:
                            service_codes = await classifier.classify_services(
                                persisted.message_text,
                                context=persisted.context,
                                conversation_id=persisted.conversation_id,
                                request_id=request_id,
                                external_message_id=persisted.external_message_id,
                            )
                        except AIUnavailable:
                            service_codes = []
                        services_resolution_failed = not service_codes
                        classification = services_turn_classification(
                            persisted.message_text,
                            service_codes or [],
                        )
            else:
                classification = services_turn_classification(
                    persisted.message_text,
                    service_codes,
                )
        else:
            classification = deterministic_confirmation_classification(
                persisted.message_text,
                persisted.context,
            )
            decision_source = "DETERMINISTIC"
        directed_event_type: str | None = None
        confidence_entity_rescued = False
        if classification is None:
            decision_source = "LLM"
            async with OpenRouterIntentClient(settings, sessionmaker) as classifier:
                try:
                    classification = await classifier.classify_intent(
                        persisted.message_text,
                        context=persisted.context,
                        conversation_id=persisted.conversation_id,
                        request_id=request_id,
                        external_message_id=persisted.external_message_id,
                    )
                except AIUnavailable as error:
                    ai_error_reason = error.reason
                    decision_source = "FALLBACK"

        if (
            classification is not None
            and decision_source == "LLM"
            and should_extract_event_type(persisted.context, classification)
        ):
            async with OpenRouterIntentClient(settings, sessionmaker) as extractor:
                try:
                    directed_event_type = await extractor.extract_event_type(
                        persisted.message_text,
                        context=persisted.context,
                        conversation_id=persisted.conversation_id,
                        request_id=request_id,
                        external_message_id=persisted.external_message_id,
                    )
                except AIUnavailable as error:
                    logger.warning(
                        "event_type_extraction_unavailable",
                        conversation_id=persisted.conversation_id,
                        request_id=str(request_id) if request_id is not None else None,
                        reason=error.reason.value,
                    )
        if classification is not None:
            classification = directed_event_type_bridge_classification(
                persisted.message_text,
                persisted.context,
                classification,
                directed_event_type,
            )
            rescued_classification = uncertain_event_type_entity_rescue_classification(
                persisted.context,
                classification,
                uncertain_threshold=settings.ai_confidence_uncertain,
                probable_threshold=settings.ai_confidence_probable,
                safe_threshold=settings.ai_confidence_safe,
            )
            confidence_entity_rescued = rescued_classification is not classification
            classification = rescued_classification

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
                        decision_source=decision_source,
                        directed_event_type=directed_event_type,
                        services_resolution_failed=services_resolution_failed,
                        confidence_entity_rescued=confidence_entity_rescued,
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


async def route_non_text_message(
    persisted: PersistedInboundMessage,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    request_id: uuid.UUID | None,
) -> bool:
    """Route channel-specific payloads before any classifier can see them."""
    if persisted.message_type in {"text", "interactive", "button"}:
        return False

    media_types = {"image", "document", "audio", "video"}
    caption = media_caption(persisted.content, persisted.message_type)
    async with sessionmaker() as session:
        async with session.begin():
            message = await session.get(Message, persisted.message_id)
            conversation = await session.get(
                Conversation,
                persisted.conversation_id,
                with_for_update=True,
            )
            customer = await session.get(Customer, persisted.customer_id)
            if message is None or conversation is None or customer is None:
                raise ValueError("Persisted inbound message cannot be reloaded")

            payment_context = await has_open_payment_handoff(session, conversation.id)
            session.add(
                build_non_text_audit(
                    message,
                    payment_context=payment_context,
                    request_id=request_id,
                )
            )

            if persisted.message_type in media_types and caption:
                return False

            response_code: str | None = None
            if persisted.message_type in {"image", "document"} and payment_context:
                response_code = "RESP-PAYMENT-002"
            elif persisted.message_type == "image":
                response_code = "RESP-FILE-001"
            elif persisted.message_type == "document":
                response_code = "RESP-FILE-004"
            elif persisted.message_type == "video":
                response_code = "RESP-FILE-005"
            elif persisted.message_type == "audio":
                response_code = "RESP-FILE-003"
            elif persisted.message_type in {"location", "contacts"}:
                response_code = "RESP-FALLBACK-001"
            elif persisted.message_type in {"unsupported", "unknown"}:
                detail = handoff_detail_for_non_text(message)
                await create_handoff(
                    session,
                    conversation,
                    customer,
                    reason="OTHER",
                    priority="NORMAL",
                    request_id=str(request_id) if request_id is not None else None,
                    settings=settings,
                    detail=detail,
                )
                response_code = "RESP-FALLBACK-001"

            if response_code is not None:
                await enqueue_template(
                    session,
                    sessionmaker,
                    conversation,
                    customer,
                    message,
                    response_code,
                    {},
                )
    return True


async def has_open_payment_handoff(session: AsyncSession, conversation_id: int) -> bool:
    handoff_id = await session.scalar(
        select(Handoff.id)
        .where(
            Handoff.conversation_id == conversation_id,
            Handoff.reason == "PAYMENT_REVIEW",
            Handoff.status.in_(("PENDING", "TAKEN")),
        )
        .limit(1)
    )
    return handoff_id is not None


def media_caption(content: dict[str, Any], message_type: str) -> str:
    typed_content = content.get(message_type)
    if not isinstance(typed_content, dict):
        return ""
    caption = typed_content.get("caption")
    return caption.strip() if isinstance(caption, str) else ""


def build_non_text_audit(
    message: Message,
    *,
    payment_context: bool,
    request_id: uuid.UUID | None,
) -> AuditEvent:
    typed_content = message.content.get(message.message_type)
    details = typed_content if isinstance(typed_content, dict) else {}
    value: dict[str, Any] = {
        "message_type": message.message_type,
        "mime_type": details.get("mime_type"),
        "has_caption": bool(media_caption(message.content, message.message_type)),
        "payment_context": payment_context,
    }
    if message.message_type == "audio":
        value.update(
            voice=details.get("voice"),
            duration_s=details.get("duration_s"),
        )
    elif message.message_type == "reaction":
        value.update(
            emoji=details.get("emoji"),
            reacted_message_id=details.get("message_id"),
        )
    elif message.message_type == "unsupported":
        value.update(
            raw_type=details.get("raw_type", "unsupported"),
            error_codes=error_codes(details),
        )
    elif message.message_type == "unknown":
        value["raw_type"] = unknown_raw_type(message)

    return AuditEvent(
        actor=SYSTEM_ACTOR,
        action="NON_TEXT_MESSAGE_RECEIVED",
        entity="message",
        old_value=None,
        new_value=value,
        reason="Inbound non-text message routed",
        request_id=request_id,
    )


def error_codes(content: dict[str, Any]) -> list[int]:
    errors = content.get("errors")
    if not isinstance(errors, list):
        return []
    return [
        code
        for error in errors
        if isinstance(error, dict) and isinstance((code := error.get("code")), int)
    ]


def unknown_raw_type(message: Message) -> str:
    unknown = message.content.get("unknown")
    if isinstance(unknown, dict) and isinstance(unknown.get("raw_type"), str):
        return unknown["raw_type"]
    return "unknown"


def handoff_detail_for_non_text(message: Message) -> str:
    if message.message_type == "unsupported":
        content = message.content.get("unsupported")
        details = content if isinstance(content, dict) else {}
        codes = error_codes(details)
        return "unsupported message" + (f"; error codes: {codes}" if codes else "")
    return f"unknown inbound message type: {unknown_raw_type(message)}"


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

            try:
                parsed = InboundWhatsAppMessage.model_validate(message)
            except ValidationError as error:
                logger.info(
                    "whatsapp_message_ignored",
                    reason="invalid_typed_payload",
                    validation_error_count=error.error_count(),
                )
                continue
            messages.append(
                parsed.model_copy(update={"phone_number": normalize_phone_number(sender)})
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
    request_id: uuid.UUID | None = None,
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
    request_id: uuid.UUID | None = None,
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
                content=inbound_message.storage_content(),
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
            "pending_fields": conversation.pending_fields,
        },
        external_message_id=message.external_message_id,
        message_type=message.message_type,
        content=message.content,
    )


def should_extract_event_type(
    context: dict[str, Any],
    classification: IntentClassification,
) -> bool:
    pending_fields = context.get("pending_fields")
    event_type_pending = context.get("pending_action") == "COLLECT_EVENT_TYPE" and (
        not isinstance(pending_fields, list) or "event_type" in pending_fields
    )
    event_type_question = context.get("last_question_code") in EVENT_TYPE_QUESTION_CODES
    if not event_type_pending and not event_type_question:
        return False
    candidates = [
        entity.normalized_value or entity.raw_value
        for entity in classification.extracted_entities
        if entity.entity == "event_type" and entity.quality_status != "INVALID"
    ]
    legacy_candidate = classification.entities.get("event_type")
    if legacy_candidate is not None:
        candidates.append(legacy_candidate)
    return not any(normalize_event_type(candidate) is not None for candidate in candidates)


def directed_event_type_bridge_classification(
    message_text: str,
    context: dict[str, Any],
    classification: IntentClassification,
    directed_event_type: str | None,
) -> IntentClassification:
    normalized_event_type = normalize_event_type(directed_event_type)
    if (
        classification.primary_intent != "UNKNOWN"
        or context.get("last_question_code") not in EVENT_TYPE_QUESTION_CODES
        or normalized_event_type is None
    ):
        return classification
    entity = ExtractedEntity(
        entity="event_type",
        raw_value=message_text,
        normalized_value=normalized_event_type,
        quality_status="PROVIDED",
        confidence=1.0,
        needs_confirmation=False,
        validation_errors=[],
    )
    return IntentClassification(
        primary_intent="EVENT_INFORMATION",
        secondary_intents=[],
        sub_intent=None,
        confidence=1.0,
        information_category=None,
        entities={},
        extracted_entities=[entity],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={
            "last_question_code": context.get("last_question_code"),
            "source_intent": "UNKNOWN",
        },
        reasoning_code="DIRECTED_EVENT_TYPE_BRIDGE",
    )


def uncertain_event_type_entity_rescue_classification(
    context: dict[str, Any],
    classification: IntentClassification,
    *,
    uncertain_threshold: float,
    probable_threshold: float,
    safe_threshold: float,
) -> IntentClassification:
    if (
        classification.primary_intent != "EVENT_INFORMATION"
        or not uncertain_threshold <= classification.confidence < probable_threshold
        or context.get("last_question_code") not in EVENT_TYPE_QUESTION_CODES
    ):
        return classification

    rescued_entity: ExtractedEntity | None = None
    for entity in classification.extracted_entities:
        if entity.entity != "event_type":
            continue
        normalized_event_type = normalize_event_type(
            entity.normalized_value or entity.raw_value
        )
        if (
            entity.quality_status in {"PROVIDED", "CORRECTED"}
            and not entity.needs_confirmation
            and entity.confidence >= safe_threshold
            and normalized_event_type is not None
        ):
            rescued_entity = ExtractedEntity(
                entity="event_type",
                raw_value=entity.raw_value,
                normalized_value=normalized_event_type,
                quality_status=entity.quality_status,
                confidence=entity.confidence,
                needs_confirmation=False,
                validation_errors=list(entity.validation_errors),
            )
            break

    if rescued_entity is None:
        return classification

    return IntentClassification(
        primary_intent="EVENT_INFORMATION",
        secondary_intents=[],
        sub_intent=None,
        confidence=rescued_entity.confidence,
        information_category=None,
        entities={},
        extracted_entities=[rescued_entity],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={
            "original_global_confidence": classification.confidence,
            "rescued_entity_confidence": rescued_entity.confidence,
            "last_question_code": context.get("last_question_code"),
            "original_reasoning_code": classification.reasoning_code,
        },
        reasoning_code="UNCERTAIN_ENTITY_RESCUE",
    )


def services_turn_classification(
    message_text: str,
    service_codes: list[str],
) -> IntentClassification:
    entities = (
        [
            ExtractedEntity(
                entity="requested_services",
                raw_value=message_text,
                normalized_value=service_codes,
                quality_status="PROVIDED",
                confidence=1.0,
                needs_confirmation=False,
                validation_errors=[],
            )
        ]
        if service_codes
        else []
    )
    return IntentClassification(
        primary_intent="EVENT_INFORMATION",
        secondary_intents=[],
        sub_intent=None,
        confidence=1.0,
        information_category=None,
        entities={},
        extracted_entities=entities,
        requested_action=None,
        missing_fields=[] if service_codes else ["requested_services"],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="DIRECTED_SERVICES_CAPTURE",
    )


def parse_request_id(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        logger.warning("legacy_webhook_request_id_ignored", legacy_request_id=value)
        return None


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
    for message_type in ("image", "document", "audio", "video"):
        typed_content = content.get(message_type)
        if isinstance(typed_content, dict):
            caption = typed_content.get("caption")
            if isinstance(caption, str):
                return caption
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
    request_id: uuid.UUID | None = None,
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            await record_provider_status_in_session(status_payload, session, request_id=request_id)


async def record_provider_status_in_session(
    status_payload: dict[str, Any],
    session: AsyncSession,
    request_id: uuid.UUID | None = None,
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
    request_id: uuid.UUID | None = None,
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
                    request_id=str(request_id) if request_id is not None else None,
                )
            )

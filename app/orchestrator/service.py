from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIErrorReason
from app.ai.schemas import IntentClassification
from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.faq_catalog import NO_APPROVED_ANSWER, response_code_for_category
from app.conversation.knowledge import KnowledgeRenderError, render_response
from app.conversation.models import Conversation
from app.conversation.pending_actions import validate_pending_action
from app.conversation.service import ALLOWED_TRANSITIONS, transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.service import create_handoff

logger = structlog.get_logger(__name__)

SYSTEM_ACTOR = "SYSTEM"
SENSITIVE_HANDOFF_INTENTS = {
    "HUMAN_REQUEST",
    "COMPLAINT",
    "EMERGENCY",
    "PAYMENT_MESSAGE",
    "EVENT_CANCELLATION",
}
TRANSIENT_UNSUPPORTED_INTENTS = {
    "EVENT_INFORMATION",
    "QUOTE_REQUEST",
    "MODIFY_EVENT_DATA",
    "SCHEDULE_VISIT",
    "RESCHEDULE_VISIT",
    "CANCEL_VISIT",
    "RESERVATION_INFORMATION",
}
CRITICAL_STATES = {
    ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
    ConversationState.WAITING_FOR_APPOINTMENT_DATE,
    ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
    ConversationState.QUOTE_REQUEST_READY,
}

HANDOFF_REASON_BY_INTENT = {
    "HUMAN_REQUEST": "CUSTOMER_REQUEST",
    "COMPLAINT": "COMPLAINT",
    "EMERGENCY": "URGENT_EVENT",
    "PAYMENT_MESSAGE": "PAYMENT_REVIEW",
    "EVENT_CANCELLATION": "CANCELLATION",
}


@dataclass(frozen=True)
class OrchestrationInput:
    conversation: Conversation
    customer: Customer
    inbound_message: Message
    message_text: str
    request_id: str | None = None


async def orchestrate_inbound_message(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification | None,
    ai_error_reason: AIErrorReason | None = None,
) -> None:
    conversation = orchestration_input.conversation
    customer = orchestration_input.customer
    inbound_message = orchestration_input.inbound_message
    conversation.last_message_at = inbound_message.created_at

    state = ConversationState(conversation.state)
    if state == ConversationState.CLOSED:
        audit_orchestrator_event(
            session,
            "CLOSED_CONVERSATION_MESSAGE_RECEIVED",
            conversation,
            reason="Message received while conversation is CLOSED",
            request_id=orchestration_input.request_id,
        )
        return

    if state in {ConversationState.WAITING_FOR_HUMAN, ConversationState.HUMAN_ACTIVE}:
        audit_orchestrator_event(
            session,
            "MESSAGE_RECEIVED_DURING_HANDOFF",
            conversation,
            reason=f"Message received while conversation is {state.value}",
            request_id=orchestration_input.request_id,
        )
        return

    if not conversation.bot_enabled:
        audit_orchestrator_event(
            session,
            "MESSAGE_RECEIVED_WHILE_BOT_DISABLED",
            conversation,
            reason="Message received while bot_enabled is false",
            request_id=orchestration_input.request_id,
        )
        return

    if ai_error_reason is not None:
        await handle_ai_unavailable(
            session,
            settings,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            ai_error_reason,
            orchestration_input.message_text,
            orchestration_input.request_id,
        )
        return

    if classification is None:
        raise ValueError("classification or ai_error_reason is required")

    classification = await resolve_pending_confirmation(
        session,
        conversation,
        classification,
        orchestration_input.message_text,
        orchestration_input.request_id,
    )

    if classification.confidence < settings.ai_confidence_uncertain:
        audit_confidence_decision(
            session,
            conversation,
            classification,
            decision="DEGRADE_TO_UNKNOWN",
            threshold=settings.ai_confidence_uncertain,
            request_id=orchestration_input.request_id,
        )
        classification = classification.model_copy(
            update={
                "primary_intent": "UNKNOWN",
                "secondary_intents": [],
                "requested_action": "ASK_CLARIFICATION_MENU",
                "needs_human": False,
                "handoff_reason": None,
                "priority": "NORMAL",
                "reasoning_code": "LOW_CONFIDENCE_BELOW_UNCERTAIN",
            }
        )
    elif classification.confidence < settings.ai_confidence_probable:
        audit_confidence_decision(
            session,
            conversation,
            classification,
            decision="ASK_CONFIRMATION",
            threshold=settings.ai_confidence_probable,
            request_id=orchestration_input.request_id,
        )
        conversation.pending_confirmation = {
            "classification": classification.model_dump(mode="json"),
            "original_intent": classification.primary_intent,
            "original_confidence": classification.confidence,
            "entities": classification.entities,
        }
        set_pending_action(conversation, "CLASSIFY_MESSAGE")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            "RESP-FALLBACK-004",
            {},
        )
        persist_classification_context(conversation, classification)
        return

    await route_classification(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
    )


def conversation_context(conversation: Conversation) -> dict[str, Any]:
    return {
        "last_intent": conversation.last_intent,
        "pending_action": conversation.pending_action,
        "last_question_code": conversation.last_question_code,
        "known_fields": {},
        "failed_understanding_count": conversation.failed_understanding_count,
        "pending_confirmation": conversation.pending_confirmation,
    }


async def resolve_pending_confirmation(
    session: AsyncSession,
    conversation: Conversation,
    classification: IntentClassification,
    message_text: str,
    request_id: str | None,
) -> IntentClassification:
    if not conversation.pending_confirmation:
        return classification

    pending = conversation.pending_confirmation
    if is_affirmative(message_text):
        confirmed = IntentClassification.model_validate(pending["classification"])
        audit_orchestrator_event(
            session,
            "AI_CONFIRMATION_ACCEPTED",
            conversation,
            reason="Customer confirmed tentative classification",
            request_id=request_id,
            extra={
                "confirmed_intent": confirmed.primary_intent,
                "original_confidence": confirmed.confidence,
            },
        )
        conversation.pending_confirmation = None
        return confirmed

    audit_orchestrator_event(
        session,
        "AI_CONFIRMATION_DISCARDED",
        conversation,
        reason="Customer did not confirm tentative classification",
        request_id=request_id,
        extra={"pending_confirmation": pending},
    )
    conversation.pending_confirmation = None
    return classification


async def route_classification(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    customer = orchestration_input.customer
    inbound_message = orchestration_input.inbound_message
    intent = classification.primary_intent

    if not is_action_allowed_for_slice(conversation, classification):
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            "RESP-FALLBACK-004",
            {},
        )
        audit_orchestrator_event(
            session,
            "ORCHESTRATOR_ACTION_REJECTED",
            conversation,
            reason="Requested action is not allowed for current state in Slice 1",
            request_id=orchestration_input.request_id,
            extra={"intent": intent, "requested_action": classification.requested_action},
        )
        return

    if intent == "GREETING":
        await handle_greeting(session, knowledge_sessionmaker, orchestration_input, classification)
        return

    if intent == "GENERAL_INFORMATION":
        await handle_general_information(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if intent == "FAREWELL":
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            "RESP-FAREWELL-001",
            {},
        )
        persist_classification_context(conversation, classification)
        set_pending_action(conversation, None)
        conversation.pending_confirmation = None
        if ConversationState.RESOLVED in ALLOWED_TRANSITIONS[ConversationState(conversation.state)]:
            await transition_conversation(
                session,
                conversation,
                ConversationState.RESOLVED,
                actor=SYSTEM_ACTOR,
                reason="Farewell without critical pending action",
            )
        return

    if intent == "UNKNOWN":
        await handle_unknown(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if intent in SENSITIVE_HANDOFF_INTENTS:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason=classification.handoff_reason or HANDOFF_REASON_BY_INTENT[intent],
            priority="CRITICAL" if intent == "EMERGENCY" else classification.priority,
        )
        return

    if intent in TRANSIENT_UNSUPPORTED_INTENTS:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="UNSUPPORTED_REQUEST",
            priority=classification.priority,
            detail=classification.primary_intent,
        )
        return

    await handle_unknown(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
    )


async def handle_greeting(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    customer = orchestration_input.customer
    response_code = "RESP-GREETING-002" if customer.full_name else "RESP-GREETING-001"
    variables = {"customer_name": customer.full_name} if customer.full_name else {}
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        orchestration_input.conversation,
        customer,
        orchestration_input.inbound_message,
        response_code,
        variables,
    )
    persist_classification_context(orchestration_input.conversation, classification)
    orchestration_input.conversation.failed_understanding_count = 0
    orchestration_input.conversation.pending_confirmation = None


async def handle_general_information(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    previous_state = ConversationState(conversation.state)
    previous_pending_action = conversation.pending_action
    if ConversationState.ANSWERING_INFORMATION in ALLOWED_TRANSITIONS[previous_state]:
        set_pending_action(conversation, "ANSWER_INFORMATION")
        await transition_conversation(
            session,
            conversation,
            ConversationState.ANSWERING_INFORMATION,
            actor=SYSTEM_ACTOR,
            reason="General information detected",
        )

    category = classification.information_category
    if category is None:
        conversation.failed_understanding_count += 1
        persist_classification_context(conversation, classification)
        set_pending_action(conversation, "CLASSIFY_MESSAGE")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-FALLBACK-001",
            {},
        )
        target_state = (
            previous_state
            if previous_state != ConversationState.ANSWERING_INFORMATION
            and previous_state in ALLOWED_TRANSITIONS[ConversationState.ANSWERING_INFORMATION]
            else ConversationState.BOT_ACTIVE
        )
        if conversation.state != target_state.value:
            await transition_conversation(
                session,
                conversation,
                target_state,
                actor=SYSTEM_ACTOR,
                reason="General information category unclear",
            )
        conversation.pending_action = previous_pending_action
        return

    response_code = response_code_for_category(category)
    if response_code == "RESP-LOCATION-001" and wants_location_link(
        orchestration_input.message_text
    ):
        response_code = "RESP-LOCATION-002"
    if response_code == NO_APPROVED_ANSWER:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="OTHER",
            priority="NORMAL",
            detail=f"NO_APPROVED_ANSWER category={category}",
        )
        return

    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        response_code,
        {"map_url": "https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw"}
        if response_code == "RESP-LOCATION-002"
        else {},
    )
    persist_classification_context(conversation, classification)
    conversation.failed_understanding_count = 0
    conversation.pending_confirmation = None

    target_state = (
        previous_state
        if previous_state != ConversationState.ANSWERING_INFORMATION
        and previous_state in ALLOWED_TRANSITIONS[ConversationState.ANSWERING_INFORMATION]
        else ConversationState.BOT_ACTIVE
    )
    if conversation.state != target_state.value:
        await transition_conversation(
            session,
            conversation,
            target_state,
            actor=SYSTEM_ACTOR,
            reason="General information answered",
        )
    conversation.pending_action = previous_pending_action


async def handle_unknown(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    conversation.failed_understanding_count += 1
    persist_classification_context(conversation, classification)
    set_pending_action(conversation, "CLASSIFY_MESSAGE")

    if conversation.failed_understanding_count == 1:
        response_code = "RESP-FALLBACK-001"
    elif conversation.failed_understanding_count == 2:
        response_code = "RESP-FALLBACK-002"
    else:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="LOW_CONFIDENCE",
            priority="NORMAL",
            response_code_override="RESP-FALLBACK-003",
        )
        return

    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        response_code,
        {},
    )


async def handle_ai_unavailable(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    error_reason: AIErrorReason,
    message_text: str,
    request_id: str | None,
) -> None:
    audit_orchestrator_event(
        session,
        "AI_UNAVAILABLE",
        conversation,
        reason=error_reason.value,
        request_id=request_id,
    )
    if ConversationState(conversation.state) in CRITICAL_STATES:
        classification = IntentClassification(
            primary_intent="UNKNOWN",
            secondary_intents=[],
            sub_intent=None,
            confidence=0,
            entities={},
            requested_action="CREATE_HANDOFF_LOW_CONFIDENCE",
            missing_fields=[],
            needs_confirmation=False,
            needs_human=True,
            handoff_reason="SYSTEM_ERROR",
            priority="URGENT",
            context_reference={},
            reasoning_code="AI_UNAVAILABLE_CRITICAL_STATE",
        )
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            OrchestrationInput(conversation, customer, inbound_message, "", request_id),
            classification,
            reason="SYSTEM_ERROR",
            priority="URGENT",
            detail=error_reason.value,
        )
        return

    if looks_like_location_question(message_text):
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            "RESP-LOCATION-002",
            {"map_url": "https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw"},
        )
        return

    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        "RESP-DISCOVERY-002",
        {},
    )


async def create_handoff_and_pause(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
    reason: str,
    priority: str,
    detail: str | None = None,
    response_code_override: str | None = None,
) -> None:
    conversation = orchestration_input.conversation
    _handoff, response_code = await create_handoff(
        session,
        conversation,
        orchestration_input.customer,
        reason=reason,
        priority=priority,
        request_id=orchestration_input.request_id,
        settings=settings,
        detail=detail,
    )
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        response_code_override or response_code,
        {},
    )
    persist_classification_context(conversation, classification)
    set_pending_action(conversation, "WAIT_FOR_HUMAN")
    conversation.pending_confirmation = None


async def enqueue_template(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    response_code: str,
    variables: dict[str, Any],
) -> None:
    try:
        body = await render_response(knowledge_sessionmaker, response_code, variables)
    except KnowledgeRenderError:
        logger.error("approved_response_render_failed", response_code=response_code)
        body = await render_response(knowledge_sessionmaker, "RESP-AI-ERROR-001", {})

    conversation.last_question_code = response_code
    session.add(
        Outbox(
            conversation_id=conversation.id,
            message_id=inbound_message.id,
            channel=Channel.WHATSAPP,
            recipient_phone_number=customer.phone_number,
            payload={"type": "text", "text": {"body": body}},
            status="PENDING",
        )
    )


def persist_classification_context(
    conversation: Conversation,
    classification: IntentClassification,
) -> None:
    conversation.last_intent = classification.primary_intent


def set_pending_action(conversation: Conversation, pending_action: str | None) -> None:
    conversation.pending_action = validate_pending_action(pending_action)


def is_affirmative(message_text: str) -> bool:
    return message_text.strip().casefold() in {
        "si",
        "sí",
        "s",
        "ok",
        "okay",
        "dale",
        "correcto",
        "claro",
    }


def looks_like_location_question(message_text: str) -> bool:
    normalized = message_text.casefold()
    return any(
        token in normalized for token in ("donde", "dónde", "ubic", "direccion", "dirección")
    )


def wants_location_link(message_text: str) -> bool:
    normalized = message_text.casefold()
    return any(token in normalized for token in ("pásame", "pasame", "map", "link", "enlace"))


def audit_confidence_decision(
    session: AsyncSession,
    conversation: Conversation,
    classification: IntentClassification,
    decision: str,
    threshold: float,
    request_id: str | None,
) -> None:
    audit_orchestrator_event(
        session,
        "AI_CONFIDENCE_DECISION",
        conversation,
        reason=decision,
        request_id=request_id,
        extra={
            "original_intent": classification.primary_intent,
            "original_confidence": classification.confidence,
            "threshold": threshold,
            "decision": decision,
        },
    )


def is_action_allowed_for_slice(
    conversation: Conversation,
    classification: IntentClassification,
) -> bool:
    if classification.primary_intent in {"GREETING", "GENERAL_INFORMATION", "FAREWELL", "UNKNOWN"}:
        return True
    if classification.primary_intent in SENSITIVE_HANDOFF_INTENTS | TRANSIENT_UNSUPPORTED_INTENTS:
        return ConversationState.WAITING_FOR_HUMAN in ALLOWED_TRANSITIONS[
            ConversationState(conversation.state)
        ]
    return False


def audit_orchestrator_event(
    session: AsyncSession,
    action: str,
    conversation: Conversation,
    reason: str,
    request_id: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor=SYSTEM_ACTOR,
            action=action,
            entity="conversation",
            old_value=None,
            new_value={"conversation_id": conversation.id, **(extra or {})},
            reason=reason,
            request_id=request_id,
        )
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIErrorReason
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.audit.models import AuditEvent
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import Settings
from app.conversation.confirmation import resolve_contextual_confirmation
from app.conversation.faq_catalog import NO_APPROVED_ANSWER, response_code_for_category
from app.conversation.knowledge import KnowledgeRenderError, render_response
from app.conversation.models import Conversation
from app.conversation.pending_actions import validate_pending_action
from app.conversation.service import ALLOWED_TRANSITIONS, transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event, EventServiceRequest
from app.event.validation import (
    EventDateTriplet,
    parse_customer_date_expression,
    validate_event_date_triplet,
)
from app.handoff.service import create_handoff
from app.lead.budget import calculate_budget_range, parse_cop_amount
from app.lead.models import Lead
from app.orchestrator.slot_filling import (
    QUESTION_CODE_BY_ACTION,
    CaptureProgress,
    minimum_quote_data_complete,
    pending_fields_for,
    select_next_question,
)
from app.quote.models import QuoteRequest

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
    "SCHEDULE_VISIT",
    "RESCHEDULE_VISIT",
    "CANCEL_VISIT",
    "RESERVATION_INFORMATION",
}
COLLECTION_INTENTS = {"EVENT_INFORMATION", "QUOTE_REQUEST", "MODIFY_EVENT_DATA"}
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

    classification = resolve_contextual_confirmation_classification(
        conversation,
        orchestration_input.message_text,
        classification,
    )
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
    if isinstance(pending, dict) and pending.get("type") == "FULL_NAME_CONFIRMATION":
        return classification

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
    state = ConversationState(conversation.state)

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

    if intent == "DENY" and state == ConversationState.QUOTE_REQUEST_READY:
        await handle_quote_request_ready(
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

    if state == ConversationState.QUOTE_REQUEST_READY:
        await handle_quote_request_ready(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if state == ConversationState.COLLECTING_EVENT_DATA or intent in COLLECTION_INTENTS:
        await handle_collecting_event_data(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
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


async def handle_collecting_event_data(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    customer = orchestration_input.customer
    inbound_message = orchestration_input.inbound_message
    lead, event = await get_or_create_capture_models(
        session,
        conversation,
        customer,
        request_id=orchestration_input.request_id,
    )

    if ConversationState(conversation.state) == ConversationState.BOT_ACTIVE:
        await transition_conversation(
            session,
            conversation,
            ConversationState.COLLECTING_EVENT_DATA,
            actor=SYSTEM_ACTOR,
            reason="Commercial intent starts quote data capture",
        )

    handled_name_confirmation = await maybe_apply_name_confirmation(
        session,
        conversation,
        customer,
        orchestration_input.message_text,
        orchestration_input.request_id,
    )
    entities = normalized_entities(classification)
    if not handled_name_confirmation:
        await apply_extracted_entities(
            session,
            conversation,
            customer,
            lead,
            event,
            entities,
            orchestration_input.request_id,
        )
    if should_mark_budget_declined_by_evasion(lead, entities):
        apply_budget_declined(session, lead, orchestration_input.request_id)

    progress = await capture_progress(session, customer, lead, event, conversation)
    conversation.pending_fields = pending_fields_for(progress)
    next_action = select_next_question(progress)
    persist_classification_context(conversation, classification)
    conversation.failed_understanding_count = 0

    if next_action is not None:
        set_pending_action(conversation, next_action)
        if next_action == "COLLECT_BUDGET" and lead.budget_data_status == "NOT_ASKED":
            lead.budget_data_status = "ASKED_PENDING"
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            QUESTION_CODE_BY_ACTION[next_action],
            {},
        )
        return

    await transition_to_quote_request_ready(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        lead,
        event,
        request_id=orchestration_input.request_id,
    )


async def handle_quote_request_ready(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    customer = orchestration_input.customer
    lead = await active_lead(session, conversation)
    event = await active_event(session, lead)
    if lead is None or event is None:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="SYSTEM_ERROR",
            priority="URGENT",
            detail="QUOTE_REQUEST_READY without active lead/event",
        )
        return

    if classification.primary_intent == "DENY":
        await transition_conversation(
            session,
            conversation,
            ConversationState.COLLECTING_EVENT_DATA,
            actor=SYSTEM_ACTOR,
            reason="Customer denied quote summary",
        )
        set_pending_action(conversation, None)
        conversation.pending_confirmation = {
            "resolved_intent": "DENY",
            "previous_pending_action": "CONFIRM_QUOTE_REQUEST",
            "last_question_code": conversation.last_question_code,
        }
        persist_classification_context(conversation, classification)
        return

    if classification.primary_intent == "MODIFY_EVENT_DATA":
        await apply_extracted_entities(
            session,
            conversation,
            customer,
            lead,
            event,
            normalized_entities(classification),
            orchestration_input.request_id,
        )
        await transition_conversation(
            session,
            conversation,
            ConversationState.COLLECTING_EVENT_DATA,
            actor=SYSTEM_ACTOR,
            reason="Customer corrected quote summary",
        )
        await handle_collecting_event_data(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if classification.primary_intent != "CONFIRM" and not is_affirmative(
        orchestration_input.message_text
    ):
        set_pending_action(conversation, "CONFIRM_QUOTE_REQUEST")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            orchestration_input.inbound_message,
            "RESP-QUOTE-001",
            {"missing_field": "la confirmación de la solicitud"},
        )
        return

    progress = await capture_progress(session, customer, lead, event, conversation)
    if not minimum_quote_data_complete(progress):
        await transition_conversation(
            session,
            conversation,
            ConversationState.COLLECTING_EVENT_DATA,
            actor=SYSTEM_ACTOR,
            reason="Quote confirmation rejected by deterministic minimum gate",
        )
        await handle_collecting_event_data(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    quote_request = await get_or_create_quote_request(session, lead, event)
    if quote_request.request_status == "READY":
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            orchestration_input.inbound_message,
            "RESP-QUOTE-007",
            {},
        )
        return

    now = datetime.now(UTC)
    quote_request.request_status = "READY"
    quote_request.minimum_data_complete = True
    quote_request.missing_fields = []
    quote_request.date_pending = date_pending(event)
    quote_request.requested_at = now
    quote_request.due_at = add_business_days_bogota(now, 3)
    quote_request.summary_snapshot = summary_snapshot(customer, lead, event)
    lead.lead_status = "QUOTE_REQUESTED"
    previous_pending_action = conversation.pending_action
    conversation.pending_confirmation = {
        "resolved_intent": "CONFIRM",
        "previous_pending_action": previous_pending_action,
        "last_question_code": conversation.last_question_code,
    }
    audit_domain_change(
        session,
        "QUOTE_REQUEST_READY",
        "quote_request",
        {"request_status": "DRAFT"},
        {
            "quote_request_id": str(quote_request.quote_request_id),
            "request_status": "READY",
            "date_pending": quote_request.date_pending,
        },
        "Customer confirmed quote summary",
        orchestration_input.request_id,
    )
    await create_handoff(
        session,
        conversation,
        customer,
        reason="QUOTE_PREPARATION",
        priority="NORMAL",
        request_id=orchestration_input.request_id,
        settings=settings,
    )
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        orchestration_input.inbound_message,
        "RESP-QUOTE-009" if quote_request.date_pending else "RESP-QUOTE-004",
        {},
    )
    set_pending_action(conversation, "WAIT_FOR_HUMAN")


async def get_or_create_capture_models(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    request_id: str | None,
) -> tuple[Lead, Event]:
    lead = await active_lead(session, conversation)
    if lead is None:
        lead = Lead(customer_id=customer.id, channel=conversation.channel, lead_status="QUALIFYING")
        session.add(lead)
        await session.flush()
        conversation.active_lead_id = lead.lead_id
        audit_domain_change(
            session,
            "LEAD_CREATED",
            "lead",
            None,
            {"lead_id": str(lead.lead_id), "conversation_id": conversation.id},
            "Commercial capture started",
            request_id,
        )
    elif lead.lead_status == "NEW":
        lead.lead_status = "QUALIFYING"

    event = await active_event(session, lead)
    if event is None:
        event = Event(lead_id=lead.lead_id)
        session.add(event)
        await session.flush()
        audit_domain_change(
            session,
            "EVENT_CREATED",
            "event",
            None,
            {"event_id": str(event.event_id), "lead_id": str(lead.lead_id)},
            "Commercial capture started",
            request_id,
        )
    return lead, event


async def active_lead(session: AsyncSession, conversation: Conversation) -> Lead | None:
    if conversation.active_lead_id is None:
        return None
    return await session.get(Lead, conversation.active_lead_id)


async def active_event(session: AsyncSession, lead: Lead | None) -> Event | None:
    if lead is None:
        return None
    return await session.scalar(select(Event).where(Event.lead_id == lead.lead_id).limit(1))


async def get_or_create_quote_request(
    session: AsyncSession,
    lead: Lead,
    event: Event,
) -> QuoteRequest:
    existing = await session.scalar(
        select(QuoteRequest)
        .where(QuoteRequest.lead_id == lead.lead_id, QuoteRequest.event_id == event.event_id)
        .limit(1)
    )
    if existing is not None:
        return existing
    quote_request = QuoteRequest(
        lead_id=lead.lead_id,
        event_id=event.event_id,
        request_status="DRAFT",
        minimum_data_complete=False,
        missing_fields=[],
        date_pending=date_pending(event),
        summary_snapshot={},
    )
    session.add(quote_request)
    await session.flush()
    return quote_request


async def apply_extracted_entities(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    lead: Lead,
    event: Event,
    entities: list[ExtractedEntity],
    request_id: str | None,
) -> None:
    for entity in entities:
        if entity.quality_status == "INVALID":
            audit_domain_change(
                session,
                "ENTITY_INVALID",
                "conversation",
                None,
                {
                    "conversation_id": conversation.id,
                    "entity": entity.entity,
                    "validation_errors": entity.validation_errors,
                },
                "Extracted entity failed deterministic validation",
                request_id,
            )
            continue
        if entity.entity == "full_name":
            await apply_full_name(session, conversation, customer, entity, request_id)
        elif entity.entity == "event_type":
            apply_event_type(session, event, entity, request_id)
        elif entity.entity == "guest_count":
            apply_guest_count(session, event, entity, request_id)
        elif entity.entity == "guest_count_range":
            apply_guest_count_range(session, event, entity, request_id)
        elif entity.entity == "event_date":
            apply_event_date(session, event, entity, request_id)
        elif entity.entity == "estimated_budget":
            apply_budget(session, lead, entity, request_id)
        elif entity.entity == "budget_declined":
            apply_budget_declined(session, lead, request_id)
        elif entity.entity == "requested_services":
            apply_requested_services(session, event, entity, request_id)
        elif entity.entity == "special_requests":
            apply_special_requests(session, event, entity, request_id)


async def apply_full_name(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    name = str(entity.normalized_value or entity.raw_value).strip()
    if not name:
        return
    if entity.needs_confirmation or entity.quality_status == "PENDING_CONFIRMATION":
        conversation.pending_confirmation = {"type": "FULL_NAME_CONFIRMATION", "full_name": name}
        return
    old = {"full_name": customer.full_name}
    customer.full_name = name
    audit_domain_change(
        session,
        "CUSTOMER_NAME_CAPTURED",
        "customer",
        old,
        {"customer_id": customer.id, "full_name": name},
        "Customer name captured during quote data collection",
        request_id,
    )


async def maybe_apply_name_confirmation(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    message_text: str,
    request_id: str | None,
) -> bool:
    pending = conversation.pending_confirmation
    if not isinstance(pending, dict) or pending.get("type") != "FULL_NAME_CONFIRMATION":
        return False
    if not is_affirmative(message_text):
        return False
    name = str(pending["full_name"])
    old = {"full_name": customer.full_name}
    customer.full_name = name
    conversation.pending_confirmation = None
    audit_domain_change(
        session,
        "CUSTOMER_NAME_CONFIRMED",
        "customer",
        old,
        {"customer_id": customer.id, "full_name": name},
        "Customer confirmed inferred name",
        request_id,
    )
    return True


def apply_event_type(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    event_type = str(entity.normalized_value or entity.raw_value).strip().upper()
    if event_type == "BODA":
        event_type = "WEDDING"
    old = {"event_type": event.event_type, "event_type_other": event.event_type_other}
    event.event_type = event_type
    audit_domain_change(
        session,
        "EVENT_TYPE_CAPTURED" if entity.quality_status != "CORRECTED" else "EVENT_TYPE_CORRECTED",
        "event",
        old,
        {"event_id": str(event.event_id), "event_type": event.event_type},
        "Event type captured during quote data collection",
        request_id,
    )


def apply_guest_count(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    count = int(entity.normalized_value)
    old = guest_count_snapshot(event)
    event.guest_count = count
    event.guest_count_min = None
    event.guest_count_max = None
    event.guest_count_status = "PROVIDED"
    audit_domain_change(
        session,
        "GUEST_COUNT_CAPTURED" if entity.quality_status != "CORRECTED" else "GUEST_COUNT_CORRECTED",
        "event",
        old,
        guest_count_snapshot(event),
        "Guest count captured during quote data collection",
        request_id,
    )


def apply_guest_count_range(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    value = entity.normalized_value
    if not isinstance(value, dict):
        return
    old = guest_count_snapshot(event)
    event.guest_count = None
    event.guest_count_min = int(value["min"])
    event.guest_count_max = int(value["max"])
    event.guest_count_status = "RANGE"
    audit_domain_change(
        session,
        "GUEST_COUNT_CAPTURED" if entity.quality_status != "CORRECTED" else "GUEST_COUNT_CORRECTED",
        "event",
        old,
        guest_count_snapshot(event),
        "Guest count range captured during quote data collection",
        request_id,
    )


def apply_event_date(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    triplet = triplet_from_entity(entity)
    old = date_snapshot(event)
    event.event_date = triplet.event_date
    event.event_month = triplet.event_month
    event.event_date_type = triplet.event_date_type
    event.event_date_raw = triplet.event_date_raw[:200]
    audit_domain_change(
        session,
        "EVENT_DATE_CAPTURED" if entity.quality_status != "CORRECTED" else "EVENT_DATE_CORRECTED",
        "event",
        old,
        date_snapshot(event),
        "Event date triplet captured atomically",
        request_id,
    )


def apply_budget(
    session: AsyncSession,
    lead: Lead,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    amount = (
        Decimal(str(entity.normalized_value))
        if entity.normalized_value is not None
        else parse_cop_amount(entity.raw_value)
    )
    old = {
        "estimated_budget": str(lead.estimated_budget) if lead.estimated_budget else None,
        "budget_range": lead.budget_range,
        "budget_data_status": lead.budget_data_status,
    }
    lead.estimated_budget = amount
    lead.budget_range = calculate_budget_range(amount)
    lead.budget_data_status = "PROVIDED"
    audit_domain_change(
        session,
        "BUDGET_CAPTURED",
        "lead",
        old,
        {
            "lead_id": str(lead.lead_id),
            "estimated_budget": str(amount),
            "budget_range": lead.budget_range,
            "budget_data_status": lead.budget_data_status,
        },
        "Budget captured during quote data collection",
        request_id,
    )


def apply_budget_declined(session: AsyncSession, lead: Lead, request_id: str | None) -> None:
    old = {"budget_data_status": lead.budget_data_status}
    lead.budget_data_status = "DECLINED"
    lead.budget_range = "NOT_PROVIDED"
    audit_domain_change(
        session,
        "BUDGET_DECLINED",
        "lead",
        old,
        {"lead_id": str(lead.lead_id), "budget_data_status": "DECLINED"},
        "Customer declined to share budget",
        request_id,
    )


def should_mark_budget_declined_by_evasion(lead: Lead, entities: list[ExtractedEntity]) -> bool:
    if lead.budget_data_status != "ASKED_PENDING":
        return False
    return not any(entity.entity in {"estimated_budget", "budget_declined"} for entity in entities)


def apply_requested_services(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    values = entity.normalized_value
    services = values if isinstance(values, list) else [entity.raw_value]
    for service_name in services:
        service_text = str(service_name).strip()
        if not service_text:
            continue
        session.add(
            EventServiceRequest(
                event_id=event.event_id,
                service_name=service_text,
                status="REQUESTED",
            )
        )
        audit_domain_change(
            session,
            "SERVICE_REQUESTED",
            "event_service_request",
            None,
            {"event_id": str(event.event_id), "service_name": service_text},
            "Customer requested event service",
            request_id,
        )


def apply_special_requests(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    old = {"special_requests": event.special_requests}
    event.special_requests = str(entity.normalized_value or entity.raw_value).strip()
    audit_domain_change(
        session,
        "EVENT_SPECIAL_REQUESTS_CAPTURED",
        "event",
        old,
        {"event_id": str(event.event_id), "special_requests": event.special_requests},
        "Special requests captured during quote data collection",
        request_id,
    )


async def capture_progress(
    session: AsyncSession,
    customer: Customer,
    lead: Lead,
    event: Event,
    conversation: Conversation,
) -> CaptureProgress:
    has_services = (
        await session.scalar(
            select(EventServiceRequest.id)
            .where(
                EventServiceRequest.event_id == event.event_id,
                EventServiceRequest.status == "REQUESTED",
            )
            .limit(1)
        )
        is not None
    )
    return CaptureProgress(
        event_type=event.event_type,
        guest_count=event.guest_count,
        guest_count_min=event.guest_count_min,
        guest_count_max=event.guest_count_max,
        date_resolved=date_resolved(event),
        full_name=customer.full_name,
        full_name_needs_confirmation=isinstance(conversation.pending_confirmation, dict)
        and conversation.pending_confirmation.get("type") == "FULL_NAME_CONFIRMATION",
        budget_data_status=lead.budget_data_status,
        services_requested=has_services,
        pending_fields=conversation.pending_fields or [],
    )


async def transition_to_quote_request_ready(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    lead: Lead,
    event: Event,
    request_id: str | None,
) -> None:
    progress = await capture_progress(session, customer, lead, event, conversation)
    if not minimum_quote_data_complete(progress):
        next_action = select_next_question(progress)
        set_pending_action(conversation, next_action)
        if next_action is not None:
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                customer,
                inbound_message,
                QUESTION_CODE_BY_ACTION[next_action],
                {},
            )
        return

    quote_request = await get_or_create_quote_request(session, lead, event)
    quote_request.minimum_data_complete = True
    quote_request.missing_fields = []
    quote_request.date_pending = date_pending(event)
    quote_request.summary_snapshot = summary_snapshot(customer, lead, event)
    conversation.pending_fields = []
    set_pending_action(conversation, "CONFIRM_QUOTE_REQUEST")
    await transition_conversation(
        session,
        conversation,
        ConversationState.QUOTE_REQUEST_READY,
        actor=SYSTEM_ACTOR,
        reason="Minimum quote data complete",
    )
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        quote_summary_response_code(event),
        quote_summary_variables(event),
    )
    audit_domain_change(
        session,
        "QUOTE_SUMMARY_GENERATED",
        "quote_request",
        None,
        {
            "quote_request_id": str(quote_request.quote_request_id),
            "date_pending": quote_request.date_pending,
        },
        "Minimum quote data complete",
        request_id,
    )


def normalized_entities(classification: IntentClassification) -> list[ExtractedEntity]:
    if classification.extracted_entities:
        return classification.extracted_entities
    entities: list[ExtractedEntity] = []
    for name, value in classification.entities.items():
        if isinstance(value, dict):
            raw_value = str(value.get("raw_value", value.get("raw", "")))
            normalized_value = value.get("normalized_value", value.get("normalized", value))
            quality_status = str(value.get("quality_status", "PROVIDED"))
            needs_confirmation = bool(value.get("needs_confirmation", False))
            validation_errors = value.get("validation_errors", [])
        else:
            raw_value = str(value)
            normalized_value = value
            quality_status = "PROVIDED"
            needs_confirmation = False
            validation_errors = []
        entities.append(
            ExtractedEntity(
                entity=name,
                raw_value=raw_value,
                normalized_value=normalized_value,
                quality_status=quality_status,
                confidence=0.9,
                needs_confirmation=needs_confirmation,
                validation_errors=validation_errors,
            )
        )
    return entities


def resolve_contextual_confirmation_classification(
    conversation: Conversation,
    message_text: str,
    fallback: IntentClassification,
) -> IntentClassification:
    resolved = resolve_contextual_confirmation(
        message_text,
        conversation.pending_action,
        conversation.last_question_code,
    )
    if resolved is None:
        return fallback
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
            "pending_action": conversation.pending_action,
            "last_question_code": conversation.last_question_code,
        },
        reasoning_code=f"DETERMINISTIC_{resolved}",
    )


def triplet_from_entity(entity: ExtractedEntity) -> EventDateTriplet:
    value = entity.normalized_value
    if isinstance(value, dict):
        parsed_date = value.get("event_date")
        return validate_event_date_triplet(
            date.fromisoformat(parsed_date) if parsed_date else None,
            value.get("event_month"),
            value["event_date_type"],
            str(value.get("event_date_raw") or entity.raw_value),
        )
    if isinstance(value, str) and value:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return parse_customer_date_expression(
                entity.raw_value,
                datetime.now(ZoneInfo("America/Bogota")).date(),
            )
        return validate_event_date_triplet(parsed, None, "EXACT", entity.raw_value)
    return parse_customer_date_expression(
        entity.raw_value,
        datetime.now(ZoneInfo("America/Bogota")).date(),
    )


def date_resolved(event: Event) -> bool:
    return (
        event.event_date is not None
        or event.event_month is not None
        or event.event_date_type in {"FLEXIBLE", "UNKNOWN"}
    )


def date_pending(event: Event) -> bool:
    return (
        event.event_date is None
        and event.event_month is None
        and event.event_date_type in {"FLEXIBLE", "UNKNOWN"}
    )


def quote_summary_response_code(event: Event) -> str:
    if date_pending(event):
        return "RESP-QUOTE-008"
    if event.event_month is not None and event.event_date is None:
        return "RESP-QUOTE-005"
    return "RESP-QUOTE-002"


def quote_summary_variables(event: Event) -> dict[str, Any]:
    if date_pending(event):
        return {
            "event_type": event.event_type or "tu celebración",
            "guest_count": guest_count_text(event),
        }
    if event.event_month is not None and event.event_date is None:
        return {"event_month": event.event_month}
    return {
        "event_type": event.event_type or "tu celebración",
        "guest_count": guest_count_text(event),
        "event_date": event.event_date.isoformat() if event.event_date else event.event_month,
        "requested_services_summary": "los servicios solicitados",
    }


def guest_count_text(event: Event) -> str:
    if event.guest_count is not None:
        return str(event.guest_count)
    if event.guest_count_min is not None and event.guest_count_max is not None:
        return f"entre {event.guest_count_min} y {event.guest_count_max}"
    return "por definir"


def summary_snapshot(customer: Customer, lead: Lead, event: Event) -> dict[str, Any]:
    return {
        "full_name": customer.full_name,
        "phone_number": customer.phone_number,
        "event_type": event.event_type,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "event_month": event.event_month,
        "event_date_type": event.event_date_type,
        "event_date_raw": event.event_date_raw,
        "date_pending": date_pending(event),
        "guest_count": event.guest_count,
        "guest_count_min": event.guest_count_min,
        "guest_count_max": event.guest_count_max,
        "budget_data_status": lead.budget_data_status,
        "estimated_budget": str(lead.estimated_budget) if lead.estimated_budget else None,
    }


def add_business_days_bogota(start: datetime, days: int) -> datetime:
    local = start.astimezone(ZoneInfo("America/Bogota"))
    added = 0
    current = local
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current.astimezone(UTC)


def date_snapshot(event: Event) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "event_month": event.event_month,
        "event_date_type": event.event_date_type,
        "event_date_raw": event.event_date_raw,
    }


def guest_count_snapshot(event: Event) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "guest_count": event.guest_count,
        "guest_count_min": event.guest_count_min,
        "guest_count_max": event.guest_count_max,
        "guest_count_status": event.guest_count_status,
    }


def audit_domain_change(
    session: AsyncSession,
    action: str,
    entity: str,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    reason: str,
    request_id: str | None,
) -> None:
    session.add(
        AuditEvent(
            actor=SYSTEM_ACTOR,
            action=action,
            entity=entity,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            request_id=request_id,
        )
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
    if classification.primary_intent in COLLECTION_INTENTS:
        return ConversationState(conversation.state) in {
            ConversationState.BOT_ACTIVE,
            ConversationState.COLLECTING_EVENT_DATA,
            ConversationState.QUOTE_REQUEST_READY,
        }
    if classification.primary_intent in {"CONFIRM", "DENY"}:
        return bool(
            conversation.pending_action
            and conversation.pending_action.startswith("CONFIRM_")
            and conversation.last_question_code
        )
    if classification.primary_intent in SENSITIVE_HANDOFF_INTENTS | TRANSIENT_UNSUPPORTED_INTENTS:
        return (
            ConversationState.WAITING_FOR_HUMAN
            in ALLOWED_TRANSITIONS[ConversationState(conversation.state)]
        )
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

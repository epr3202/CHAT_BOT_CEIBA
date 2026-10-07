from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIErrorReason
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.appointment.service import (
    VisitSchedulingService,
    VisitServiceResult,
    interpret_visit_time,
    parse_visit_time_text,
    resolve_visit_date_text,
    validate_visit_attendees,
)
from app.audit.models import AuditEvent
from app.calendar.adapter import get_calendar_adapter
from app.catalog.models import CatalogSend
from app.catalog.service import (
    CatalogCaptionTooLong,
    CatalogRequestOutcome,
    CatalogRequestResult,
    enqueue_catalog_event_type_prompt,
    enqueue_proactive_catalogs_for_event_type,
    handle_explicit_catalog_request,
    is_catalog_request_category,
)
from app.channel.delivery import (
    TRANSFER_RESPONSE_CODES,
    automatic_context,
    handoff_context,
    payment_evidence_ack_context,
    payment_review_context,
)
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.config.settings import Settings, get_settings
from app.conversation.catalog_event_type import (
    FIXED_PRICE_EVENT_TYPES,
    normalize_catalog_event_type_label,
    resolve_catalog_event_type_match,
    resolve_fixed_price_information_match,
    resolve_fixed_price_information_type,
)
from app.conversation.confirmation import (
    DENIALS,
    normalize_confirmation_text,
    resolve_contextual_confirmation,
)
from app.conversation.entity_validation import (
    Accepted,
    InvalidEntity,
    Rejection,
    decode_entities,
    rejection,
    validate_entities,
    validate_entity,
)
from app.conversation.explicit_human import EXPLICIT_HUMAN_REASON
from app.conversation.faq_catalog import NO_APPROVED_ANSWER, response_code_for_category
from app.conversation.fixed_price_booking import (
    BOOKING_ACTIONS,
    FIXED_PRICE_BOOKING_REASON,
    GENERIC_CAPTURE_ACTIONS,
    SELF_SERVICE_BOOKING_REASON,
    booking_guard_eligible,
    is_catalog_plan_choice,
    is_explicit_visit_request,
    is_fixed_price_booking,
    is_fixed_price_catalog_followup,
    match_booking_plan,
)
from app.conversation.knowledge import KnowledgeRenderError, get_latest_response, render_response
from app.conversation.models import Conversation
from app.conversation.pending_actions import validate_pending_action
from app.conversation.pending_confirmation import (
    PendingProposal,
    proposal_context,
    read_pending,
)
from app.conversation.presentation import (
    format_date_natural,
    format_event_type,
    format_month_natural,
)
from app.conversation.service import ALLOWED_TRANSITIONS, transition_conversation
from app.conversation.services_catalog import (
    match_requested_services,
)
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.event_type import normalize_event_type
from app.event.models import Event, EventServiceRequest
from app.event.validation import EventDateTriplet
from app.handoff.models import Handoff
from app.handoff.service import create_handoff
from app.lead.budget import calculate_budget_range
from app.lead.models import Lead
from app.orchestrator.inbox_effects import defer_agenda_service
from app.orchestrator.slot_filling import (
    QUESTION_CODE_BY_ACTION,
    CaptureProgress,
    minimum_quote_data_complete,
    pending_fields_for,
    select_next_question,
)
from app.payment.models import PaymentEvidence
from app.payment.service import create_payment_evidence
from app.plan.models import Plan
from app.quote.models import QuoteRequest
from app.scheduling.availability import AvailabilityService

logger = structlog.get_logger(__name__)
_decision_source: ContextVar[Literal["DETERMINISTIC", "LLM", "FALLBACK"]] = ContextVar(
    "orchestrator_decision_source", default="LLM"
)

SYSTEM_ACTOR = "SYSTEM"
SENSITIVE_HANDOFF_INTENTS = {
    "HUMAN_REQUEST",
    "COMPLAINT",
    "EMERGENCY",
    "PAYMENT_MESSAGE",
    "EVENT_CANCELLATION",
}
TRANSIENT_UNSUPPORTED_INTENTS = {
    "RESERVATION_INFORMATION",
}
VISIT_INTENTS = {"SCHEDULE_VISIT", "RESCHEDULE_VISIT", "CANCEL_VISIT"}
APPOINTMENT_FLOW_STATES = {
    ConversationState.WAITING_FOR_APPOINTMENT_DATE,
    ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
    ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
}
DIRECT_APPOINTMENT_ANSWER_ACTIONS = {
    "COLLECT_CUSTOMER_NAME",
    "COLLECT_VISIT_ATTENDEES",
    "COLLECT_VISIT_REASON",
}
COLLECTION_INTENTS = {"EVENT_INFORMATION", "QUOTE_REQUEST", "MODIFY_EVENT_DATA"}
CRITICAL_STATES = {
    ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
    ConversationState.WAITING_FOR_APPOINTMENT_DATE,
    ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
    ConversationState.QUOTE_REQUEST_READY,
}
CATALOG_CAPTURE_ACTION = "COLLECT_CATALOG_EVENT_TYPE"
CATALOG_CAPTURE_ABANDON_INTENTS = (
    SENSITIVE_HANDOFF_INTENTS
    | TRANSIENT_UNSUPPORTED_INTENTS
    | VISIT_INTENTS
    | {"QUOTE_REQUEST", "MODIFY_EVENT_DATA", "FAREWELL"}
)

HANDOFF_REASON_BY_INTENT = {
    "HUMAN_REQUEST": "CUSTOMER_REQUEST",
    "COMPLAINT": "COMPLAINT",
    "EMERGENCY": "URGENT_EVENT",
    "PAYMENT_MESSAGE": "PAYMENT_REVIEW",
    "EVENT_CANCELLATION": "CANCELLATION",
}


AUDIO_WRITTEN_CONFIRM_ACTIONS = frozenset(
    {
        "CONFIRM_BOOKING",
        "CONFIRM_APPOINTMENT",
        "CONFIRM_RESCHEDULE",
        "CONFIRM_VISIT_CANCELLATION",
        "CONFIRM_QUOTE_REQUEST",
    }
)


def audio_confirmation_requires_text(input_origin: str, pending_action: str | None) -> bool:
    return input_origin == "AUDIO_TRANSCRIPT" and pending_action in AUDIO_WRITTEN_CONFIRM_ACTIONS


@dataclass(frozen=True)
class OrchestrationInput:
    conversation: Conversation
    customer: Customer
    inbound_message: Message
    message_text: str
    request_id: uuid.UUID | None = None
    decision_source: Literal["DETERMINISTIC", "LLM", "FALLBACK"] = "LLM"
    directed_event_type: str | None = None
    services_resolution_failed: bool = False
    confidence_entity_rescued: bool = False
    input_origin: Literal["TEXT", "AUDIO_TRANSCRIPT"] = "TEXT"
    transcription_id: int | None = None


@dataclass(frozen=True)
class PendingConfirmationResolution:
    classification: IntentClassification
    confirmation_uplifted: bool


def record_audio_response_code(session: AsyncSession, code: str) -> None:
    info = session.info
    if isinstance(info, dict) and "audio_response_codes" in info:
        info["audio_response_codes"].append(code)


async def orchestrate_inbound_message(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification | None,
    ai_error_reason: AIErrorReason | None = None,
) -> None:
    conversation = orchestration_input.conversation
    state_before = ConversationState(conversation.state).value
    pending_before = conversation.pending_action
    audio_turn = orchestration_input.input_origin == "AUDIO_TRANSCRIPT"
    response_codes: list[str] = []
    info = session.info
    previous_codes = info.get("audio_response_codes") if isinstance(info, dict) else None
    if audio_turn and isinstance(info, dict):
        info["audio_response_codes"] = response_codes
    intent = classification.primary_intent if classification is not None else "UNKNOWN"
    decision_token = _decision_source.set(orchestration_input.decision_source)
    try:
        await _orchestrate_inbound_message(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            ai_error_reason,
        )
    finally:
        decision_source = _decision_source.get()
        _decision_source.reset(decision_token)
        state_after = ConversationState(conversation.state).value
        transition = f"{state_before}->{state_after}" if state_before != state_after else None
        logger.info(
            "orchestrator_decision",
            conversation_id=conversation.id,
            request_id=(
                str(orchestration_input.request_id)
                if orchestration_input.request_id is not None
                else None
            ),
            intent=intent,
            state_before=state_before,
            state_after=state_after,
            transition=transition,
            decision_source=decision_source,
            input_origin=orchestration_input.input_origin,
            pending_action=conversation.pending_action,
        )
        if audio_turn:
            if isinstance(info, dict):
                if previous_codes is None:
                    info.pop("audio_response_codes", None)
                else:
                    info["audio_response_codes"] = previous_codes
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="AUDIO_TRANSCRIPT_TURN_APPLIED",
                    entity="message",
                    old_value=None,
                    new_value={
                        "message_id": orchestration_input.inbound_message.id,
                        "transcription_id": orchestration_input.transcription_id,
                        "input_origin": orchestration_input.input_origin,
                        "decision_source": decision_source,
                        "state_before": state_before,
                        "state_after": state_after,
                        "pending_before": pending_before,
                        "pending_after": conversation.pending_action,
                        "response_codes": response_codes,
                    },
                    reason="AUDIO_TRANSCRIPT_TURN_APPLIED",
                    request_id=orchestration_input.request_id,
                )
            )


async def _orchestrate_inbound_message(
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

    if audio_confirmation_requires_text(
        orchestration_input.input_origin, conversation.pending_action
    ):
        last_question_code = conversation.last_question_code
        try:
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                customer,
                inbound_message,
                "RESP-AUDIO-WRITTEN-CONFIRM-001",
                {},
            )
        finally:
            conversation.last_question_code = last_question_code
        session.add(
            AuditEvent(
                actor="SYSTEM",
                action="AUDIO_CONFIRMATION_REQUIRES_TEXT",
                entity="message",
                old_value=None,
                new_value={
                    "message_id": inbound_message.id,
                    "pending_action": conversation.pending_action,
                },
                reason="AUDIO_CONFIRMATION_REQUIRES_TEXT",
                request_id=orchestration_input.request_id,
            )
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

    if (
        orchestration_input.decision_source == "DETERMINISTIC"
        and classification.reasoning_code == SELF_SERVICE_BOOKING_REASON
    ):
        from app.orchestrator.booking_flow import handle_booking_start

        await handle_booking_start(session, settings, knowledge_sessionmaker, orchestration_input)
        return

    if (
        orchestration_input.decision_source == "DETERMINISTIC"
        and classification.reasoning_code == FIXED_PRICE_BOOKING_REASON
    ):
        await handle_fixed_price_booking(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if (
        orchestration_input.decision_source == "DETERMINISTIC"
        and classification.primary_intent == "HUMAN_REQUEST"
        and classification.reasoning_code == EXPLICIT_HUMAN_REASON
    ):
        # Human guards above and R2 ownership still apply. Do not accept an old
        # confirmation or apply model-confidence thresholds to this explicit rule.
        await route_classification(
            session, settings, knowledge_sessionmaker, orchestration_input, classification
        )
        return

    if conversation.pending_action in BOOKING_ACTIONS:
        from app.orchestrator.booking_flow import handle_booking_step

        await handle_booking_step(session, settings, knowledge_sessionmaker, orchestration_input)
        return

    _, envelope_errors = decode_entities(classification)
    envelope_errors = [
        item for item in envelope_errors if item.code in {"INVALID_ENVELOPE", "INVALID_LEGACY"}
    ]
    if envelope_errors:
        for item in envelope_errors:
            audit_entity_rejection(session, item, orchestration_input.request_id, conversation)
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            "RESP-FALLBACK-004",
            {},
        )
        return

    classification = resolve_contextual_confirmation_classification(
        conversation,
        orchestration_input.message_text,
        classification,
    )
    classification = with_directed_event_type(
        classification,
        orchestration_input.directed_event_type,
    )
    classification = normalize_classification_event_type_entities(
        session,
        classification,
        orchestration_input.request_id,
    )
    if orchestration_input.confidence_entity_rescued:
        audit_uncertain_entity_rescue(
            session,
            conversation,
            classification,
            orchestration_input.request_id,
        )
    if orchestration_input.services_resolution_failed:
        await handle_failed_services_resolution(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return
    (
        catalog_handled,
        understanding_failure_already_counted,
    ) = await resolve_catalog_event_type_capture(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
    )
    if catalog_handled:
        return
    pending_confirmation_resolution = await resolve_pending_confirmation(
        session,
        conversation,
        classification,
        orchestration_input.message_text,
        orchestration_input.request_id,
    )
    classification = pending_confirmation_resolution.classification
    classification = normalize_classification_event_type_entities(
        session,
        classification,
        orchestration_input.request_id,
    )

    if pending_confirmation_resolution.confirmation_uplifted:
        audit_confirmation_uplift(
            session,
            conversation,
            classification,
            orchestration_input.request_id,
        )
    elif classification.confidence < settings.ai_confidence_uncertain:
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
        batch = validate_entities(classification, entity_today())
        if batch.rejected:
            for item in batch.rejected:
                audit_entity_rejection(
                    session,
                    item,
                    orchestration_input.request_id,
                    conversation,
                )
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
            return
        audit_confidence_decision(
            session,
            conversation,
            classification,
            decision="ASK_CONFIRMATION",
            threshold=settings.ai_confidence_probable,
            request_id=orchestration_input.request_id,
        )
        conversation.pending_confirmation = {
            "type": "CLASSIFICATION_CONFIRMATION",
            "version": 1,
            "context": proposal_context(conversation.state, conversation.active_lead_id),
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
        understanding_failure_already_counted=understanding_failure_already_counted,
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


async def booking_event_context(
    session: AsyncSession,
    conversation: Conversation,
) -> dict[str, Any] | None:
    self_service = get_settings().self_service_booking_enabled
    if not booking_guard_eligible(
        conversation.state,
        conversation.pending_action,
        conversation.bot_enabled,
        self_service=self_service,
    ):
        return None
    # Eligible claim/apply/prepare loads lead + event, then refreshes event with FOR UPDATE.
    event = await active_event(session, await active_lead(session, conversation))
    if event is not None:
        event = await session.get(
            Event,
            event.event_id,
            with_for_update=True,
            populate_existing=True,
        )
    if event is None and not self_service:
        return None
    catalog_sent = (
        await session.scalar(
            select(CatalogSend.catalog_send_id)
            .join(
                Outbox,
                Outbox.id == CatalogSend.outbound_message_id,
            )
            .where(CatalogSend.lead_id == event.lead_id, Outbox.status == "SENT")
            .limit(1)
        )
        if event is not None
        else None
    )
    plans = (
        await session.scalars(
            select(Plan)
            .where(
                Plan.active.is_(True),
                Plan.event_type.in_(FIXED_PRICE_EVENT_TYPES),
            )
            .order_by(Plan.sort_order, Plan.code)
        )
        if self_service
        else []
    )
    return {
        "event_id": str(event.event_id) if event is not None else None,
        "event_type": event.event_type if event is not None else None,
        "catalog_sent": "yes" if catalog_sent is not None else None,
        "plans": [
            {"plan_id": str(plan.plan_id), "name": plan.name, "event_type": plan.event_type}
            for plan in plans
        ],
    }


def deterministic_booking_or_catalog_classification(
    message_text: str,
    context: dict[str, Any],
    settings: Settings | None = None,
) -> IntentClassification | None:
    # Precedence: pending_action routes → D1 guard → CATALOG_CAPTURE/type resolution → LLM.
    facts = context.get("booking_event") or {}
    if context.get("pending_action") in BOOKING_ACTIONS:
        return IntentClassification(
            primary_intent="UNKNOWN",
            sub_intent=None,
            confidence=0,
            requested_action=None,
            needs_confirmation=False,
            needs_human=False,
            handoff_reason=None,
            priority="NORMAL",
            reasoning_code="BOOKING_STEP",
        )
    self_service = settings is not None and settings.self_service_booking_enabled
    eligible = booking_guard_eligible(
        context.get("state"),
        context.get("pending_action"),
        context.get("bot_enabled", True),
        self_service=self_service,
    )
    if eligible and is_explicit_visit_request(message_text):
        return None
    catalog_followup = self_service and is_fixed_price_catalog_followup(
        facts.get("event_type"), context.get("last_question_code")
    )
    plans = facts.get("plans", [])
    if catalog_followup:
        plans = [plan for plan in plans if plan["event_type"] == facts["event_type"]]
    named_plan = match_booking_plan(message_text, plans) if self_service else None
    explicit_date = (
        resolve_visit_date_text(
            message_text,
            today=current_bogota_datetime().date(),
            require_absolute_confirmation=True,
        )
        if self_service and (facts.get("catalog_sent") == "yes" or catalog_followup)
        else None
    )
    match = resolve_catalog_event_type_match(
        message_text,
        answering_event_type_question=context.get("pending_action") == CATALOG_CAPTURE_ACTION,
    )
    ambiguous_plan = (
        catalog_followup
        and named_plan is None
        and sum(match_booking_plan(message_text, [plan]) is not None for plan in plans) > 1
    )
    if eligible and (
        named_plan is not None
        or (
            catalog_followup
            and match is None
            and (
                ambiguous_plan
                or is_catalog_plan_choice(
                    message_text,
                    has_date=explicit_date is not None and explicit_date.resolved_date is not None,
                )
            )
        )
        or is_fixed_price_booking(
            message_text,
            facts.get("event_type"),
        )
        or (
            self_service
            and facts.get("event_type") in FIXED_PRICE_EVENT_TYPES
            and explicit_date is not None
            and explicit_date.resolved_date is not None
            and explicit_date.interpretation == "EXACTA"
            and parse_visit_time_text(message_text, require_explicit=True) is not None
        )
    ):
        return IntentClassification(
            primary_intent="HUMAN_REQUEST",
            sub_intent=None,
            confidence=0,
            needs_human=True,
            needs_confirmation=False,
            priority="NORMAL",
            handoff_reason="RESERVATION_CONFIRMATION",
            requested_action="CREATE_HANDOFF",
            reasoning_code=(
                SELF_SERVICE_BOOKING_REASON if self_service else FIXED_PRICE_BOOKING_REASON
            ),
        )
    mentioned_type = match.event_type if match is not None else None
    if context.get("pending_action") == CATALOG_CAPTURE_ACTION and mentioned_type is not None:
        return IntentClassification(
            primary_intent="UNKNOWN",
            sub_intent=None,
            confidence=0,
            requested_action=None,
            needs_confirmation=False,
            needs_human=False,
            handoff_reason=None,
            priority="NORMAL",
            reasoning_code="CATALOG_LABEL_MATCH",
        )
    if context.get("pending_action") in {None, "NONE"} and mentioned_type is not None:
        catalog_request = bool(
            {"catalogo", "catalogos"}
            & set(normalize_catalog_event_type_label(message_text).split())
        )
        explicit_proposal = (
            match is not None
            and match.event_type == "PROPOSAL"
            and len(normalize_catalog_event_type_label(match.matched_label).split()) >= 2
        )
        if catalog_request or explicit_proposal:
            return IntentClassification(
                primary_intent="GENERAL_INFORMATION",
                sub_intent=None,
                confidence=1.0,
                information_category="catalog_request" if catalog_request else "tipos de eventos",
                extracted_entities=[
                    ExtractedEntity(
                        entity="event_type",
                        raw_value=message_text,
                        normalized_value=mentioned_type,
                        quality_status="PROVIDED",
                        confidence=1.0,
                    )
                ],
                requested_action=None,
                needs_confirmation=False,
                needs_human=False,
                handoff_reason=None,
                priority="NORMAL",
                reasoning_code="CATALOG_MENTION_MATCH"
                if catalog_request
                else "FIXED_PRICE_INFORMATION_MATCH",
            )
    return None


async def handle_fixed_price_booking(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    facts = await booking_event_context(session, conversation)
    if not facts or not is_fixed_price_booking(
        orchestration_input.message_text,
        facts["event_type"],
    ):
        raise ValueError("Fixed-price booking context changed before settlement")
    event = await session.get(Event, UUID(facts["event_id"]))
    decision = resolve_visit_date_text(
        orchestration_input.message_text,
        today=current_bogota_datetime().date(),
        require_absolute_confirmation=True,
    )
    detail = f"Nueva solicitud de reserva para {format_event_type(event.event_type)}."
    if decision.resolved_date is not None:
        old = date_snapshot(event)
        if not decision.needs_confirmation:
            event.event_date = decision.resolved_date
            event.event_month = None
            event.event_date_type = "EXACT"
        event.event_date_raw = decision.matched_text
        audit_domain_change(
            session,
            "EVENT_DATE_CAPTURED",
            "event",
            old,
            date_snapshot(event),
            "Fecha solicitada para reserva; confirmación humana si es relativa o contradictoria",
            orchestration_input.request_id,
        )
        detail += f" Fecha solicitada: {format_date_natural(decision.resolved_date)}"
        detail += " (pendiente de confirmación)." if decision.needs_confirmation else "."
    await create_handoff_and_pause(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
        reason="RESERVATION_CONFIRMATION",
        priority="NORMAL",
        detail=detail,
    )


def current_pending(conversation: Conversation) -> PendingProposal:
    return read_pending(
        conversation.pending_confirmation,
        state=conversation.state,
        pending_action=conversation.pending_action,
        last_question_code=conversation.last_question_code,
        active_lead_id=conversation.active_lead_id,
    )


def discard_pending(
    session: AsyncSession,
    conversation: Conversation,
    pending: PendingProposal,
    request_id: str | None,
    reason: str,
) -> None:
    audit_orchestrator_event(
        session,
        "AI_CONFIRMATION_DISCARDED"
        if pending.kind == "CLASSIFICATION"
        else "PENDING_CONFIRMATION_DISCARDED",
        conversation,
        reason=reason,
        request_id=request_id,
        extra={"pending_type": pending.kind, "discard_reason": reason},
    )
    conversation.pending_confirmation = None


async def resolve_pending_confirmation(
    session: AsyncSession,
    conversation: Conversation,
    classification: IntentClassification,
    message_text: str,
    request_id: str | None,
) -> PendingConfirmationResolution:
    pending = current_pending(conversation)
    if pending.kind == "ABSENT":
        return PendingConfirmationResolution(classification, False)
    if pending.kind in {"INVALID", "RESOLVED"}:
        if (
            pending.reason == "INVALID_NAME_SHAPE"
            and conversation.pending_action == "COLLECT_CUSTOMER_NAME"
        ):
            conversation.pending_fields = list(
                dict.fromkeys(
                    [*(conversation.pending_fields or []), "full_name"],
                )
            )
        discard_pending(session, conversation, pending, request_id, pending.reason or "INVALID")
        return PendingConfirmationResolution(classification, False)

    if (
        classification.primary_intent == "GENERAL_INFORMATION"
        and not is_affirmative(message_text)
        and normalize_confirmation_text(message_text) not in DENIALS
        and classification.information_category is not None
        and not is_catalog_request_category(classification.information_category)
        and response_code_for_category(classification.information_category) != NO_APPROVED_ANSWER
    ):
        # A recognized interruption does not create a new proposal. Legacy already
        # validated in its actual question context is made explicit before that changes.
        if "version" not in conversation.pending_confirmation:
            conversation.pending_confirmation = {
                **conversation.pending_confirmation,
                "type": "FULL_NAME_CONFIRMATION"
                if pending.kind == "NAME"
                else "CLASSIFICATION_CONFIRMATION",
                "version": 1,
                "context": proposal_context(conversation.state, conversation.active_lead_id),
            }
        return PendingConfirmationResolution(classification, False)

    if pending.kind == "NAME":
        if normalize_confirmation_text(message_text) in DENIALS:
            discard_pending(session, conversation, pending, request_id, "NAME_DENIED")
        return PendingConfirmationResolution(classification, False)

    corrected = any(e.quality_status == "CORRECTED" for e in normalized_entities(classification))
    if is_affirmative(message_text) and not corrected:
        confirmed = pending.classification
        # The discriminator guarantees this model; unexpected programming faults propagate.
        assert confirmed is not None
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
        if conversation.pending_action == "CLASSIFY_MESSAGE":
            set_pending_action(conversation, None)
        return PendingConfirmationResolution(confirmed, True)

    discard_pending(session, conversation, pending, request_id, "NOT_AFFIRMATIVE_OR_CORRECTED")
    return PendingConfirmationResolution(classification, False)


async def resolve_catalog_event_type_capture(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> tuple[bool, bool]:
    conversation = orchestration_input.conversation
    if conversation.pending_action != CATALOG_CAPTURE_ACTION:
        return False, False

    match = resolve_catalog_event_type_match(
        orchestration_input.message_text, answering_event_type_question=True
    )
    event_type = (
        match.event_type if match is not None else classified_catalog_event_type(classification)
    )

    if event_type is not None:
        lead = await active_lead(session, conversation)
        event = await active_event(session, lead)
        result = await handle_explicit_catalog_request(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            lead.lead_id if lead is not None else None,
            event.event_type if event is not None else None,
            event_type,
            orchestration_input.request_id,
        )
        if not catalog_result_requires_human(result):
            set_pending_action(conversation, None)
        if result.outcome == CatalogRequestOutcome.SENT:
            conversation.failed_understanding_count = 0
        conversation.pending_confirmation = None
        persist_classification_context(conversation, classification)
        audit_orchestrator_event(
            session,
            "CATALOG_EVENT_TYPE_RESOLVED",
            conversation,
            reason="Catalog event type resolved",
            request_id=orchestration_input.request_id,
            extra={
                "event_type": event_type,
                "outcome": result.outcome.value,
                "sent_count": result.sent_count,
                "matched_label": match.matched_label if match is not None else None,
                "decision_source": "DETERMINISTIC"
                if match is not None
                else orchestration_input.decision_source,
                "source": "CATALOG_CAPTURE_MENTION"
                if match is not None
                else "EVENT_TYPE_EXTRACTION"
                if orchestration_input.directed_event_type is not None
                else "INTENT_CLASSIFICATION",
            },
        )
        return True, False

    if catalog_capture_should_be_abandoned(classification, settings):
        set_pending_action(conversation, None)
        conversation.pending_confirmation = None
        audit_orchestrator_event(
            session,
            "CATALOG_CAPTURE_ABANDONED",
            conversation,
            reason="Customer changed to a distinct actionable intent",
            request_id=orchestration_input.request_id,
            extra={
                "intent": classification.primary_intent,
                "confidence": classification.confidence,
            },
        )
        return False, False

    conversation.failed_understanding_count += 1
    attempt = conversation.failed_understanding_count
    audit_orchestrator_event(
        session,
        "CATALOG_EVENT_TYPE_UNRESOLVED",
        conversation,
        reason="Catalog event type could not be resolved deterministically",
        request_id=orchestration_input.request_id,
        extra={"attempt": attempt, "failed_understanding_count": attempt},
    )
    conversation.pending_confirmation = None

    if attempt == 1:
        result = await enqueue_catalog_event_type_prompt(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            orchestration_input.request_id,
        )
        if result.outcome == CatalogRequestOutcome.ASK_EVENT_TYPE:
            set_pending_action(conversation, CATALOG_CAPTURE_ACTION)
        elif not catalog_result_requires_human(result):
            set_pending_action(conversation, None)
        persist_classification_context(conversation, classification)
        return True, False

    set_pending_action(conversation, None)
    return False, True


def classified_catalog_event_type(classification: IntentClassification) -> str | None:
    for entity in normalized_entities(classification):
        if entity.entity != "event_type" or entity.quality_status == "INVALID":
            continue
        candidate = normalize_event_type(entity.normalized_value or entity.raw_value)
        if candidate is not None:
            return candidate
    return None


def catalog_result_requires_human(result: CatalogRequestResult) -> bool:
    return result.outcome == CatalogRequestOutcome.HANDOFF or (
        result.outcome == CatalogRequestOutcome.UNAVAILABLE and result.event_type is not None
    )


def catalog_capture_should_be_abandoned(
    classification: IntentClassification, settings: Settings
) -> bool:
    if classification.confidence < settings.ai_confidence_probable:
        return False
    if classification.primary_intent in CATALOG_CAPTURE_ABANDON_INTENTS:
        return True
    return classification.primary_intent == "GENERAL_INFORMATION" and bool(
        classification.information_category
        and not is_catalog_request_category(classification.information_category)
    )


async def route_classification(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
    *,
    understanding_failure_already_counted: bool = False,
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

    if state in APPOINTMENT_FLOW_STATES:
        await handle_appointment_flow_state(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if conversation.pending_action == "CONFIRM_VISIT_CANCELLATION":
        await handle_visit_cancellation_confirmation(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if (
        state == ConversationState.COLLECTING_EVENT_DATA
        and intent in VISIT_INTENTS
        and classification.confidence < settings.ai_confidence_safe
    ):
        await handle_collecting_event_data(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if intent in VISIT_INTENTS:
        await handle_visit_intent(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
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
            understanding_failure_already_counted=understanding_failure_already_counted,
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
            understanding_failure_already_counted=understanding_failure_already_counted,
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
        understanding_failure_already_counted=understanding_failure_already_counted,
    )


async def handle_visit_intent(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    intent = classification.primary_intent
    if intent == "SCHEDULE_VISIT":
        await start_visit_scheduling(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    service = visit_scheduling_service(settings, knowledge_sessionmaker)
    if intent == "RESCHEDULE_VISIT":
        result = await service.request_reschedule(orchestration_input.customer.id)
        if result.needs_handoff:
            await create_handoff_and_pause(
                session,
                settings,
                knowledge_sessionmaker,
                orchestration_input,
                classification,
                reason="OTHER",
                priority=classification.priority,
                detail="Visit reschedule requires appointment identification",
                response_code_override=result.response_code,
            )
            return
        current_draft = dict(orchestration_input.conversation.visit_draft or {})
        resume = current_draft.get("resume") or capture_resume_marker(
            orchestration_input.conversation
        )
        orchestration_input.conversation.visit_draft = {
            "mode": "RESCHEDULE",
            "appointment_id": str(result.appointment_id),
            "resume": resume,
        }
        await move_to_appointment_date(session, orchestration_input.conversation)
        set_pending_action(orchestration_input.conversation, "SELECT_VISIT_DATE")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            orchestration_input.conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            result.response_code,
            result.variables,
        )
        persist_classification_context(orchestration_input.conversation, classification)
        return

    result = await service.request_cancellation(orchestration_input.customer.id)
    if result.needs_handoff:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="CANCELLATION",
            priority=classification.priority,
            detail="Visit cancellation requires appointment identification",
            response_code_override=result.response_code,
        )
        return
    orchestration_input.conversation.visit_draft = {
        "mode": "CANCEL",
        "appointment_id": str(result.appointment_id),
        "response_variables": result.variables,
        "resume": capture_resume_marker(orchestration_input.conversation),
    }
    set_pending_action(orchestration_input.conversation, "CONFIRM_VISIT_CANCELLATION")
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        orchestration_input.conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        result.response_code,
        result.variables,
    )
    persist_classification_context(orchestration_input.conversation, classification)


async def start_visit_scheduling(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
    *,
    restart: bool = False,
) -> None:
    conversation = orchestration_input.conversation
    existing_draft = dict(conversation.visit_draft or {})
    resume = existing_draft.get("resume") or capture_resume_marker(conversation)
    conversation.visit_draft = {"mode": "SCHEDULE", "resume": resume}
    await move_to_appointment_date(session, conversation)
    set_pending_action(conversation, "SELECT_VISIT_DATE")
    if not restart:
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-VISIT-002",
            {},
        )
    persist_classification_context(conversation, classification)
    conversation.failed_understanding_count = 0
    await handle_waiting_for_appointment_date(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
    )


async def handle_appointment_flow_state(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    state = ConversationState(orchestration_input.conversation.state)
    if (
        state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION
        and orchestration_input.conversation.pending_action in DIRECT_APPOINTMENT_ANSWER_ACTIONS
    ):
        await handle_waiting_for_appointment_selection(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return
    if state == ConversationState.WAITING_FOR_APPOINTMENT_DATE:
        date_decision = resolve_visit_date_text(
            orchestration_input.message_text,
            today=current_bogota_datetime().date(),
            require_absolute_confirmation=True,
        )
        if date_decision.interpretation != "NO_INTERPRETABLE":
            await handle_waiting_for_appointment_date(
                session,
                settings,
                knowledge_sessionmaker,
                orchestration_input,
                classification,
            )
            return
    elif state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION:
        draft = require_visit_draft(orchestration_input.conversation)
        offered_slots = [time.fromisoformat(value) for value in draft.get("offered_slots", [])]
        time_decision = interpret_visit_time(orchestration_input.message_text, offered_slots)
        if time_decision.interpretation != "NO_INTERPRETABLE":
            await handle_waiting_for_appointment_selection(
                session,
                settings,
                knowledge_sessionmaker,
                orchestration_input,
                classification,
            )
            return
    else:
        confirmation_intent = resolve_contextual_confirmation(
            orchestration_input.message_text,
            orchestration_input.conversation.pending_action,
            orchestration_input.conversation.last_question_code,
        )
        if confirmation_intent is not None:
            if classification.primary_intent != confirmation_intent:
                classification = classification.model_copy(
                    update={"primary_intent": confirmation_intent}
                )
            await handle_appointment_confirmation(
                session,
                settings,
                knowledge_sessionmaker,
                orchestration_input,
                classification,
            )
            return

    intent = classification.primary_intent
    if intent == "SCHEDULE_VISIT":
        await start_visit_scheduling(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            restart=True,
        )
        return
    if intent == "CANCEL_VISIT":
        await cancel_visit_attempt(
            session,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return
    if intent == "RESCHEDULE_VISIT":
        await handle_visit_intent(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    if state == ConversationState.WAITING_FOR_APPOINTMENT_DATE:
        await handle_waiting_for_appointment_date(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return
    if state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION:
        await handle_waiting_for_appointment_selection(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return
    await handle_appointment_confirmation(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
    )


async def handle_waiting_for_appointment_date(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    decision = resolve_visit_date_text(
        orchestration_input.message_text,
        today=current_bogota_datetime().date(),
        require_absolute_confirmation=True,
    )
    resolved_date = decision.resolved_date
    date_to_confirm = resolved_date if decision.inferred_month else None
    if conversation.pending_action == "CONFIRM_VISIT_DATE":
        draft = require_visit_draft(conversation)
        try:
            candidate = date.fromisoformat(draft.get("candidate_visit_date", ""))
        except (TypeError, ValueError):
            candidate = None
        confirmation = resolve_contextual_confirmation(
            orchestration_input.message_text,
            conversation.pending_action,
            conversation.last_question_code,
        )
        if confirmation == "DENY":
            draft.pop("candidate_visit_date", None)
            conversation.visit_draft = draft
            set_pending_action(conversation, "SELECT_VISIT_DATE")
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                orchestration_input.customer,
                orchestration_input.inbound_message,
                "RESP-VISIT-003",
                {},
            )
            return
        if confirmation == "CONFIRM" and candidate is not None:
            resolved_date = candidate
            date_to_confirm = None
        elif resolved_date is None and candidate is not None:
            date_to_confirm = candidate
        if date_to_confirm is None:
            draft.pop("candidate_visit_date", None)
            conversation.visit_draft = draft
            set_pending_action(conversation, "SELECT_VISIT_DATE")

    if date_to_confirm is not None:
        draft = require_visit_draft(conversation)
        draft["candidate_visit_date"] = date_to_confirm.isoformat()
        conversation.visit_draft = draft
        set_pending_action(conversation, "CONFIRM_VISIT_DATE")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-EVENT-DATA-003",
            {"resolved_date": date_to_confirm},
        )
        return

    if decision.needs_confirmation or decision.interpretation == "RELATIVA":
        # Other relative expressions and conflicting weekdays keep their
        # existing request for a new date; only inferred months use confirmation.
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-VISIT-003",
            {},
        )
        return
    if resolved_date is None:
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-VISIT-003",
            {},
        )
        return

    availability = await availability_service(settings, knowledge_sessionmaker).available_slots(
        resolved_date,
        today=current_bogota_datetime().date(),
        request_id=orchestration_input.request_id,
    )
    if availability.requires_review:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="SYSTEM_ERROR",
            priority="URGENT",
            detail="Calendar unavailable while offering visit slots",
            response_code_override=availability.response_code,
        )
        return
    if not availability.slots:
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            availability.response_code,
            {},
        )
        return

    draft = require_visit_draft(conversation)
    draft["visit_date"] = resolved_date.isoformat()
    draft["offered_slots"] = [slot.start_time.strftime("%H:%M") for slot in availability.slots]
    conversation.visit_draft = draft
    await transition_conversation(
        session,
        conversation,
        ConversationState.WAITING_FOR_APPOINTMENT_SELECTION,
        actor=SYSTEM_ACTOR,
        reason="Validated visit date has available slots",
    )
    set_pending_action(conversation, "SELECT_VISIT_TIME")
    selected = interpret_visit_time(
        orchestration_input.message_text,
        [slot.start_time for slot in availability.slots],
        require_explicit=True,
    )
    if selected.accepted:
        await handle_waiting_for_appointment_selection(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        availability.response_code,
        {
            "visit_date": format_date_natural(resolved_date),
            "appointment_options": format_appointment_options(
                [slot.start_time for slot in availability.slots]
            ),
        },
    )
    persist_classification_context(conversation, classification)


async def handle_waiting_for_appointment_selection(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    draft = require_visit_draft(conversation)
    pending_action = conversation.pending_action
    if pending_action == "SELECT_VISIT_TIME":
        offered_slots = [time.fromisoformat(value) for value in draft.get("offered_slots", [])]
        result = interpret_visit_time(orchestration_input.message_text, offered_slots)
        if not result.accepted or result.preferred_visit_time is None:
            variables = (
                {"appointment_options": format_appointment_options(offered_slots)}
                if result.response_code == "RESP-VISIT-TIME-003"
                else {}
            )
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                orchestration_input.customer,
                orchestration_input.inbound_message,
                result.response_code or "RESP-VISIT-TIME-003",
                variables,
            )
            return
        draft["visit_time"] = result.preferred_visit_time.strftime("%H:%M")
        conversation.visit_draft = draft
        if draft.get("mode") == "RESCHEDULE":
            await prepare_reschedule_confirmation(
                session,
                settings,
                knowledge_sessionmaker,
                orchestration_input,
                classification,
            )
            return
        set_pending_action(conversation, "COLLECT_VISIT_ATTENDEES")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-VISIT-DATA-001",
            {},
        )
        return

    if pending_action == "COLLECT_VISIT_ATTENDEES":
        attendee_count = parse_attendee_count(orchestration_input.message_text)
        if attendee_count is None:
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                orchestration_input.customer,
                orchestration_input.inbound_message,
                "RESP-VISIT-DATA-001",
                {},
            )
            return
        attendees = validate_visit_attendees(
            attendee_count,
            exception_requested=requests_attendee_exception(orchestration_input.message_text),
        )
        if not attendees.accepted:
            if attendees.needs_handoff:
                await create_handoff_and_pause(
                    session,
                    settings,
                    knowledge_sessionmaker,
                    orchestration_input,
                    classification,
                    reason="CAPACITY_REVIEW",
                    priority=classification.priority,
                    detail="Visit attendee exception requested",
                    response_code_override=attendees.response_code,
                )
                return
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                orchestration_input.customer,
                orchestration_input.inbound_message,
                attendees.response_code or "RESP-VISIT-DATA-002",
                {},
            )
            return
        draft["attendee_count"] = attendee_count
        conversation.visit_draft = draft
        set_pending_action(conversation, "COLLECT_VISIT_REASON")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-VISIT-DATA-003",
            {},
        )
        return

    if pending_action == "COLLECT_CUSTOMER_NAME":
        message_text = orchestration_input.message_text
        if (
            current_pending(conversation).kind == "NAME"
            and classification.primary_intent == "GENERAL_INFORMATION"
            and classification.information_category is not None
            and not is_catalog_request_category(classification.information_category)
            and response_code_for_category(classification.information_category)
            != NO_APPROVED_ANSWER
            and not is_affirmative(message_text)
            and normalize_confirmation_text(message_text) not in DENIALS
        ):
            await handle_general_information(
                session,
                settings,
                knowledge_sessionmaker,
                orchestration_input,
                classification,
            )
            return
        corrected = any(
            entity.quality_status == "CORRECTED" for entity in normalized_entities(classification)
        )
        confirmed = (
            await maybe_apply_name_confirmation(
                session,
                conversation,
                orchestration_input.customer,
                message_text,
                orchestration_input.request_id,
            )
            if not corrected
            else False
        )
        name_rejected = False
        # A bare answer cannot become a fresh name through the direct-text fallback.
        if not confirmed and (
            corrected
            or (
                not is_affirmative(message_text)
                and normalize_confirmation_text(message_text) not in DENIALS
            )
        ):
            name_entity = direct_customer_name_entity(classification, message_text)
            name_rejected = (
                checked_entity(
                    session,
                    name_entity,
                    orchestration_input.request_id,
                    conversation,
                )
                is None
            )
            if not name_rejected:
                await apply_full_name(
                    session,
                    conversation,
                    orchestration_input.customer,
                    name_entity,
                    orchestration_input.request_id,
                )
        if name_rejected:
            conversation.pending_fields = list(
                dict.fromkeys(
                    [*(conversation.pending_fields or []), "full_name"],
                )
            )
        elif confirmed or (
            not is_affirmative(message_text)
            and current_pending(conversation).kind != "NAME"
            and any(item.entity == "full_name" for item in normalized_entities(classification))
        ):
            conversation.pending_fields = [
                field for field in (conversation.pending_fields or []) if field != "full_name"
            ]
        if (
            name_rejected
            or current_pending(conversation).kind == "NAME"
            or "full_name" in (conversation.pending_fields or [])
            or not (orchestration_input.customer.full_name or "").strip()
        ):
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                orchestration_input.customer,
                orchestration_input.inbound_message,
                QUESTION_CODE_BY_ACTION["COLLECT_CUSTOMER_NAME"],
                {},
            )
            return
        draft.pop("return_to", None)
        conversation.visit_draft = draft
        await prepare_visit_confirmation(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
        )
        return

    draft["visit_reason"] = orchestration_input.message_text
    conversation.visit_draft = draft
    if not (orchestration_input.customer.full_name or "").strip():
        draft["return_to"] = "VISIT_CONFIRMATION_SUMMARY"
        conversation.visit_draft = draft
        set_pending_action(conversation, "COLLECT_CUSTOMER_NAME")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            QUESTION_CODE_BY_ACTION["COLLECT_CUSTOMER_NAME"],
            {},
        )
        return
    await prepare_visit_confirmation(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
    )


async def prepare_visit_confirmation(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    draft = require_visit_draft(conversation)
    service = visit_scheduling_service(settings, knowledge_sessionmaker)
    result = await service.prepare_confirmation_summary(
        conversation_id=conversation.id,
        customer_name=orchestration_input.customer.full_name,
        preferred_visit_date=date.fromisoformat(draft["visit_date"]),
        preferred_visit_time=time.fromisoformat(draft["visit_time"]),
        attendee_count=int(draft["attendee_count"]),
        visit_reason=draft["visit_reason"],
    )
    if result.needs_handoff:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="SYSTEM_ERROR",
            priority="URGENT",
            detail="Required visit customer name is missing",
            response_code_override=result.response_code,
        )
        return
    await transition_conversation(
        session,
        conversation,
        result.state or ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
        actor=SYSTEM_ACTOR,
        reason="Visit data ready for customer confirmation",
    )
    set_pending_action(conversation, "CONFIRM_APPOINTMENT")
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        result.response_code,
        result.variables,
    )


async def prepare_reschedule_confirmation(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    draft = require_visit_draft(conversation)
    service = visit_scheduling_service(settings, knowledge_sessionmaker)
    result = await service.prepare_reschedule_summary(
        appointment_id=UUID(draft["appointment_id"]),
        new_date=date.fromisoformat(draft["visit_date"]),
        new_time=time.fromisoformat(draft["visit_time"]),
    )
    await transition_conversation(
        session,
        conversation,
        result.state or ConversationState.APPOINTMENT_PENDING_CONFIRMATION,
        actor=SYSTEM_ACTOR,
        reason="Reschedule data ready for customer confirmation",
    )
    set_pending_action(conversation, "CONFIRM_RESCHEDULE")
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        result.response_code,
        result.variables,
    )
    persist_classification_context(conversation, classification)


async def handle_appointment_confirmation(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    draft = require_visit_draft(conversation)
    if classification.primary_intent == "DENY":
        # INTERIM(states.md): pending approved correction/cancellation copy.
        draft.pop("visit_date", None)
        draft.pop("visit_time", None)
        draft.pop("offered_slots", None)
        conversation.visit_draft = draft
        await transition_conversation(
            session,
            conversation,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            actor=SYSTEM_ACTOR,
            reason="Customer denied appointment summary",
        )
        set_pending_action(conversation, "SELECT_VISIT_DATE")
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-VISIT-003",
            {},
        )
        return

    if classification.primary_intent != "CONFIRM" and not is_affirmative(
        orchestration_input.message_text
    ):
        await repeat_visit_confirmation(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
        )
        return

    service = visit_scheduling_service(settings, knowledge_sessionmaker)
    if draft.get("mode") == "RESCHEDULE":
        result = await service.reschedule_appointment(
            appointment_id=UUID(draft["appointment_id"]),
            new_date=date.fromisoformat(draft["visit_date"]),
            new_time=time.fromisoformat(draft["visit_time"]),
            actor="CUSTOMER",
            now=current_bogota_datetime(),
        )
    else:
        result = await service.confirm_appointment(
            customer_id=orchestration_input.customer.id,
            lead_id=conversation.active_lead_id,
            conversation_id=conversation.id,
            visit_date=date.fromisoformat(draft["visit_date"]),
            visit_time=time.fromisoformat(draft["visit_time"]),
            attendee_count=int(draft["attendee_count"]),
            visit_reason=str(draft["visit_reason"]),
            customer_confirmation=True,
            now=current_bogota_datetime(),
            request_id=orchestration_input.request_id,
        )
    await apply_visit_service_result(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
        result,
    )


async def repeat_visit_confirmation(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
) -> None:
    conversation = orchestration_input.conversation
    draft = require_visit_draft(conversation)
    service = visit_scheduling_service(settings, knowledge_sessionmaker)
    if draft.get("mode") == "RESCHEDULE":
        result = await service.prepare_reschedule_summary(
            appointment_id=UUID(draft["appointment_id"]),
            new_date=date.fromisoformat(draft["visit_date"]),
            new_time=time.fromisoformat(draft["visit_time"]),
        )
    else:
        result = await service.prepare_confirmation_summary(
            conversation_id=conversation.id,
            customer_name=orchestration_input.customer.full_name,
            preferred_visit_date=date.fromisoformat(draft["visit_date"]),
            preferred_visit_time=time.fromisoformat(draft["visit_time"]),
            attendee_count=int(draft["attendee_count"]),
            visit_reason=str(draft["visit_reason"]),
        )
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        result.response_code,
        result.variables,
    )


async def apply_visit_service_result(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
    result: VisitServiceResult,
) -> None:
    conversation = orchestration_input.conversation
    draft = require_visit_draft(conversation)
    if result.needs_handoff:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="SYSTEM_ERROR",
            priority="URGENT",
            detail=f"Visit service requires review: {result.response_code}",
            response_code_override=result.response_code,
        )
        return

    target = result.state
    if target == ConversationState.APPOINTMENT_CONFIRMED:
        set_pending_action(conversation, None)
        conversation.visit_draft = None
    if target is not None and conversation.state != target.value:
        await transition_conversation(
            session,
            conversation,
            target,
            actor=SYSTEM_ACTOR,
            reason=f"Visit service result {result.response_code}",
        )
    if result.response_code == "RESP-VISIT-CONFIRM-005":
        set_pending_action(conversation, "SELECT_VISIT_TIME")
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        result.response_code,
        result.variables,
    )
    if result.state != ConversationState.APPOINTMENT_CONFIRMED:
        return

    if draft.get("mode") == "SCHEDULE" and conversation.active_lead_id is not None:
        lead = await session.get(Lead, conversation.active_lead_id)
        if lead is not None:
            lead.lead_status = "VISIT_SCHEDULED"
    audit_domain_change(
        session,
        "VISIT_CONFIRMED" if draft.get("mode") == "SCHEDULE" else "VISIT_RESCHEDULED",
        "appointment",
        None,
        {"appointment_id": str(result.appointment_id)},
        result.response_code,
        orchestration_input.request_id,
    )
    await clear_visit_draft_and_resume_capture(
        session,
        knowledge_sessionmaker,
        orchestration_input,
        completed_draft=draft,
    )


async def handle_visit_cancellation_confirmation(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    draft = require_visit_draft(conversation)
    if draft.get("mode") != "CANCEL":
        raise ValueError("Visit cancellation confirmation without cancellation draft")
    if classification.primary_intent not in {"CONFIRM", "DENY"}:
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-CANCEL-VISIT-001",
            dict(draft.get("response_variables") or {}),
        )
        return

    service = visit_scheduling_service(settings, knowledge_sessionmaker)
    confirmed = classification.primary_intent == "CONFIRM"
    result = await service.cancel_appointment(
        appointment_id=UUID(draft["appointment_id"]),
        customer_confirmation=confirmed,
        reason="Solicitud del cliente",
        now=current_bogota_datetime(),
    )
    if result.needs_handoff:
        await create_handoff_and_pause(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            classification,
            reason="CANCELLATION",
            priority="URGENT",
            detail=f"Visit cancellation requires review: {result.response_code}",
            response_code_override=result.response_code,
        )
        return
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        result.response_code,
        result.variables,
    )
    if confirmed and result.response_code == "RESP-CANCEL-VISIT-002":
        audit_domain_change(
            session,
            "VISIT_CANCELLED",
            "appointment",
            None,
            {"appointment_id": draft["appointment_id"]},
            "Customer confirmed visit cancellation",
            orchestration_input.request_id,
        )
        if conversation.state == ConversationState.APPOINTMENT_CONFIRMED.value:
            await transition_conversation(
                session,
                conversation,
                ConversationState.BOT_ACTIVE,
                actor=SYSTEM_ACTOR,
                reason="Confirmed visit was cancelled",
            )
    set_pending_action(conversation, None)
    await clear_visit_draft_and_resume_capture(
        session,
        knowledge_sessionmaker,
        orchestration_input,
    )


async def cancel_visit_attempt(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    persist_classification_context(orchestration_input.conversation, classification)
    set_pending_action(orchestration_input.conversation, None)
    await clear_visit_draft_and_resume_capture(
        session,
        knowledge_sessionmaker,
        orchestration_input,
        move_to_bot_when_no_resume=True,
    )


async def clear_visit_draft_and_resume_capture(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    *,
    move_to_bot_when_no_resume: bool = False,
    completed_draft: dict[str, Any] | None = None,
) -> None:
    conversation = orchestration_input.conversation
    draft = dict(completed_draft if completed_draft is not None else conversation.visit_draft or {})
    resume = draft.get("resume")
    conversation.visit_draft = None
    if not isinstance(resume, dict):
        if move_to_bot_when_no_resume and conversation.state != ConversationState.BOT_ACTIVE.value:
            await transition_conversation(
                session,
                conversation,
                ConversationState.BOT_ACTIVE,
                actor=SYSTEM_ACTOR,
                reason="Visit attempt cancelled",
            )
        return

    if conversation.state != ConversationState.BOT_ACTIVE.value:
        await transition_conversation(
            session,
            conversation,
            ConversationState.BOT_ACTIVE,
            actor=SYSTEM_ACTOR,
            reason="Visit flow completed before capture resumption",
        )
    await transition_conversation(
        session,
        conversation,
        ConversationState.COLLECTING_EVENT_DATA,
        actor=SYSTEM_ACTOR,
        reason="Resume suspended event data capture",
    )
    lead = await active_lead(session, conversation)
    event = await active_event(session, lead)
    if lead is None or event is None:
        set_pending_action(conversation, None)
        return
    progress = await capture_progress(
        session,
        orchestration_input.customer,
        lead,
        event,
        conversation,
    )
    unresolved = [field for field in (conversation.pending_fields or []) if field in ENTITY_ACTION]
    conversation.pending_fields = list(
        dict.fromkeys(
            [*pending_fields_for(progress), *unresolved],
        )
    )
    next_action = select_next_question(progress)
    if next_action is None and unresolved:
        next_action = ENTITY_ACTION[unresolved[0]]
    if next_action is None:
        await transition_to_quote_request_ready(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            lead,
            event,
            orchestration_input.request_id,
        )
        return
    set_pending_action(conversation, next_action)
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        QUESTION_CODE_BY_ACTION.get(next_action, "RESP-FALLBACK-004"),
        {},
    )


async def move_to_appointment_date(
    session: AsyncSession,
    conversation: Conversation,
) -> None:
    state = ConversationState(conversation.state)
    if state == ConversationState.NEW:
        await transition_conversation(
            session,
            conversation,
            ConversationState.BOT_ACTIVE,
            actor=SYSTEM_ACTOR,
            reason="Visit request activates new conversation",
        )
        state = ConversationState.BOT_ACTIVE
    if state != ConversationState.WAITING_FOR_APPOINTMENT_DATE:
        await transition_conversation(
            session,
            conversation,
            ConversationState.WAITING_FOR_APPOINTMENT_DATE,
            actor=SYSTEM_ACTOR,
            reason="Start or restart visit date selection",
        )


def visit_scheduling_service(settings: Settings, sessionmaker: Any) -> VisitSchedulingService:
    return defer_agenda_service(
        VisitSchedulingService(
            sessionmaker=sessionmaker,
            calendar_adapter=get_calendar_adapter(settings),
            freebusy_calendar_ids=freebusy_calendar_ids(settings),
        )
    )


def availability_service(settings: Settings, sessionmaker: Any) -> AvailabilityService:
    return defer_agenda_service(
        AvailabilityService(
            sessionmaker=sessionmaker,
            calendar_adapter=get_calendar_adapter(settings),
            freebusy_calendar_ids=freebusy_calendar_ids(settings),
        )
    )


def freebusy_calendar_ids(settings: Settings) -> list[str]:
    calendar_ids = [
        value.strip() for value in settings.google_freebusy_calendar_ids.split(",") if value.strip()
    ]
    if settings.google_calendar_id.strip() and settings.google_calendar_id not in calendar_ids:
        calendar_ids.append(settings.google_calendar_id)
    return calendar_ids


def current_bogota_datetime() -> datetime:
    return datetime.now(ZoneInfo("America/Bogota"))


def capture_resume_marker(conversation: Conversation) -> dict[str, str] | None:
    if conversation.state != ConversationState.COLLECTING_EVENT_DATA.value:
        return None
    return {
        "state": ConversationState.COLLECTING_EVENT_DATA.value,
        "pending_action": conversation.pending_action or "",
        "last_question_code": conversation.last_question_code or "",
    }


def require_visit_draft(conversation: Conversation) -> dict[str, Any]:
    if not isinstance(conversation.visit_draft, dict):
        raise ValueError("Appointment flow state requires visit_draft")
    return dict(conversation.visit_draft)


def format_appointment_options(slots: list[time]) -> str:
    labels = [slot.strftime("%H:%M") for slot in slots]
    if len(labels) < 2:
        return labels[0] if labels else ""
    return ", ".join(labels[:-1]) + f" y {labels[-1]}"


def parse_attendee_count(message_text: str) -> int | None:
    match = re.search(r"\b(\d+)\b", message_text)
    return int(match.group(1)) if match is not None else None


def requests_attendee_exception(message_text: str) -> bool:
    normalized = message_text.casefold()
    return any(token in normalized for token in ("excepción", "excepcion", "más", "mas"))


def direct_customer_name_entity(
    classification: IntentClassification,
    message_text: str,
) -> ExtractedEntity:
    extracted_name = next(
        (entity for entity in normalized_entities(classification) if entity.entity == "full_name"),
        None,
    )
    if extracted_name is not None:
        return extracted_name
    raw_value = message_text
    normalized_value = (
        extracted_name.normalized_value if extracted_name is not None else message_text
    )
    return ExtractedEntity(
        entity="full_name",
        raw_value=raw_value,
        normalized_value=normalized_value,
        quality_status="PROVIDED",
        confidence=1.0,
        needs_confirmation=False,
        validation_errors=[],
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
    *,
    understanding_failure_already_counted: bool = False,
) -> None:
    conversation = orchestration_input.conversation
    previous_state = ConversationState(conversation.state)
    previous_pending_action = conversation.pending_action
    preserve_name_context = (
        previous_state == ConversationState.WAITING_FOR_APPOINTMENT_SELECTION
        and previous_pending_action == "COLLECT_CUSTOMER_NAME"
        and current_pending(conversation).kind == "NAME"
    )
    if (
        not preserve_name_context
        and not is_catalog_request_category(classification.information_category)
        and ConversationState.ANSWERING_INFORMATION in ALLOWED_TRANSITIONS[previous_state]
    ):
        set_pending_action(conversation, "ANSWER_INFORMATION")
        await transition_conversation(
            session,
            conversation,
            ConversationState.ANSWERING_INFORMATION,
            actor=SYSTEM_ACTOR,
            reason="General information detected",
        )

    category = classification.information_category
    event_type_entities = [
        entity
        for entity in normalized_entities(classification)
        if entity.entity == "event_type" and entity.quality_status in {"PROVIDED", "CORRECTED"}
    ]
    fixed_price_entities = [
        entity
        for entity in event_type_entities
        if not entity.needs_confirmation
        and normalize_event_type(entity.normalized_value or entity.raw_value)
        in FIXED_PRICE_EVENT_TYPES
    ]
    fixed_price_entity = next(
        (
            entity
            for entity in fixed_price_entities
            if normalize_event_type(entity.normalized_value or entity.raw_value) == "PROPOSAL"
        ),
        fixed_price_entities[0] if fixed_price_entities else None,
    )
    mentioned_event_type = resolve_fixed_price_information_type(orchestration_input.message_text)
    if mentioned_event_type is not None and (
        not event_type_entities
        or all(
            not entity.needs_confirmation
            and normalize_event_type(entity.normalized_value or entity.raw_value)
            == "ROMANTIC_DINNER"
            for entity in event_type_entities
        )
    ):
        fixed_price_entity = ExtractedEntity(
            entity="event_type",
            raw_value=orchestration_input.message_text,
            normalized_value=mentioned_event_type,
            quality_status="PROVIDED",
            confidence=1.0,
        )
    if category is None and fixed_price_entity is None:
        if not understanding_failure_already_counted:
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

    response_code = response_code_for_category(category) if category else NO_APPROVED_ANSWER
    if is_catalog_request_category(category):
        lead = await active_lead(session, conversation)
        event = await active_event(session, lead)
        match = resolve_catalog_event_type_match(orchestration_input.message_text)
        if match is not None:
            audit_orchestrator_event(
                session,
                "CATALOG_EVENT_TYPE_RESOLVED",
                conversation,
                reason="Catalog request event type resolved from text",
                request_id=orchestration_input.request_id,
                extra={
                    "event_type": match.event_type,
                    "matched_label": match.matched_label,
                    "decision_source": "DETERMINISTIC",
                    "source": "EXPLICIT_CATALOG_MENTION",
                },
            )
        classified_event_type = classified_catalog_event_type(classification)
        catalog_event_type = (
            match.event_type
            if match is not None
            else classified_event_type
            if classified_event_type is not None
            else event.event_type
            if event is not None
            else None
        )
        fixed_price_entity = None
        if catalog_event_type in FIXED_PRICE_EVENT_TYPES:
            if match is not None or classified_event_type is None:
                fixed_price_entity = ExtractedEntity(
                    entity="event_type",
                    raw_value=match.matched_label if match is not None else catalog_event_type,
                    normalized_value=catalog_event_type,
                    quality_status="PROVIDED",
                    confidence=1.0,
                )
            else:
                fixed_price_entity = next(
                    (
                        entity
                        for entity in fixed_price_entities
                        if normalize_event_type(entity.normalized_value or entity.raw_value)
                        == catalog_event_type
                    ),
                    None,
                )
        if fixed_price_entity is None:
            result = await handle_explicit_catalog_request(
                session,
                knowledge_sessionmaker,
                conversation,
                orchestration_input.customer,
                orchestration_input.inbound_message,
                lead.lead_id if lead is not None else None,
                event.event_type if event is not None else None,
                match.event_type if match is not None else classified_event_type,
                orchestration_input.request_id,
            )
            persist_classification_context(conversation, classification)
            conversation.failed_understanding_count = 0
            conversation.pending_confirmation = None
            if result.outcome == CatalogRequestOutcome.ASK_EVENT_TYPE:
                set_pending_action(conversation, CATALOG_CAPTURE_ACTION)
                audit_orchestrator_event(
                    session,
                    "CATALOG_CAPTURE_STARTED",
                    conversation,
                    reason="Catalog request requires event type",
                    request_id=orchestration_input.request_id,
                    extra={"previous_pending_action": previous_pending_action},
                )
            elif not catalog_result_requires_human(result):
                set_pending_action(conversation, previous_pending_action)

            target_state = previous_state
            if (
                not catalog_result_requires_human(result)
                and conversation.state != target_state.value
            ):
                await transition_conversation(
                    session,
                    conversation,
                    target_state,
                    actor=SYSTEM_ACTOR,
                    reason="Catalog information handled",
                )
            return
    if fixed_price_entity is not None:
        match = resolve_fixed_price_information_match(orchestration_input.message_text)
        if (
            not is_catalog_request_category(category)
            and match is not None
            and mentioned_event_type is not None
            and normalize_event_type(
                fixed_price_entity.normalized_value or fixed_price_entity.raw_value
            )
            == match.event_type
        ):
            audit_orchestrator_event(
                session,
                "CATALOG_EVENT_TYPE_RESOLVED",
                conversation,
                reason="Fixed-price information event type resolved from text",
                request_id=orchestration_input.request_id,
                extra={
                    "event_type": match.event_type,
                    "matched_label": match.matched_label,
                    "decision_source": "DETERMINISTIC",
                    "source": "FIXED_PRICE_MENTION",
                },
            )
        lead, event = await get_or_create_capture_models(
            session,
            conversation,
            orchestration_input.customer,
            request_id=orchestration_input.request_id,
        )
        apply_event_type(session, event, fixed_price_entity, orchestration_input.request_id)
        if not settings.self_service_booking_enabled:
            await enqueue_fixed_price_catalogs(
                session,
                knowledge_sessionmaker,
                orchestration_input,
                lead,
                event,
            )
        response_code = (
            "RESP-EVENTS-PROPOSAL-001"
            if event.event_type == "PROPOSAL"
            else "RESP-EVENTS-ROMANTIC-001"
        )
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

    try:
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
            strict=fixed_price_entity is not None and settings.self_service_booking_enabled,
        )
    except KnowledgeRenderError:
        from app.orchestrator.booking_flow import handoff

        await handoff(
            session,
            settings,
            knowledge_sessionmaker,
            orchestration_input,
            "Texto de experiencia de precio fijo no aprobado o incompleto",
            reason="TEMPLATE_UNAVAILABLE",
        )
        return
    if fixed_price_entity is not None and settings.self_service_booking_enabled:
        await enqueue_fixed_price_catalogs(
            session,
            knowledge_sessionmaker,
            orchestration_input,
            lead,
            event,
            ordered=True,
        )
        if previous_pending_action not in BOOKING_ACTIONS:
            candidate = resolve_visit_date_text(
                orchestration_input.message_text,
                today=current_bogota_datetime().date(),
                require_absolute_confirmation=True,
            )
            if candidate.resolved_date is not None:
                conversation.booking_draft = {
                    "date": candidate.resolved_date.isoformat(),
                    "date_confirmation": candidate.needs_confirmation,
                }
        if previous_pending_action in GENERIC_CAPTURE_ACTIONS:
            previous_pending_action = None
            previous_state = ConversationState.BOT_ACTIVE
            conversation.pending_fields = []
            conversation.pending_confirmation = None
    persist_classification_context(conversation, classification)
    conversation.failed_understanding_count = 0
    # A validated proposal survives an approved FAQ interruption and its restored action.

    target_state = (
        previous_state
        if preserve_name_context
        or (
            previous_state != ConversationState.ANSWERING_INFORMATION
            and previous_state in ALLOWED_TRANSITIONS[ConversationState.ANSWERING_INFORMATION]
        )
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


async def enqueue_fixed_price_catalogs(
    session: AsyncSession,
    sm: Any,
    turn: OrchestrationInput,
    lead: Lead,
    event: Event,
    *,
    ordered: bool = False,
) -> None:
    after_outbox_id = None
    if ordered:
        await session.flush()
        after_outbox_id = await session.scalar(
            select(Outbox.id)
            .where(
                Outbox.message_id == turn.inbound_message.id,
                Outbox.message_kind == "TEXT",
                Outbox.conversation_id == turn.conversation.id,
            )
            .order_by(Outbox.id.desc())
            .limit(1)
        )
        if after_outbox_id is None:
            raise ValueError("Fixed-price catalog requires its approved text outbox")
    try:
        sent_count = await enqueue_proactive_catalogs_for_event_type(
            session,
            sm,
            turn.conversation,
            turn.customer,
            turn.inbound_message,
            lead.lead_id,
            event.event_type,
            turn.request_id,
            after_outbox_id=after_outbox_id,
        )
    except CatalogCaptionTooLong:
        sent_count = 0
    actions = ["FIXED_PRICE_CATALOG_SENT_FROM_GENERAL_INFO"]
    if event.event_type == "ROMANTIC_DINNER":
        actions.append("ROMANTIC_CATALOG_SENT_FROM_GENERAL_INFO")
    for action in actions:
        audit_orchestrator_event(
            session,
            action,
            turn.conversation,
            reason="Fixed-price event information triggers proactive catalog selection",
            request_id=turn.request_id,
            extra={
                "event_type": event.event_type,
                "lead_id": str(lead.lead_id),
                "sent_count": sent_count,
            },
        )


async def handle_unknown(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
    *,
    understanding_failure_already_counted: bool = False,
) -> None:
    conversation = orchestration_input.conversation
    if not understanding_failure_already_counted:
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

    entities = contextual_requested_service_entities(
        conversation,
        orchestration_input.message_text,
        normalized_entities(classification),
    )
    original_entities = entities
    batch = validate_entities(
        classification.model_copy(update={"extracted_entities": entities}),
        entity_today(),
    )
    for item in batch.rejected:
        audit_entity_rejection(session, item, orchestration_input.request_id, conversation)
    entities = [item.canonical() for item in batch.accepted]
    held_fields = list(conversation.pending_fields or [])
    handled_name_confirmation = (
        await maybe_apply_name_confirmation(
            session,
            conversation,
            customer,
            orchestration_input.message_text,
            orchestration_input.request_id,
        )
        if not any(entity.quality_status == "CORRECTED" for entity in original_entities)
        and not any(item.entity == "full_name" for item in batch.rejected)
        else False
    )
    captured_requested_services = any(
        entity.entity == "requested_services" and entity.quality_status != "INVALID"
        for entity in entities
    )
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
        if not (
            settings.self_service_booking_enabled and event.event_type in FIXED_PRICE_EVENT_TYPES
        ):
            await maybe_enqueue_proactive_catalogs(
                session,
                knowledge_sessionmaker,
                conversation,
                customer,
                inbound_message,
                lead,
                event,
                entities,
                orchestration_input.request_id,
            )
    fixed_price_event = event.event_type in FIXED_PRICE_EVENT_TYPES
    if fixed_price_event and settings.self_service_booking_enabled:
        conversation.pending_fields = []
        conversation.pending_action = None
        conversation.pending_confirmation = None
        conversation.failed_understanding_count = 0
        persist_classification_context(conversation, classification)
        await transition_conversation(
            session,
            conversation,
            "BOT_ACTIVE",
            actor=SYSTEM_ACTOR,
            reason="Precio fijo: se omite captura genérica bajo autoservicio",
        )
        try:
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                customer,
                inbound_message,
                "RESP-EVENTS-PROPOSAL-001"
                if event.event_type == "PROPOSAL"
                else "RESP-EVENTS-ROMANTIC-001",
                {},
                strict=True,
            )
        except KnowledgeRenderError:
            from app.orchestrator.booking_flow import handoff

            await handoff(
                session,
                settings,
                knowledge_sessionmaker,
                orchestration_input,
                "Texto de experiencia de precio fijo no aprobado o incompleto",
                reason="TEMPLATE_UNAVAILABLE",
            )
            return
        await enqueue_fixed_price_catalogs(
            session,
            knowledge_sessionmaker,
            orchestration_input,
            lead,
            event,
            ordered=True,
        )
        return
    declined_by_evasion = (
        not fixed_price_event
        and not batch.rejected
        and should_mark_budget_declined_by_evasion(lead, entities)
    )
    if declined_by_evasion:
        apply_budget_declined(session, lead, orchestration_input.request_id)

    progress = await capture_progress(session, customer, lead, event, conversation)
    unresolved = [
        field
        for field in held_fields
        if field in ENTITY_ACTION
        and field
        not in {
            canonical_field(item.entity)
            for item in entities
            if item.entity != "budget_declined" or item.normalized_value is True
        }
    ]
    if handled_name_confirmation:
        unresolved = [field for field in unresolved if field != "full_name"]
    if declined_by_evasion or fixed_price_event:
        unresolved = [field for field in unresolved if field != "estimated_budget"]
    rejected_fields = [
        canonical_field(item.entity)
        for item in batch.rejected
        if item.code != "UNSUPPORTED_SERVICE_ITEM" and item.entity != "UNKNOWN"
    ]
    if fixed_price_event:
        rejected_fields = [field for field in rejected_fields if field != "estimated_budget"]
    conversation.pending_fields = list(
        dict.fromkeys([*pending_fields_for(progress), *unresolved, *rejected_fields])
    )
    next_action = next(
        (
            ENTITY_ACTION[field]
            for field in [*rejected_fields, *unresolved]
            if field in ENTITY_ACTION
        ),
        select_next_question(progress),
    )
    persist_classification_context(conversation, classification)
    conversation.failed_understanding_count = 0
    if captured_requested_services:
        conversation.services_failed_understanding_count = 0

    if next_action is None and any(
        item.code != "UNSUPPORTED_SERVICE_ITEM" for item in batch.rejected
    ):
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
        return

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
            QUESTION_CODE_BY_ACTION.get(next_action, "RESP-FALLBACK-004"),
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

    if (
        classification.primary_intent == "MODIFY_EVENT_DATA"
        or validate_entities(
            classification,
            entity_today(),
        ).rejected
    ):
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

    if (
        conversation.pending_action != "CONFIRM_QUOTE_REQUEST"
        or not conversation.last_question_code
    ):
        if conversation.pending_action == "CONFIRM_QUOTE_REQUEST":
            set_pending_action(conversation, None)
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            orchestration_input.inbound_message,
            "RESP-FALLBACK-004",
            {},
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
    notice_case, _ = await create_handoff(
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
        notice_case=notice_case,
    )
    set_pending_action(conversation, "WAIT_FOR_HUMAN")


async def handle_failed_services_resolution(
    session: AsyncSession,
    settings: Settings,
    knowledge_sessionmaker: Any,
    orchestration_input: OrchestrationInput,
    classification: IntentClassification,
) -> None:
    conversation = orchestration_input.conversation
    if conversation.pending_action != "COLLECT_SERVICES":
        return

    conversation.services_failed_understanding_count = (
        conversation.services_failed_understanding_count or 0
    ) + 1
    persist_classification_context(conversation, classification)
    if conversation.services_failed_understanding_count == 1:
        await enqueue_template(
            session,
            knowledge_sessionmaker,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            "RESP-SERVICES-RETRY-001",
            {},
        )
        return

    _lead, event = await get_or_create_capture_models(
        session,
        conversation,
        orchestration_input.customer,
        request_id=orchestration_input.request_id,
    )
    apply_requested_services(
        session,
        event,
        ExtractedEntity(
            entity="requested_services",
            raw_value="OTHER",
            normalized_value=["OTHER"],
            quality_status="PROVIDED",
            confidence=1.0,
            needs_confirmation=False,
            validation_errors=[],
        ),
        orchestration_input.request_id,
    )
    conversation.pending_fields = [
        field for field in conversation.pending_fields if field != "requested_services"
    ]
    conversation.services_failed_understanding_count = 0
    await create_handoff_and_pause(
        session,
        settings,
        knowledge_sessionmaker,
        orchestration_input,
        classification,
        reason="OTHER",
        priority="NORMAL",
        detail="No fue posible clasificar los servicios después de una repregunta.",
    )


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


ENTITY_ACTION = {
    "event_type": "COLLECT_EVENT_TYPE",
    "guest_count": "COLLECT_GUEST_COUNT",
    "event_date": "COLLECT_EVENT_DATE",
    "full_name": "COLLECT_CUSTOMER_NAME",
    "estimated_budget": "COLLECT_BUDGET",
    "requested_services": "COLLECT_SERVICES",
    "special_requests": "CLASSIFY_MESSAGE",
}


def canonical_field(name: str) -> str:
    return {"guest_count_range": "guest_count", "budget_declined": "estimated_budget"}.get(
        name,
        name,
    )


def entity_today() -> date:
    return datetime.now(ZoneInfo("America/Bogota")).date()


def audit_entity_rejection(
    session: AsyncSession,
    item: Rejection,
    request_id: str | None,
    conversation: Conversation | None = None,
) -> None:
    action = "PENDING_CONFIRMATION_INVALID_NAME" if item.entity == "full_name" else "ENTITY_INVALID"
    audit_domain_change(
        session,
        action,
        "conversation",
        None,
        {"entity": item.entity, "code": item.code, "value_type": item.value_type},
        "Entity rejected before domain mutation",
        request_id,
    )
    if conversation is not None and item.entity == "full_name" and item.correction:
        pending = conversation.pending_confirmation
        if isinstance(pending, dict) and pending.get("type") == "FULL_NAME_CONFIRMATION":
            discard_pending(
                session,
                conversation,
                PendingProposal("NAME"),
                request_id,
                "INVALID_NAME_CORRECTION",
            )


def checked_entity(
    session: AsyncSession,
    entity: ExtractedEntity,
    request_id: str | None,
    conversation: Conversation | None = None,
) -> Accepted | None:
    try:
        accepted = validate_entity(entity, entity_today())
    except InvalidEntity as error:
        if str(error) == "UNSUPPORTED_EVENT_TYPE":
            audit_discarded_event_type(session, entity, request_id)
        else:
            audit_entity_rejection(session, rejection(entity, str(error)), request_id, conversation)
        return None
    for item in accepted.warnings:
        audit_entity_rejection(session, item, request_id, conversation)
    return accepted


async def apply_extracted_entities(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    lead: Lead,
    event: Event,
    entities: list[ExtractedEntity],
    request_id: str | None,
) -> None:
    for proposed in entities:
        accepted = checked_entity(session, proposed, request_id, conversation)
        if accepted is None:
            continue
        entity = accepted.canonical()
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
        elif entity.entity == "budget_declined" and entity.normalized_value is True:
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
    accepted = checked_entity(session, entity, request_id, conversation)
    if accepted is None:
        return
    name = accepted.value
    if entity.needs_confirmation or entity.quality_status in {"PENDING_CONFIRMATION", "INFERRED"}:
        conversation.pending_confirmation = {
            "type": "FULL_NAME_CONFIRMATION",
            "version": 1,
            "full_name": name,
            "context": proposal_context(conversation.state, conversation.active_lead_id),
        }
        return
    pending = conversation.pending_confirmation
    if isinstance(pending, dict) and pending.get("type") == "FULL_NAME_CONFIRMATION":
        discard_pending(
            session,
            conversation,
            PendingProposal("NAME"),
            request_id,
            "NAME_REPLACED",
        )
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
    pending = current_pending(conversation)
    if pending.kind != "NAME" or conversation.pending_action != "COLLECT_CUSTOMER_NAME":
        return False
    if not is_affirmative(message_text):
        return False
    name = pending.full_name
    assert name is not None
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
    accepted = checked_entity(session, entity, request_id)
    if accepted is None:
        return
    event_type = accepted.value
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


async def maybe_enqueue_proactive_catalogs(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    lead: Lead,
    event: Event,
    entities: list[ExtractedEntity],
    request_id: str | None,
) -> None:
    confirmed_event_type = any(
        entity.entity == "event_type"
        and entity.quality_status in {"PROVIDED", "CORRECTED"}
        and not entity.needs_confirmation
        and normalize_event_type(entity.normalized_value or entity.raw_value) is not None
        for entity in entities
    )
    if not confirmed_event_type:
        return
    try:
        await enqueue_proactive_catalogs_for_event_type(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            lead.lead_id,
            event.event_type,
            request_id,
        )
    except CatalogCaptionTooLong:
        logger.warning(
            "catalog_caption_too_long",
            conversation_id=conversation.id,
            lead_id=str(lead.lead_id),
            event_type=event.event_type,
        )


def apply_guest_count(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    accepted = checked_entity(session, entity, request_id)
    if accepted is None:
        return
    count = accepted.value
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
    accepted = checked_entity(session, entity, request_id)
    if accepted is None:
        return
    low, high = accepted.value
    old = guest_count_snapshot(event)
    event.guest_count = None
    event.guest_count_min = low
    event.guest_count_max = high
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
    accepted = checked_entity(session, entity, request_id)
    if accepted is None:
        return
    triplet = accepted.value
    old = date_snapshot(event)
    event.event_date = triplet.event_date
    event.event_month = triplet.event_month
    event.event_date_type = triplet.event_date_type
    event.event_date_raw = triplet.event_date_raw
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
    accepted = checked_entity(session, entity, request_id)
    if accepted is None:
        return
    amount = accepted.value
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
    accepted = checked_entity(session, entity, request_id)
    if accepted is None:
        return
    for position, service_code in enumerate(accepted.value):
        session.add(
            EventServiceRequest(
                event_id=event.event_id,
                service_name=service_code,
                status="REQUESTED",
                position=position,
            )
        )
        audit_domain_change(
            session,
            "SERVICE_REQUESTED",
            "event_service_request",
            None,
            {
                "event_id": str(event.event_id),
                "service_name": service_code,
                "position": position,
            },
            "Customer requested event service",
            request_id,
        )


def apply_special_requests(
    session: AsyncSession,
    event: Event,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    accepted = checked_entity(session, entity, request_id)
    if accepted is None:
        return
    old = {"special_requests": event.special_requests}
    event.special_requests = accepted.value
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
        full_name_needs_confirmation=current_pending(conversation).kind == "NAME",
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
        await quote_summary_variables(session, event),
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
    # Decode only here: correction/context resolution must still see original quality.
    preferred = classification
    if classification.extracted_entities:
        preferred = classification.model_copy(update={"entities": {}})
    return decode_entities(preferred)[0]


def normalize_event_type_entities(
    session: AsyncSession,
    entities: list[ExtractedEntity],
    request_id: str | None,
) -> list[ExtractedEntity]:
    normalized_entities_list: list[ExtractedEntity] = []
    for entity in entities:
        if entity.entity != "event_type":
            normalized_entities_list.append(entity)
            continue
        value = entity.normalized_value
        if value is None:
            value = entity.raw_value
        if not isinstance(value, str):
            normalized_entities_list.append(entity)
            continue
        if any(
            "\x00" in text or any(0xD800 <= ord(char) <= 0xDFFF for char in text)
            for text in (value, entity.raw_value)
        ):
            normalized_entities_list.append(entity)
            continue
        event_type = normalize_event_type(value)
        if event_type is None:
            audit_discarded_event_type(session, entity, request_id)
            continue
        normalized_entities_list.append(entity.model_copy(update={"normalized_value": event_type}))
    return normalized_entities_list


def normalize_classification_event_type_entities(
    session: AsyncSession,
    classification: IntentClassification,
    request_id: str | None,
) -> IntentClassification:
    entities = normalize_event_type_entities(
        session,
        normalized_entities(classification),
        request_id,
    )
    legacy_entities = dict(classification.entities)
    # Never overwrite a conflicting legacy proposal with the typed representation.
    legacy_value = legacy_entities.get("event_type")
    if isinstance(legacy_value, str):
        legacy_type = normalize_event_type(legacy_value)
        if legacy_type is None:
            legacy_entities.pop("event_type")
        else:
            legacy_entities["event_type"] = legacy_type
    return classification.model_copy(
        update={
            "entities": legacy_entities,
            "extracted_entities": entities,
        }
    )


def with_directed_event_type(
    classification: IntentClassification,
    directed_event_type: str | None,
) -> IntentClassification:
    if directed_event_type is None:
        return classification
    if any(
        entity.entity == "event_type"
        and normalize_event_type(entity.normalized_value or entity.raw_value) is not None
        for entity in normalized_entities(classification)
    ):
        return classification
    entity = ExtractedEntity(
        entity="event_type",
        raw_value=directed_event_type,
        normalized_value=directed_event_type,
        quality_status="PROVIDED",
        confidence=1.0,
        needs_confirmation=False,
        validation_errors=[],
    )
    return classification.model_copy(
        update={"extracted_entities": [*classification.extracted_entities, entity]}
    )


def audit_discarded_event_type(
    session: AsyncSession,
    entity: ExtractedEntity,
    request_id: str | None,
) -> None:
    audit_domain_change(
        session,
        "EVENT_TYPE_ENTITY_DISCARDED",
        "event_type",
        None,
        {
            "raw_value": entity.raw_value,
            "normalized_value": entity.normalized_value,
        },
        "Unknown event_type entity discarded before domain validation",
        request_id,
    )


def contextual_requested_service_entities(
    conversation: Conversation,
    message_text: str,
    entities: list[ExtractedEntity],
) -> list[ExtractedEntity]:
    if conversation.pending_action != "COLLECT_SERVICES":
        return entities
    if any(entity.entity == "requested_services" for entity in entities):
        return entities
    service_codes = match_requested_services(message_text)
    if service_codes is None:
        return entities
    return [
        *entities,
        ExtractedEntity(
            entity="requested_services",
            raw_value=message_text,
            normalized_value=service_codes,
            quality_status="PROVIDED",
            confidence=1.0,
            needs_confirmation=False,
            validation_errors=[],
        ),
    ]


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
    return validate_entity(entity, entity_today()).value


def raw_value_has_explicit_year(raw_value: str) -> bool:
    import re

    return re.search(r"\b20\d{2}\b", raw_value) is not None


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


async def quote_summary_variables(session: AsyncSession, event: Event) -> dict[str, Any]:
    if date_pending(event):
        return {
            "event_type": format_event_type(event.event_type),
            "guest_count": guest_count_text(event),
        }
    if event.event_month is not None and event.event_date is None:
        return {"event_month": format_month_natural(event.event_month)}
    return {
        "event_type": format_event_type(event.event_type),
        "guest_count": guest_count_text(event),
        "event_date": format_date_natural(event.event_date)
        if event.event_date
        else format_month_natural(event.event_month),
        "requested_services_summary": await requested_services_summary(session, event),
    }


def guest_count_text(event: Event) -> str:
    if event.guest_count is not None:
        return str(event.guest_count)
    if event.guest_count_min is not None and event.guest_count_max is not None:
        return f"entre {event.guest_count_min} y {event.guest_count_max}"
    return "por definir"


async def requested_services_summary(session: AsyncSession, event: Event) -> list[str]:
    services = (
        await session.scalars(
            select(EventServiceRequest.service_name)
            .where(
                EventServiceRequest.event_id == event.event_id,
                EventServiceRequest.status == "REQUESTED",
            )
            .order_by(
                EventServiceRequest.position.asc().nulls_last(),
                EventServiceRequest.created_at,
                EventServiceRequest.id,
            )
        )
    ).all()
    if not services:
        raise ValueError("Missing requested services for quote summary")
    return list(services)


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

    question_code = conversation.last_question_code
    if conversation.pending_action not in {None, "NONE"} and question_code:
        question = await get_latest_response(knowledge_sessionmaker, question_code)
        if (
            question is not None
            and question.status == "APPROVED"
            and question.allowed_variables == []
        ):
            await enqueue_template(
                session,
                knowledge_sessionmaker,
                conversation,
                customer,
                inbound_message,
                question_code,
                {},
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
    conversation.visit_draft = None
    conversation.booking_draft = None
    handoff, response_code = await create_handoff(
        session,
        conversation,
        orchestration_input.customer,
        reason=reason,
        priority=priority,
        request_id=orchestration_input.request_id,
        settings=settings,
        detail=detail,
    )
    if reason == "PAYMENT_REVIEW":
        await create_payment_evidence(
            session,
            conversation,
            orchestration_input.customer,
            orchestration_input.inbound_message,
            handoff,
            request_id=orchestration_input.request_id,
        )
    await enqueue_template(
        session,
        knowledge_sessionmaker,
        conversation,
        orchestration_input.customer,
        orchestration_input.inbound_message,
        response_code_override or response_code,
        {},
        notice_case=handoff,
        request_id=(
            str(orchestration_input.request_id)
            if orchestration_input.request_id is not None
            else None
        ),
    )
    persist_classification_context(conversation, classification)
    set_pending_action(conversation, "WAIT_FOR_HUMAN")
    conversation.services_failed_understanding_count = 0
    conversation.pending_confirmation = None


async def enqueue_template(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    response_code: str,
    variables: dict[str, Any],
    *,
    notice_case: Handoff | None = None,
    payment_decision: PaymentEvidence | None = None,
    payment_ack: tuple[PaymentEvidence, Handoff] | None = None,
    strict: bool = False,
    request_id: str | None = None,
) -> None:
    rendered_code = response_code
    try:
        body = await render_response(knowledge_sessionmaker, response_code, variables)
    except KnowledgeRenderError as error:
        context_request_id = request_id or structlog.contextvars.get_contextvars().get("request_id")
        render_request_id = str(context_request_id) if context_request_id is not None else None
        logger.error(
            "approved_response_render_failed",
            response_code=response_code,
            reason=error.reason.value,
            conversation_id=conversation.id,
            request_id=render_request_id,
        )
        session.add(
            AuditEvent(
                actor="SYSTEM",
                action="TEMPLATE_RENDER_FAILED",
                entity="conversation",
                old_value=None,
                new_value={
                    "response_code": response_code,
                    "reason": error.reason.value,
                    "conversation_id": conversation.id,
                    "request_id": render_request_id,
                },
                reason=error.reason.value,
                request_id=render_request_id,
            )
        )
        if strict:
            raise
        body = await render_response(knowledge_sessionmaker, "RESP-AI-ERROR-001", {})
        rendered_code = "RESP-AI-ERROR-001"

    conversation.last_question_code = response_code
    record_audio_response_code(session, rendered_code)
    context = automatic_context(conversation, "TEMPLATE")
    if payment_ack is not None and rendered_code == "RESP-BOOKING-EVIDENCE-001":
        context = payment_evidence_ack_context(*payment_ack)
    elif notice_case is not None and rendered_code in TRANSFER_RESPONSE_CODES:
        context = await handoff_context(session, conversation, notice_case)
    elif payment_decision is not None and rendered_code in {
        "RESP-PAYMENT-004",
        "RESP-PAYMENT-005",
        "RESP-BOOKING-CONFIRMED-001",
        "RESP-BOOKING-PARTIAL-001",
        "RESP-BOOKING-REJECTED-001",
        "RESP-BOOKING-BALANCE-PAID-001",
        "RESP-BOOKING-BALANCE-PARTIAL-001",
    }:
        context = payment_review_context(payment_decision)
    session.add(
        Outbox(
            conversation_id=conversation.id,
            message_id=inbound_message.id,
            channel=Channel.WHATSAPP,
            recipient_phone_number=customer.phone_number,
            payload={"type": "text", "text": {"body": body}},
            delivery_context=context,
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
    if pending_action == "COLLECT_SERVICES":
        conversation.services_failed_understanding_count = 0


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


def audit_uncertain_entity_rescue(
    session: AsyncSession,
    conversation: Conversation,
    classification: IntentClassification,
    request_id: str | None,
) -> None:
    context_reference = classification.context_reference
    audit_orchestrator_event(
        session,
        "AI_CONFIDENCE_DECISION",
        conversation,
        reason="UNCERTAIN_ENTITY_RESCUE",
        request_id=request_id,
        extra={
            "decision": "UNCERTAIN_ENTITY_RESCUE",
            "original_global_confidence": context_reference.get("original_global_confidence"),
            "rescued_entity_confidence": context_reference.get("rescued_entity_confidence"),
            "last_question_code": context_reference.get("last_question_code"),
            "original_reasoning_code": context_reference.get("original_reasoning_code"),
        },
    )


def audit_confirmation_uplift(
    session: AsyncSession,
    conversation: Conversation,
    classification: IntentClassification,
    request_id: str | None,
) -> None:
    audit_orchestrator_event(
        session,
        "AI_CONFIDENCE_DECISION",
        conversation,
        reason="CONFIRMATION_UPLIFT",
        request_id=request_id,
        extra={
            "decision": "CONFIRMATION_UPLIFT",
            "confirmed_intent": classification.primary_intent,
            "original_global_confidence": classification.confidence,
            "original_reasoning_code": classification.reasoning_code,
            "last_question_code": conversation.last_question_code,
        },
    )


def is_action_allowed_for_slice(
    conversation: Conversation,
    classification: IntentClassification,
) -> bool:
    state = ConversationState(conversation.state)
    if state in APPOINTMENT_FLOW_STATES:
        return True
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
    if classification.primary_intent in VISIT_INTENTS:
        return state in {
            ConversationState.NEW,
            ConversationState.BOT_ACTIVE,
            ConversationState.ANSWERING_INFORMATION,
            ConversationState.COLLECTING_EVENT_DATA,
            ConversationState.APPOINTMENT_CONFIRMED,
            ConversationState.RETURNED_TO_BOT,
        }
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
    if (
        action == "CATALOG_EVENT_TYPE_RESOLVED"
        and (extra or {}).get("decision_source") == "DETERMINISTIC"
    ):
        _decision_source.set("DETERMINISTIC")
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

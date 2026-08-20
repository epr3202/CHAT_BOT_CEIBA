from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.catalog.models import CatalogAsset, CatalogEventTypeMap, CatalogSend
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.conversation.knowledge import KnowledgeRenderError, render_response
from app.conversation.models import Conversation
from app.conversation.presentation import format_event_type
from app.conversation.service import transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.handoff.service import build_deterministic_summary

CATALOG_CAPTION_MAX_LENGTH = 1024
CATALOG_CAPTION_RESPONSE_CODE = "RESP-CATALOG-001"
CATALOG_ASK_EVENT_TYPE_RESPONSE_CODE = "RESP-CATALOG-002"
CATALOG_UNAVAILABLE_RESPONSE_CODE = "RESP-CATALOG-003"
CATALOG_REQUEST_CATEGORIES = {"catalogo", "catálogo", "brochure", "pdf", "catalog_request"}

logger = structlog.get_logger(__name__)


class CatalogCaptionTooLong(ValueError):
    pass


class CatalogRequestOutcome(StrEnum):
    SENT = "SENT"
    ASK_EVENT_TYPE = "ASK_EVENT_TYPE"
    UNAVAILABLE = "UNAVAILABLE"
    HANDOFF = "HANDOFF"


@dataclass(frozen=True)
class CatalogRequestResult:
    outcome: CatalogRequestOutcome
    event_type: str | None = None
    sent_count: int = 0


async def enqueue_proactive_catalogs_for_event_type(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    lead_id: UUID,
    event_type: str | None,
    request_id: str | None,
) -> int:
    if event_type is None:
        return 0
    return await enqueue_catalogs_for_event_type(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        lead_id,
        event_type,
        "PROACTIVE",
        ("PROACTIVE",),
        request_id,
    )


async def handle_explicit_catalog_request(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    lead_id: UUID | None,
    event_type: str | None,
    classified_event_type: str | None,
    request_id: str | None,
) -> CatalogRequestResult:
    candidate = classified_event_type or event_type
    if candidate is None:
        return await enqueue_catalog_event_type_prompt(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            request_id,
        )

    sent = await enqueue_catalogs_for_event_type(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        lead_id,
        candidate,
        "EXPLICIT_REQUEST",
        ("ON_REQUEST", "PROACTIVE"),
        request_id,
    )
    if sent > 0:
        return CatalogRequestResult(CatalogRequestOutcome.SENT, candidate, sent)
    return await enqueue_catalog_unavailable_response(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        request_id,
        event_type=candidate,
    )


async def enqueue_catalog_event_type_prompt(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    request_id: str | None,
) -> CatalogRequestResult:
    enqueued = await enqueue_template_text(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        CATALOG_ASK_EVENT_TYPE_RESPONSE_CODE,
        {},
        request_id,
        fallback_response_codes=(CATALOG_UNAVAILABLE_RESPONSE_CODE,),
        trigger="EXPLICIT_REQUEST",
    )
    if not enqueued:
        return CatalogRequestResult(CatalogRequestOutcome.HANDOFF)
    if conversation.last_question_code == CATALOG_ASK_EVENT_TYPE_RESPONSE_CODE:
        return CatalogRequestResult(CatalogRequestOutcome.ASK_EVENT_TYPE)
    return CatalogRequestResult(CatalogRequestOutcome.UNAVAILABLE)


async def enqueue_catalog_unavailable_response(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    request_id: str | None,
    *,
    event_type: str,
) -> CatalogRequestResult:
    enqueued = await enqueue_template_text(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        CATALOG_UNAVAILABLE_RESPONSE_CODE,
        {},
        request_id,
        trigger="EXPLICIT_REQUEST",
    )
    if enqueued:
        await create_catalog_not_available_handoff(
            session,
            conversation,
            customer,
            event_type,
            request_id,
        )
    return CatalogRequestResult(
        CatalogRequestOutcome.UNAVAILABLE if enqueued else CatalogRequestOutcome.HANDOFF,
        event_type,
    )


async def create_catalog_not_available_handoff(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    event_type: str,
    request_id: str | None,
) -> None:
    existing = await session.scalar(
        select(Handoff)
        .where(
            Handoff.conversation_id == conversation.id,
            Handoff.reason == "CATALOG_NOT_AVAILABLE",
            Handoff.status.in_(("PENDING", "TAKEN")),
        )
        .order_by(Handoff.id.desc())
        .limit(1)
    )
    if existing is None:
        detail = f"Tipo de evento solicitado: {event_type}"
        summary = await build_deterministic_summary(
            session,
            conversation,
            customer,
            "CATALOG_NOT_AVAILABLE",
            detail=detail,
            last_messages_limit=5,
        )
        session.add(
            Handoff(
                conversation_id=conversation.id,
                reason="CATALOG_NOT_AVAILABLE",
                priority="NORMAL",
                summary=summary,
                status="PENDING",
            )
        )
    conversation.pending_action = "WAIT_FOR_HUMAN"
    conversation.bot_enabled = False
    if conversation.state != ConversationState.WAITING_FOR_HUMAN.value:
        await transition_conversation(
            session,
            conversation,
            ConversationState.WAITING_FOR_HUMAN,
            actor="SYSTEM",
            reason="CATALOG_NOT_AVAILABLE",
        )
    audit_catalog_event(
        session,
        "CATALOG_HANDOFF_NOT_AVAILABLE",
        "Requested event type has no active catalog",
        request_id,
        {
            "conversation_id": conversation.id,
            "reason": "CATALOG_NOT_AVAILABLE",
            "event_type": event_type,
        },
    )


async def enqueue_catalogs_for_event_type(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    lead_id: UUID | None,
    event_type: str,
    trigger: str,
    modes: tuple[str, ...],
    request_id: str | None,
) -> int:
    assets = await active_assets_for_event_type(session, event_type, modes=modes)
    if not assets:
        audit_catalog_event(
            session,
            "CATALOG_SEND_OMITTED",
            "No active catalog mapped to event_type",
            request_id,
            {"lead_id": str(lead_id), "event_type": event_type, "trigger": trigger},
        )
        return 0
    sent = 0
    for asset in assets:
        try:
            caption = await render_response(
                knowledge_sessionmaker,
                CATALOG_CAPTION_RESPONSE_CODE,
                {"event_type": format_event_type(event_type)},
            )
        except KnowledgeRenderError as error:
            audit_catalog_event(
                session,
                "CATALOG_SEND_REJECTED",
                f"Catalog caption template is not renderable: {error.reason.value}",
                request_id,
                {"catalog_asset_id": str(asset.catalog_asset_id), "trigger": trigger},
            )
            log_catalog_response_suppressed(
                conversation_id=conversation.id,
                response_code=CATALOG_CAPTION_RESPONSE_CODE,
                reason=error.reason.value,
                request_id=request_id,
                trigger=trigger,
            )
            continue
        if len(caption) > CATALOG_CAPTION_MAX_LENGTH:
            audit_catalog_event(
                session,
                "CATALOG_SEND_REJECTED",
                "Catalog caption exceeds WhatsApp document caption limit",
                request_id,
                {"catalog_asset_id": str(asset.catalog_asset_id), "caption_length": len(caption)},
            )
            log_catalog_response_suppressed(
                conversation_id=conversation.id,
                response_code=CATALOG_CAPTION_RESPONSE_CODE,
                reason="caption_too_long",
                request_id=request_id,
                trigger=trigger,
            )
            raise CatalogCaptionTooLong("Catalog caption exceeds 1024 characters")
        try:
            async with session.begin_nested():
                outbox = Outbox(
                    conversation_id=conversation.id,
                    message_id=inbound_message.id,
                    channel=Channel.WHATSAPP,
                    recipient_phone_number=customer.phone_number,
                    payload={"type": "document", "document": {"caption": caption}},
                    message_kind="DOCUMENT",
                    catalog_asset_id=asset.catalog_asset_id,
                    status="PENDING",
                )
                session.add(outbox)
                await session.flush()
                if lead_id is not None:
                    session.add(
                        CatalogSend(
                            lead_id=lead_id,
                            catalog_asset_id=asset.catalog_asset_id,
                            trigger=trigger,
                            outbound_message_id=outbox.id,
                        )
                    )
                    await session.flush()
        except IntegrityError:
            audit_catalog_event(
                session,
                "CATALOG_SEND_DEDUPED",
                "Proactive catalog already sent for lead and asset",
                request_id,
                {"lead_id": str(lead_id), "catalog_asset_id": str(asset.catalog_asset_id)},
            )
            continue
        sent += 1
        audit_catalog_event(
            session,
            "CATALOG_SEND_ENQUEUED",
            "Catalog document outbox enqueued",
            request_id,
            {
                "catalog_asset_id": str(asset.catalog_asset_id),
                "trigger": trigger,
                "outbox_id": outbox.id,
            },
        )
    return sent


async def active_assets_for_event_type(
    session: AsyncSession, event_type: str, *, modes: tuple[str, ...]
) -> list[CatalogAsset]:
    return list(
        (
            await session.scalars(
                select(CatalogAsset)
                .join(CatalogEventTypeMap)
                .where(
                    CatalogEventTypeMap.event_type == event_type,
                    CatalogEventTypeMap.send_mode.in_(modes),
                    CatalogAsset.active.is_(True),
                )
                .order_by(CatalogAsset.created_at, CatalogAsset.catalog_asset_id)
            )
        ).all()
    )


async def enqueue_template_text(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    response_code: str,
    variables: dict[str, Any],
    request_id: str | None,
    *,
    fallback_response_codes: tuple[str, ...] = (),
    trigger: str | None = None,
) -> bool:
    attempted_codes = tuple(dict.fromkeys((response_code, *fallback_response_codes)))
    for current_response_code in attempted_codes:
        try:
            body = await render_response(knowledge_sessionmaker, current_response_code, variables)
        except KnowledgeRenderError as error:
            audit_catalog_event(
                session,
                "CATALOG_TEXT_RESPONSE_OMITTED",
                f"Template {current_response_code} is missing or not approved",
                request_id,
                {"response_code": current_response_code, "trigger": trigger},
            )
            log_catalog_response_suppressed(
                conversation_id=conversation.id,
                response_code=current_response_code,
                reason=error.reason.value,
                request_id=request_id,
                trigger=trigger,
            )
            continue
        conversation.last_question_code = current_response_code
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
        return True

    await create_template_unavailable_handoff(
        session,
        conversation,
        customer,
        response_code,
        attempted_codes,
        request_id,
        trigger,
    )
    return False


async def create_template_unavailable_handoff(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    response_code: str,
    attempted_codes: tuple[str, ...],
    request_id: str | None,
    trigger: str | None,
) -> None:
    detail = (
        f"TEMPLATE_UNAVAILABLE for {response_code}; "
        f"attempted response codes: {', '.join(attempted_codes)}"
    )
    summary = await build_deterministic_summary(
        session,
        conversation,
        customer,
        "TEMPLATE_UNAVAILABLE",
        detail=detail,
        last_messages_limit=5,
    )
    session.add(
        Handoff(
            conversation_id=conversation.id,
            reason="TEMPLATE_UNAVAILABLE",
            priority="NORMAL",
            summary=summary,
            status="PENDING",
        )
    )
    conversation.pending_action = "WAIT_FOR_HUMAN"
    conversation.bot_enabled = False
    if conversation.state != ConversationState.WAITING_FOR_HUMAN.value:
        await transition_conversation(
            session,
            conversation,
            ConversationState.WAITING_FOR_HUMAN,
            actor="SYSTEM",
            reason="TEMPLATE_UNAVAILABLE",
        )
    audit_catalog_event(
        session,
        "CATALOG_HANDOFF_TEMPLATE_UNAVAILABLE",
        "Catalog response template chain unavailable",
        request_id,
        {
            "conversation_id": conversation.id,
            "reason": "TEMPLATE_UNAVAILABLE",
            "response_code": response_code,
            "attempted_response_codes": list(attempted_codes),
            "trigger": trigger,
        },
    )
    log_catalog_response_suppressed(
        conversation_id=conversation.id,
        response_code=response_code,
        reason="TEMPLATE_UNAVAILABLE",
        request_id=request_id,
        trigger=trigger,
    )


def is_catalog_request_category(category: str | None) -> bool:
    if category is None:
        return False
    return " ".join(category.strip().casefold().split()) in CATALOG_REQUEST_CATEGORIES


def audit_catalog_event(
    session: AsyncSession,
    action: str,
    reason: str,
    request_id: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor="SYSTEM",
            action=action,
            entity="catalog",
            old_value=None,
            new_value=extra or {},
            reason=reason,
            request_id=request_id,
        )
    )


def log_catalog_response_suppressed(
    *,
    conversation_id: int,
    response_code: str,
    reason: str,
    request_id: str | None,
    trigger: str | None,
) -> None:
    logger.info(
        "catalog_response_suppressed",
        conversation_id=conversation_id,
        response_code=response_code,
        reason=reason,
        request_id=request_id,
        trigger=trigger,
    )

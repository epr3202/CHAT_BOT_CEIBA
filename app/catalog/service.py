from __future__ import annotations

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
from app.customer.models import Customer

CATALOG_CAPTION_MAX_LENGTH = 1024
CATALOG_CAPTION_RESPONSE_CODE = "RESP-CATALOG-001"
CATALOG_ASK_EVENT_TYPE_RESPONSE_CODE = "RESP-CATALOG-002"
CATALOG_UNAVAILABLE_RESPONSE_CODE = "RESP-CATALOG-003"
CATALOG_REQUEST_CATEGORIES = {"catalogo", "catálogo", "brochure", "pdf", "catalog_request"}

logger = structlog.get_logger(__name__)


class CatalogCaptionTooLong(ValueError):
    pass


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
    request_id: str | None,
) -> int:
    if lead_id is None:
        await enqueue_template_text(
            session,
            knowledge_sessionmaker,
            conversation,
            customer,
            inbound_message,
            CATALOG_ASK_EVENT_TYPE_RESPONSE_CODE,
            {},
            request_id,
        )
        return 0

    sent = await enqueue_catalogs_for_event_type(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        lead_id,
        event_type or "OTHER",
        "EXPLICIT_REQUEST",
        request_id,
    )
    if sent > 0:
        return sent
    await enqueue_template_text(
        session,
        knowledge_sessionmaker,
        conversation,
        customer,
        inbound_message,
        CATALOG_ASK_EVENT_TYPE_RESPONSE_CODE
        if event_type is None
        else CATALOG_UNAVAILABLE_RESPONSE_CODE,
        {},
        request_id,
    )
    return 0


async def enqueue_catalogs_for_event_type(
    session: AsyncSession,
    knowledge_sessionmaker: Any,
    conversation: Conversation,
    customer: Customer,
    inbound_message: Message,
    lead_id: UUID,
    event_type: str,
    trigger: str,
    request_id: str | None,
) -> int:
    assets = await active_assets_for_event_type(session, event_type, send_mode="PROACTIVE")
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
            continue
        if len(caption) > CATALOG_CAPTION_MAX_LENGTH:
            audit_catalog_event(
                session,
                "CATALOG_SEND_REJECTED",
                "Catalog caption exceeds WhatsApp document caption limit",
                request_id,
                {"catalog_asset_id": str(asset.catalog_asset_id), "caption_length": len(caption)},
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
    session: AsyncSession, event_type: str, send_mode: str = "PROACTIVE"
) -> list[CatalogAsset]:
    return list(
        (
            await session.scalars(
                select(CatalogAsset)
                .join(CatalogEventTypeMap)
                .where(
                    CatalogEventTypeMap.event_type == event_type,
                    CatalogEventTypeMap.send_mode == send_mode,
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
) -> None:
    try:
        body = await render_response(knowledge_sessionmaker, response_code, variables)
    except KnowledgeRenderError:
        audit_catalog_event(
            session,
            "CATALOG_TEXT_RESPONSE_OMITTED",
            f"Template {response_code} is missing or not approved",
            request_id,
            {"response_code": response_code},
        )
        return
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

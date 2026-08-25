from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.auth import (
    DUMMY_PASSWORD_HASH,
    PIN_MIN_LENGTH,
    delete_expired_sessions_for_agent,
    hash_agent_token,
    hash_pin,
    require_admin,
    require_session,
    resolve_session_from_authorization,
    revoke_sessions_for_agent,
    verify_pin,
)
from app.agent.models import Agent, AgentSession
from app.appointment.models import Appointment, BlockedDate, Holiday
from app.audit.models import AuditEvent
from app.catalog.models import CATALOG_SEND_MODES, CatalogAsset, CatalogEventTypeMap
from app.channel.media import detect_pdf_mime_type, sha256_file
from app.channel.models import Message, Outbox
from app.channel.states import Channel
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.service import transition_conversation
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import EVENT_TYPES
from app.handoff.models import Handoff
from app.orchestrator.service import enqueue_template
from app.payment.models import PaymentEvidence

router = APIRouter(prefix="/admin", tags=["admin"])

DIRECT_TAKE_ELIGIBLE_STATES = {
    ConversationState.BOT_ACTIVE.value,
    ConversationState.ANSWERING_INFORMATION.value,
    ConversationState.COLLECTING_EVENT_DATA.value,
    ConversationState.WAITING_FOR_APPOINTMENT_DATE.value,
    ConversationState.WAITING_FOR_APPOINTMENT_SELECTION.value,
    ConversationState.APPOINTMENT_PENDING_CONFIRMATION.value,
    ConversationState.APPOINTMENT_CONFIRMED.value,
    ConversationState.RESOLVED.value,
}


class ReturnHandoffRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=500)


class AgentMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role: Literal["ADMIN", "AGENT"] = "AGENT"


class AgentCredentialsRequest(BaseModel):
    document_id: str = Field(min_length=4, max_length=64)
    pin: str = Field(min_length=PIN_MIN_LENGTH, max_length=256)


class LoginRequest(BaseModel):
    document_id: str = Field(min_length=4, max_length=64)
    pin: str = Field(min_length=1, max_length=256)


class AgentPayload(BaseModel):
    id: int
    name: str
    role: Literal["ADMIN", "AGENT"]
    active: bool
    created_at: datetime


class AgentIdentityPayload(BaseModel):
    id: int
    name: str
    role: Literal["ADMIN", "AGENT"]


class LoginPayload(BaseModel):
    token: str
    agent: AgentIdentityPayload


class AssignmentHistoryPayload(BaseModel):
    actor: str
    action: str
    created_at: datetime


class ConversationMessagePayload(BaseModel):
    id: str
    direction: Literal["INBOUND", "OUTBOUND"]
    body: str
    message_type: str
    status: str | None = None
    created_at: datetime


class ConversationPayload(BaseModel):
    id: int
    conversation_id: int
    customer_name: str | None
    customer_phone: str | None
    state: str
    last_intent: str | None
    pending_action: str | None
    bot_enabled: bool
    handoff_id: int | None
    handoff_status: str | None
    assigned_to: str | None
    assigned_agent: AgentIdentityPayload | None
    handoff_reason: str | None
    handoff_priority: str | None
    handoff_summary: str | None
    last_message_body: str | None
    last_message_preview: str | None
    last_message_direction: str | None
    last_message_at: datetime | None


class CatalogEventTypeMappingRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=64)
    send_mode: str = "ON_REQUEST"


CatalogEventTypeInput = str | CatalogEventTypeMappingRequest


class CatalogEventTypeMappingPayload(BaseModel):
    event_type: str
    send_mode: str


class CatalogCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    file_path: str = Field(min_length=1, max_length=1000)
    event_types: list[CatalogEventTypeInput] = Field(default_factory=list)


class CatalogPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    file_path: str | None = Field(default=None, min_length=1, max_length=1000)
    active: bool | None = None


class CatalogEventTypesRequest(BaseModel):
    event_types: list[CatalogEventTypeInput] = Field(default_factory=list)


class CatalogPayload(BaseModel):
    catalog_asset_id: UUID
    name: str
    file_path: str
    file_hash: str
    mime_type: str
    file_size: int
    media_cached: bool
    media_uploaded_at: datetime | None
    active: bool
    version: int
    event_types: list[str]
    event_type_mappings: list[CatalogEventTypeMappingPayload]
    created_at: datetime
    updated_at: datetime


class CatalogCategoryPayload(BaseModel):
    event_type: str
    covered: bool
    active_catalog_count: int
    catalogs: list[CatalogPayload]


class BlockedDateCreateRequest(BaseModel):
    blocked_date: date
    reason: str = Field(min_length=1, max_length=500)


class BlockedDatePatchRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class BlockedDatePayload(BaseModel):
    blocked_date: date
    reason: str
    actor: str
    created_at: datetime
    updated_at: datetime


class HolidayCreateRequest(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=255)


class HolidayPayload(BaseModel):
    holiday_date: date
    name: str
    source: Literal["SEEDED", "MANUAL"]
    created_at: datetime
    updated_at: datetime


class AppointmentDayPayload(BaseModel):
    appointment_id: UUID
    customer_id: int
    lead_id: UUID | None
    appointment_date: date
    start_time: time
    end_time: time
    timezone: str
    attendee_count: int
    visit_reason: str
    appointment_status: str
    external_calendar_id: str | None
    requires_reconciliation: bool


class PaymentEvidenceReviewRequest(BaseModel):
    note: str = Field(min_length=1, max_length=500)


class PaymentEvidencePayload(BaseModel):
    id: int
    conversation_id: int
    customer_id: int
    customer_name: str | None
    customer_phone: str
    mime_type: str
    download_status: str
    review_status: str
    size_bytes: int | None
    created_at: datetime


class PaymentEvidenceReviewPayload(BaseModel):
    id: int
    review_status: str
    reviewed_by_agent_id: int
    reviewed_at: datetime
    customer_notification: Literal["ENQUEUED", "DEFERRED"]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
HandoffListStatus = Literal["PENDING", "TAKEN", "RETURNED"]


async def authenticated_agent(session: AsyncSession, authorization: str | None) -> Agent:
    return await require_session(session, authorization)


async def authenticated_admin(session: AsyncSession, authorization: str | None) -> Agent:
    agent = await authenticated_agent(session, authorization)
    require_admin(agent)
    return agent


@router.get("/payment-evidence")
async def list_payment_evidence(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[PaymentEvidencePayload]:
    await authenticated_admin(session, authorization)
    rows = await session.execute(
        select(PaymentEvidence, Customer)
        .join(Customer, Customer.id == PaymentEvidence.customer_id)
        .where(PaymentEvidence.review_status == "PENDING_REVIEW")
        .order_by(PaymentEvidence.created_at, PaymentEvidence.id)
    )
    return [
        PaymentEvidencePayload(
            id=evidence.id,
            conversation_id=evidence.conversation_id,
            customer_id=evidence.customer_id,
            customer_name=customer.full_name,
            customer_phone=customer.phone_number,
            mime_type=evidence.mime_type,
            download_status=evidence.download_status,
            review_status=evidence.review_status,
            size_bytes=evidence.size_bytes,
            created_at=evidence.created_at,
        )
        for evidence, customer in rows.all()
    ]


@router.get("/payment-evidence/{evidence_id}/download")
async def download_payment_evidence(
    evidence_id: int,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> FileResponse:
    await authenticated_admin(session, authorization)
    evidence = await session.get(PaymentEvidence, evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment evidence not found",
        )
    if evidence.download_status != "DOWNLOADED" or evidence.storage_path is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment evidence file is not available",
        )
    file_path = Path(evidence.storage_path).resolve()
    expected_suffix = payment_evidence_suffix(evidence.mime_type)
    if (
        expected_suffix is None
        or file_path.stem != str(evidence.id)
        or file_path.suffix.casefold() != expected_suffix
        or not file_path.is_file()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment evidence file is unavailable or invalid",
        )
    return FileResponse(
        file_path,
        media_type=evidence.mime_type,
        filename=file_path.name,
    )


@router.post("/payment-evidence/{evidence_id}/accept")
async def accept_payment_evidence(
    evidence_id: int,
    body: PaymentEvidenceReviewRequest,
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> PaymentEvidenceReviewPayload:
    return await review_payment_evidence(
        evidence_id,
        "ACCEPTED",
        "RESP-PAYMENT-004",
        body.note,
        request,
        session,
        authorization,
    )


@router.post("/payment-evidence/{evidence_id}/reject")
async def reject_payment_evidence(
    evidence_id: int,
    body: PaymentEvidenceReviewRequest,
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> PaymentEvidenceReviewPayload:
    return await review_payment_evidence(
        evidence_id,
        "REJECTED",
        "RESP-PAYMENT-005",
        body.note,
        request,
        session,
        authorization,
    )


async def review_payment_evidence(
    evidence_id: int,
    decision: Literal["ACCEPTED", "REJECTED"],
    response_code: Literal["RESP-PAYMENT-004", "RESP-PAYMENT-005"],
    note: str,
    request: Request,
    session: AsyncSession,
    authorization: str | None,
) -> PaymentEvidenceReviewPayload:
    agent = await authenticated_admin(session, authorization)
    evidence = await session.get(PaymentEvidence, evidence_id, with_for_update=True)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment evidence not found",
        )
    if evidence.review_status != "PENDING_REVIEW":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment evidence has already been reviewed",
        )
    clean_note = note.strip()
    if not clean_note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Review note is required",
        )

    reviewed_at = datetime.now(UTC)
    evidence.review_status = decision
    evidence.reviewed_by_agent_id = agent.id
    evidence.reviewed_at = reviewed_at
    evidence.review_note = clean_note

    approved_template = await session.scalar(
        select(KnowledgeEntry)
        .where(
            KnowledgeEntry.code == response_code,
            KnowledgeEntry.status == "APPROVED",
        )
        .order_by(KnowledgeEntry.version.desc())
        .limit(1)
    )
    customer_notification: Literal["ENQUEUED", "DEFERRED"] = "DEFERRED"
    if approved_template is not None:
        conversation = await session.get(Conversation, evidence.conversation_id)
        customer = await session.get(Customer, evidence.customer_id)
        inbound_message = await session.get(Message, evidence.message_id)
        if conversation is None or customer is None or inbound_message is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payment evidence references are incomplete",
            )
        variables = (
            {"rejection_reason_customer_safe": clean_note}
            if decision == "REJECTED"
            else {}
        )
        await enqueue_template(
            session,
            request.app.state.db_sessionmaker,
            conversation,
            customer,
            inbound_message,
            response_code,
            variables,
        )
        customer_notification = "ENQUEUED"

    session.add(
        AuditEvent(
            actor=agent.name,
            action="PAYMENT_EVIDENCE_REVIEWED",
            entity="payment_evidence",
            old_value={"evidence_id": evidence.id, "review_status": "PENDING_REVIEW"},
            new_value={
                "evidence_id": evidence.id,
                "decision": decision,
                "agent_id": agent.id,
                "customer_notification": customer_notification,
            },
            reason="Payment evidence reviewed by an administrator",
            request_id=None,
        )
    )
    await session.commit()
    return PaymentEvidenceReviewPayload(
        id=evidence.id,
        review_status=decision,
        reviewed_by_agent_id=agent.id,
        reviewed_at=reviewed_at,
        customer_notification=customer_notification,
    )


def payment_evidence_suffix(mime_type: str) -> str | None:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime_type.casefold())


@router.post("/blocked-dates")
async def create_blocked_date(
    body: BlockedDateCreateRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> BlockedDatePayload:
    agent = await authenticated_admin(session, authorization)
    existing = await session.get(BlockedDate, body.blocked_date)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Blocked date already exists",
        )
    blocked_date = BlockedDate(
        blocked_date=body.blocked_date,
        reason=body.reason.strip(),
        actor=agent.name,
    )
    session.add(blocked_date)
    session.add(
        AuditEvent(
            actor=agent.name,
            action="BLOCKED_DATE_CREATED",
            entity="blocked_date",
            old_value=None,
            new_value={"blocked_date": body.blocked_date.isoformat(), "reason": body.reason},
            reason="Admin blocked visit date",
            request_id=None,
        )
    )
    await session.commit()
    await session.refresh(blocked_date)
    return blocked_date_payload(blocked_date)


@router.get("/blocked-dates")
async def list_blocked_dates(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[BlockedDatePayload]:
    await authenticated_admin(session, authorization)
    rows = (
        await session.scalars(select(BlockedDate).order_by(BlockedDate.blocked_date))
    ).all()
    return [blocked_date_payload(row) for row in rows]


@router.patch("/blocked-dates/{blocked_date_value}")
async def patch_blocked_date(
    blocked_date_value: date,
    body: BlockedDatePatchRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> BlockedDatePayload:
    agent = await authenticated_admin(session, authorization)
    blocked_date = await session.get(BlockedDate, blocked_date_value)
    if blocked_date is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blocked date not found")
    old_value = {
        "blocked_date": blocked_date.blocked_date.isoformat(),
        "reason": blocked_date.reason,
    }
    blocked_date.reason = body.reason.strip()
    blocked_date.actor = agent.name
    session.add(
        AuditEvent(
            actor=agent.name,
            action="BLOCKED_DATE_UPDATED",
            entity="blocked_date",
            old_value=old_value,
            new_value={
                "blocked_date": blocked_date.blocked_date.isoformat(),
                "reason": blocked_date.reason,
            },
            reason="Admin updated blocked visit date",
            request_id=None,
        )
    )
    await session.commit()
    await session.refresh(blocked_date)
    return blocked_date_payload(blocked_date)


@router.delete("/blocked-dates/{blocked_date_value}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocked_date(
    blocked_date_value: date,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    agent = await authenticated_admin(session, authorization)
    blocked_date = await session.get(BlockedDate, blocked_date_value)
    if blocked_date is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blocked date not found")
    old_value = {
        "blocked_date": blocked_date.blocked_date.isoformat(),
        "reason": blocked_date.reason,
    }
    await session.delete(blocked_date)
    session.add(
        AuditEvent(
            actor=agent.name,
            action="BLOCKED_DATE_DELETED",
            entity="blocked_date",
            old_value=old_value,
            new_value=None,
            reason="Admin removed blocked visit date",
            request_id=None,
        )
    )
    await session.commit()


@router.post("/holidays")
async def create_manual_holiday(
    body: HolidayCreateRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> HolidayPayload:
    agent = await authenticated_admin(session, authorization)
    existing = await session.get(Holiday, body.holiday_date)
    if existing is not None and existing.source != "MANUAL":
        existing.name = body.name.strip()
        existing.source = "MANUAL"
        holiday = existing
    elif existing is not None:
        existing.name = body.name.strip()
        holiday = existing
    else:
        holiday = Holiday(
            holiday_date=body.holiday_date,
            name=body.name.strip(),
            source="MANUAL",
        )
        session.add(holiday)
    session.add(
        AuditEvent(
            actor=agent.name,
            action="HOLIDAY_MANUAL_UPSERTED",
            entity="holiday",
            old_value=None,
            new_value={"holiday_date": body.holiday_date.isoformat(), "name": body.name},
            reason="Admin registered manual holiday",
            request_id=None,
        )
    )
    await session.commit()
    await session.refresh(holiday)
    return holiday_payload(holiday)


@router.get("/appointments")
async def list_appointments_for_day(
    appointment_date: date,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[AppointmentDayPayload]:
    await authenticated_admin(session, authorization)
    appointments = (
        await session.scalars(
            select(Appointment)
            .where(Appointment.appointment_date == appointment_date)
            .order_by(Appointment.start_time)
        )
    ).all()
    return [appointment_day_payload(appointment) for appointment in appointments]


@router.post("/catalogs")
async def create_catalog(
    body: CatalogCreateRequest,
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> CatalogPayload:
    agent = await authenticated_admin(session, authorization)
    file_path = resolve_catalog_file_path(request, body.file_path)
    file_size = validate_catalog_admin_file(request, file_path)
    event_type_mappings = parse_catalog_event_type_mappings(body.event_types)
    validate_catalog_event_type_mappings(event_type_mappings)
    asset = CatalogAsset(
        name=body.name.strip(),
        file_path=body.file_path.strip(),
        file_hash=sha256_file(file_path),
        mime_type="application/pdf",
        file_size=file_size,
        active=True,
        version=1,
    )
    session.add(asset)
    await session.flush()
    for mapping in event_type_mappings:
        session.add(
            CatalogEventTypeMap(
                catalog_asset_id=asset.catalog_asset_id,
                event_type=mapping.event_type,
                send_mode=mapping.send_mode,
            )
        )
    session.add(
        AuditEvent(
            actor=agent.name,
            action="CATALOG_ASSET_CREATED",
            entity="catalog_asset",
            old_value=None,
            new_value={
                "catalog_asset_id": str(asset.catalog_asset_id),
                "event_types": catalog_event_type_names(event_type_mappings),
                "event_type_mappings": catalog_event_type_mapping_values(event_type_mappings),
            },
            reason="Admin registered catalog asset",
            request_id=None,
        )
    )
    await session.commit()
    await session.refresh(asset)
    return await catalog_payload(session, asset)


@router.get("/catalogs")
async def list_catalogs(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[CatalogPayload]:
    await authenticated_admin(session, authorization)
    assets = (
        await session.scalars(
            select(CatalogAsset).order_by(CatalogAsset.created_at, CatalogAsset.name)
        )
    ).all()
    return [await catalog_payload(session, asset) for asset in assets]


@router.post("/catalogs/upload")
async def upload_catalog(
    request: Request,
    session: DbSession,
    name: Annotated[str, Form(min_length=1, max_length=180)],
    event_type: Annotated[str, Form(min_length=1, max_length=64)],
    file: Annotated[UploadFile, File()],
    send_mode: Annotated[str, Form()] = "ON_REQUEST",
    authorization: Annotated[str | None, Header()] = None,
) -> CatalogPayload:
    agent = await authenticated_admin(session, authorization)
    agent_name = agent.name
    mapping = CatalogEventTypeMappingRequest(event_type=event_type, send_mode=send_mode)
    validate_catalog_event_type_mappings([mapping])
    await session.rollback()

    stored_path, file_hash, file_size, created_new_file = await store_catalog_upload(
        request, file
    )
    try:
        async with session.begin():
            asset = CatalogAsset(
                name=name.strip(),
                file_path=stored_path.name,
                file_hash=file_hash,
                mime_type="application/pdf",
                file_size=file_size,
                active=True,
                version=1,
            )
            session.add(asset)
            await session.flush()
            session.add(
                CatalogEventTypeMap(
                    catalog_asset_id=asset.catalog_asset_id,
                    event_type=event_type,
                    send_mode=send_mode,
                )
            )
            session.add(
                AuditEvent(
                    actor=agent_name,
                    action="CATALOG_ASSET_UPLOADED",
                    entity="catalog_asset",
                    old_value=None,
                    new_value={
                        "catalog_asset_id": str(asset.catalog_asset_id),
                        "event_type": event_type,
                        "send_mode": send_mode,
                        "file_hash": file_hash,
                    },
                    reason="Admin uploaded and mapped catalog asset",
                    request_id=None,
                )
            )
    except Exception:
        if created_new_file:
            stored_path.unlink(missing_ok=True)
        raise
    return await catalog_payload(session, asset)


@router.get("/catalogs/categories")
async def list_catalog_categories(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[CatalogCategoryPayload]:
    await authenticated_admin(session, authorization)
    rows = (
        await session.execute(
            select(CatalogEventTypeMap.event_type, CatalogAsset)
            .join(CatalogAsset)
            .order_by(
                CatalogEventTypeMap.event_type,
                CatalogAsset.created_at,
                CatalogAsset.name,
            )
        )
    ).all()
    assets_by_event_type: dict[str, list[CatalogAsset]] = {
        event_type: [] for event_type in EVENT_TYPES
    }
    for mapped_event_type, asset in rows:
        assets_by_event_type[mapped_event_type].append(asset)

    payload: list[CatalogCategoryPayload] = []
    for event_type in EVENT_TYPES:
        assets = assets_by_event_type[event_type]
        active_count = sum(asset.active for asset in assets)
        payload.append(
            CatalogCategoryPayload(
                event_type=event_type,
                covered=active_count > 0,
                active_catalog_count=active_count,
                catalogs=[await catalog_payload(session, asset) for asset in assets],
            )
        )
    return payload


@router.patch("/catalogs/{catalog_asset_id}")
async def patch_catalog(
    catalog_asset_id: UUID,
    body: CatalogPatchRequest,
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> CatalogPayload:
    agent = await authenticated_admin(session, authorization)
    asset = await session.get(CatalogAsset, catalog_asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog not found")
    old_value = {
        "name": asset.name,
        "file_path": asset.file_path,
        "active": asset.active,
        "version": asset.version,
        "media_id": asset.media_id,
    }
    if body.name is not None:
        asset.name = body.name.strip()
    if body.active is not None:
        asset.active = body.active
    if body.file_path is not None:
        file_path = resolve_catalog_file_path(request, body.file_path)
        asset.file_size = validate_catalog_admin_file(request, file_path)
        asset.file_path = body.file_path.strip()
        asset.file_hash = sha256_file(file_path)
        asset.version += 1
        asset.media_id = None
        asset.media_uploaded_at = None
    session.add(
        AuditEvent(
            actor=agent.name,
            action="CATALOG_ASSET_UPDATED",
            entity="catalog_asset",
            old_value=old_value,
            new_value={
                "catalog_asset_id": str(asset.catalog_asset_id),
                "name": asset.name,
                "file_path": asset.file_path,
                "active": asset.active,
                "version": asset.version,
            },
            reason="Admin updated catalog asset",
            request_id=None,
        )
    )
    await session.commit()
    await session.refresh(asset)
    return await catalog_payload(session, asset)


@router.put("/catalogs/{catalog_asset_id}/event-types")
async def replace_catalog_event_types(
    catalog_asset_id: UUID,
    body: CatalogEventTypesRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> CatalogPayload:
    agent = await authenticated_admin(session, authorization)
    event_type_mappings = parse_catalog_event_type_mappings(body.event_types)
    validate_catalog_event_type_mappings(event_type_mappings)
    asset = await session.get(CatalogAsset, catalog_asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog not found")
    old_event_types = await catalog_event_types(session, asset.catalog_asset_id)
    old_event_type_mappings = await catalog_event_type_mappings(session, asset.catalog_asset_id)
    existing = (
        await session.scalars(
            select(CatalogEventTypeMap).where(
                CatalogEventTypeMap.catalog_asset_id == catalog_asset_id
            )
        )
    ).all()
    for row in existing:
        await session.delete(row)
    for mapping in event_type_mappings:
        session.add(
            CatalogEventTypeMap(
                catalog_asset_id=catalog_asset_id,
                event_type=mapping.event_type,
                send_mode=mapping.send_mode,
            )
        )
    session.add(
        AuditEvent(
            actor=agent.name,
            action="CATALOG_EVENT_TYPES_REPLACED",
            entity="catalog_asset",
            old_value={
                "event_types": old_event_types,
                "event_type_mappings": [
                    mapping.model_dump() for mapping in old_event_type_mappings
                ],
            },
            new_value={
                "catalog_asset_id": str(catalog_asset_id),
                "event_types": catalog_event_type_names(event_type_mappings),
                "event_type_mappings": catalog_event_type_mapping_values(event_type_mappings),
            },
            reason="Admin replaced catalog event type mappings",
            request_id=None,
        )
    )
    await session.commit()
    await session.refresh(asset)
    return await catalog_payload(session, asset)


@router.post("/login")
async def login(body: LoginRequest, session: DbSession) -> LoginPayload:
    document_id = body.document_id.strip()
    agent = await session.scalar(select(Agent).where(Agent.document_id == document_id))
    password_hash = (
        agent.password_hash if agent is not None and agent.password_hash else DUMMY_PASSWORD_HASH
    )
    pin_ok = verify_pin(body.pin, password_hash)
    if agent is None or not pin_ok:
        session.add(
            AuditEvent(
                actor="UNKNOWN",
                action="ADMIN_LOGIN_FAILED",
                entity="agent",
                old_value=None,
                new_value={"document_id": document_id},
                reason="Invalid credentials",
                request_id=None,
            )
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not agent.active:
        session.add(
            AuditEvent(
                actor=agent.name,
                action="ADMIN_LOGIN_FAILED",
                entity="agent",
                old_value=None,
                new_value={"agent_id": agent.id, "document_id": document_id},
                reason="Inactive agent",
                request_id=None,
            )
        )
        await session.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is inactive")

    token = secrets.token_urlsafe(32)
    await delete_expired_sessions_for_agent(session, agent.id)
    agent_session = AgentSession(
        agent_id=agent.id,
        token_hash=hash_agent_token(token),
        expires_at=datetime.now(UTC) + timedelta(hours=12),
    )
    session.add(agent_session)
    session.add(
        AuditEvent(
            actor=agent.name,
            action="ADMIN_LOGIN_SUCCEEDED",
            entity="agent",
            old_value=None,
            new_value={"agent_id": agent.id, "role": agent.role},
            reason="Admin session created",
            request_id=None,
        )
    )
    await session.commit()
    return LoginPayload(token=token, agent=agent_identity_payload(agent))


@router.post("/logout")
async def logout(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    agent = await authenticated_agent(session, authorization)
    agent_name = agent.name
    agent_id = agent.id
    agent_session = await resolve_session_from_authorization(session, authorization)
    if agent_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    await session.rollback()
    async with session.begin():
        agent_session.revoked_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                actor=agent_name,
                action="ADMIN_LOGOUT",
                entity="agent_session",
                old_value={"revoked_at": None},
                new_value={"agent_id": agent_id, "revoked": True},
                reason="Admin session revoked",
                request_id=None,
            )
        )
    return {"status": "ok"}


@router.post("/agents")
async def create_agent(
    body: CreateAgentRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AgentPayload:
    admin = await authenticated_admin(session, authorization)
    admin_name = admin.name
    await session.rollback()
    async with session.begin():
        agent = Agent(name=body.name, role=body.role, active=True)
        session.add(agent)
        await session.flush()
        session.add(
            AuditEvent(
                actor=admin_name,
                action="AGENT_CREATED",
                entity="agent",
                old_value=None,
                new_value={
                    "agent_id": agent.id,
                    "name": agent.name,
                    "active": agent.active,
                    "role": agent.role,
                },
                reason="Admin created agent",
                request_id=None,
            )
        )
    return AgentPayload(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        active=agent.active,
        created_at=agent.created_at,
    )


@router.get("/agents")
async def list_agents(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[AgentPayload]:
    await authenticated_admin(session, authorization)
    agents = await session.scalars(select(Agent).order_by(Agent.name.asc()))
    return [
        AgentPayload(
            id=agent.id,
            name=agent.name,
            role=agent.role,
            active=agent.active,
            created_at=agent.created_at,
        )
        for agent in agents.all()
    ]


@router.post("/agents/{agent_id}/credentials")
async def set_agent_credentials(
    agent_id: int,
    body: AgentCredentialsRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    admin = await authenticated_admin(session, authorization)
    admin_name = admin.name
    await session.rollback()
    async with session.begin():
        agent = await session.get(Agent, agent_id, with_for_update=True)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        old_value = {"agent_id": agent.id, "document_id": agent.document_id}
        agent.document_id = body.document_id.strip()
        agent.password_hash = hash_pin(body.pin)
        await revoke_sessions_for_agent(session, agent.id)
        session.add(
            AuditEvent(
                actor=admin_name,
                action="AGENT_CREDENTIALS_RESET",
                entity="agent",
                old_value=old_value,
                new_value={"agent_id": agent.id, "document_id": agent.document_id},
                reason="Admin reset agent credentials",
                request_id=None,
            )
        )
    return {"id": agent.id, "document_id": agent.document_id, "status": "credentials_set"}


@router.post("/agents/{agent_id}/deactivate")
async def deactivate_agent(
    agent_id: int,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    admin = await authenticated_admin(session, authorization)
    admin_name = admin.name
    await session.rollback()
    async with session.begin():
        agent = await session.get(Agent, agent_id, with_for_update=True)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        was_active = agent.active
        agent.active = False
        await revoke_sessions_for_agent(session, agent.id)
        active_conversation_count = await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.assigned_agent_id == agent.id,
                Conversation.state == ConversationState.HUMAN_ACTIVE.value,
            )
        )
        session.add(
            AuditEvent(
                actor=admin_name,
                action="AGENT_DEACTIVATED",
                entity="agent",
                old_value={"agent_id": agent.id, "active": was_active},
                new_value={
                    "agent_id": agent.id,
                    "active": agent.active,
                    "active_conversation_count": active_conversation_count or 0,
                },
                reason="Admin deactivated agent",
                request_id=None,
            )
        )
    return {
        "id": agent.id,
        "name": agent.name,
        "active": agent.active,
        "active_conversation_count": active_conversation_count or 0,
    }


@router.get("/me")
async def read_me(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AgentIdentityPayload:
    agent = await authenticated_agent(session, authorization)
    return AgentIdentityPayload(id=agent.id, name=agent.name, role=agent.role)


@router.get("/handoffs")
async def list_handoffs(
    session: DbSession,
    status: HandoffListStatus = "PENDING",
    authorization: Annotated[str | None, Header()] = None,
) -> list[dict[str, object]]:
    await authenticated_agent(session, authorization)
    result = await session.execute(
        select(Handoff, Customer)
        .join(Conversation, Handoff.conversation_id == Conversation.id)
        .join(Customer, Conversation.customer_id == Customer.id)
        .where(Handoff.status == status)
        .order_by(Handoff.created_at.asc())
    )
    return [handoff_payload(handoff, customer) for handoff, customer in result.all()]


@router.get("/conversations")
async def list_conversations(
    session: DbSession,
    state: str | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    authorization: Annotated[str | None, Header()] = None,
) -> list[ConversationPayload]:
    agent = await authenticated_agent(session, authorization)
    if state is not None:
        try:
            ConversationState(state)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid conversation state",
            ) from exc
    filters = []
    if state is not None:
        filters.append(Conversation.state == state)
    if assigned_to_me:
        filters.append(Conversation.assigned_agent_id == agent.id)

    statement = (
        select(Conversation, Customer, Agent)
        .join(Customer, Conversation.customer_id == Customer.id)
        .outerjoin(Agent, Conversation.assigned_agent_id == Agent.id)
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        statement = statement.where(*filters)
    result = await session.execute(statement)
    conversations = result.all()
    payloads: list[ConversationPayload] = []
    for conversation, customer, assigned_agent in conversations:
        handoff = await latest_handoff_for_conversation(session, conversation.id)
        latest_message = await latest_message_for_conversation(session, conversation.id)
        latest_body = message_body(latest_message) if latest_message is not None else None
        payloads.append(
            ConversationPayload(
                id=conversation.id,
                conversation_id=conversation.id,
                customer_name=customer.full_name,
                customer_phone=customer.phone_number,
                state=conversation.state,
                last_intent=conversation.last_intent,
                pending_action=conversation.pending_action,
                bot_enabled=conversation.bot_enabled,
                handoff_id=handoff.id if handoff is not None else None,
                handoff_status=handoff.status if handoff is not None else None,
                assigned_to=handoff.assigned_to if handoff is not None else None,
                assigned_agent=agent_identity_payload(assigned_agent),
                handoff_reason=handoff.reason if handoff is not None else None,
                handoff_priority=handoff.priority if handoff is not None else None,
                handoff_summary=handoff.summary if handoff is not None else None,
                last_message_body=latest_body,
                last_message_preview=truncate_preview(latest_body),
                last_message_direction=latest_message.direction
                if latest_message is not None
                else None,
                last_message_at=conversation.last_message_at,
            )
        )
    return payloads


@router.post("/handoffs/{handoff_id}/take")
async def take_handoff(
    handoff_id: int,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    agent = await authenticated_agent(session, authorization)
    actor = agent.name
    assigned_agent_id = agent.id
    await session.rollback()

    async with session.begin():
        handoff = await session.get(Handoff, handoff_id, with_for_update=True)
        if handoff is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found")
        if handoff.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Handoff is not pending",
            )

        conversation = await session.get(
            Conversation,
            handoff.conversation_id,
            with_for_update=True,
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.state != ConversationState.WAITING_FOR_HUMAN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation is not waiting for human",
            )
        customer = await session.get(Customer, conversation.customer_id)

        now = datetime.now(UTC)
        handoff.status = "TAKEN"
        handoff.assigned_to = actor
        handoff.assigned_agent_id = assigned_agent_id
        handoff.taken_at = now
        conversation.bot_enabled = False
        conversation.assigned_agent_id = assigned_agent_id
        await transition_conversation(
            session,
            conversation,
            ConversationState.HUMAN_ACTIVE,
            actor=actor,
            reason="Handoff taken by human agent",
        )
        session.add(
            AuditEvent(
                actor=actor,
                action="HANDOFF_TAKEN",
                entity="handoff",
                old_value={"status": "PENDING"},
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "status": "TAKEN",
                    "assigned_to": actor,
                    "assigned_agent_id": assigned_agent_id,
                },
                reason="Human agent took handoff",
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/conversations/{conversation_id}/take")
async def take_conversation(
    conversation_id: int,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    agent = await authenticated_agent(session, authorization)
    agent_id = agent.id
    agent_name = agent.name
    await session.rollback()

    async with session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        customer = await session.get(Customer, conversation.customer_id)
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation has no customer",
            )

        if conversation.state == ConversationState.HUMAN_ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation already has an active human agent",
            )
        if conversation.state == ConversationState.CLOSED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Closed conversations require explicit admin reopening",
            )
        if conversation.state == ConversationState.WAITING_FOR_HUMAN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation has a handoff pendiente; take the existing handoff",
            )
        if conversation.state not in DIRECT_TAKE_ELIGIBLE_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation state is not eligible for direct takeover",
            )

        now = datetime.now(UTC)
        previous_state = conversation.state
        previous_bot_enabled = conversation.bot_enabled
        previous_assigned_agent_id = conversation.assigned_agent_id

        if conversation.state == ConversationState.RESOLVED.value:
            session.add(
                AuditEvent(
                    actor=agent_name,
                    action="CONVERSATION_REOPENED",
                    entity="conversation",
                    old_value={"conversation_id": conversation.id, "state": conversation.state},
                    new_value={
                        "conversation_id": conversation.id,
                        "state": ConversationState.BOT_ACTIVE.value,
                    },
                    reason="Direct takeover reopened resolved conversation",
                    request_id=None,
                )
            )
            await transition_conversation(
                session,
                conversation,
                ConversationState.BOT_ACTIVE,
                actor=agent_name,
                reason="Direct takeover reopening",
            )

        handoff = Handoff(
            conversation_id=conversation.id,
            reason="MANUAL_TAKEOVER",
            priority="NORMAL",
            summary=await build_manual_takeover_summary(session, conversation, customer),
            status="TAKEN",
            assigned_to=agent_name,
            assigned_agent_id=agent_id,
            taken_at=now,
        )
        session.add(handoff)
        await session.flush()
        session.add(
            AuditEvent(
                actor=agent_name,
                action="HANDOFF_CREATED",
                entity="handoff",
                old_value=None,
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "reason": "MANUAL_TAKEOVER",
                    "priority": "NORMAL",
                    "status": "TAKEN",
                },
                reason="Manual direct takeover",
                request_id=None,
            )
        )

        conversation.bot_enabled = False
        conversation.pending_action = "WAIT_FOR_HUMAN"
        conversation.assigned_agent_id = agent_id
        await move_conversation_to_human_active(
            session,
            conversation,
            actor=agent_name,
            reason="Manual direct takeover",
        )
        session.add(
            AuditEvent(
                actor=agent_name,
                action="HANDOFF_TAKEN",
                entity="handoff",
                old_value={"status": "PENDING"},
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "status": "TAKEN",
                    "assigned_to": agent_name,
                    "assigned_agent_id": agent_id,
                },
                reason="Manual direct takeover",
                request_id=None,
            )
        )
        session.add(
            AuditEvent(
                actor=agent_name,
                action="CONVERSATION_MANUAL_TAKEOVER",
                entity="conversation",
                old_value={
                    "conversation_id": conversation.id,
                    "state": previous_state,
                    "bot_enabled": previous_bot_enabled,
                    "assigned_agent_id": previous_assigned_agent_id,
                },
                new_value={
                    "conversation_id": conversation.id,
                    "handoff_id": handoff.id,
                    "state": ConversationState.HUMAN_ACTIVE.value,
                    "bot_enabled": False,
                    "assigned_to": agent_name,
                    "assigned_agent_id": agent_id,
                },
                reason="Manual direct takeover",
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/handoffs/{handoff_id}/return")
async def return_handoff(
    handoff_id: int,
    body: ReturnHandoffRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    agent = await authenticated_agent(session, authorization)
    actor = agent.name
    await session.rollback()

    async with session.begin():
        handoff = await session.get(Handoff, handoff_id, with_for_update=True)
        if handoff is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found")
        if handoff.status != "TAKEN":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Handoff is not taken",
            )

        conversation = await session.get(
            Conversation,
            handoff.conversation_id,
            with_for_update=True,
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.state != ConversationState.HUMAN_ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation is not human active",
            )
        customer = await session.get(Customer, conversation.customer_id)

        handoff.status = "RETURNED"
        handoff.resolved_at = datetime.now(UTC)
        handoff.assigned_agent_id = None
        handoff.assigned_to = None
        conversation.bot_enabled = True
        conversation.pending_action = None
        conversation.assigned_agent_id = None
        await transition_conversation(
            session,
            conversation,
            ConversationState.RETURNED_TO_BOT,
            actor=actor,
            reason=body.resolution,
        )
        await transition_conversation(
            session,
            conversation,
            ConversationState.BOT_ACTIVE,
            actor=actor,
            reason="Returned to bot after human handling",
        )
        session.add(
            AuditEvent(
                actor=actor,
                action="HANDOFF_RETURNED",
                entity="handoff",
                old_value={"status": "TAKEN"},
                new_value={
                    "handoff_id": handoff.id,
                    "conversation_id": conversation.id,
                    "status": "RETURNED",
                },
                reason=body.resolution,
                request_id=None,
            )
        )

    return handoff_payload(handoff, customer)


@router.post("/conversations/{conversation_id}/messages")
async def create_agent_message(
    conversation_id: int,
    body: AgentMessageRequest,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, int | str]:
    agent = await authenticated_agent(session, authorization)
    actor = agent.name
    await session.rollback()

    async with session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.state != ConversationState.HUMAN_ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation is not human active",
            )

        customer = await session.get(Customer, conversation.customer_id)
        latest_message = await session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.desc())
            .limit(1)
        )
        if customer is None or latest_message is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conversation cannot receive agent messages",
            )

        outbox = Outbox(
            conversation_id=conversation.id,
            message_id=latest_message.id,
            channel=Channel.WHATSAPP,
            recipient_phone_number=customer.phone_number,
            payload={
                "type": "text",
                "text": {"body": body.text},
                "agent": True,
            },
            status="PENDING",
        )
        session.add(outbox)
        active_handoff = await session.scalar(
            select(Handoff)
            .where(
                Handoff.conversation_id == conversation.id,
                Handoff.status == "TAKEN",
            )
            .order_by(Handoff.id.desc())
            .limit(1)
        )
        if active_handoff is not None:
            active_handoff.summary = append_handoff_summary_line(
                active_handoff.summary,
                "OUTBOUND",
                body.text,
            )
        await session.flush()
        session.add(
            AuditEvent(
                actor=actor,
                action="AGENT_MESSAGE_ENQUEUED",
                entity="outbox",
                old_value=None,
                new_value={
                    "conversation_id": conversation.id,
                    "outbox_id": outbox.id,
                },
                reason="Human agent message queued through admin API",
                request_id=None,
            )
        )

    return {"outbox_id": outbox.id, "status": outbox.status}


@router.get("/conversations/{conversation_id}/messages")
async def list_conversation_messages(
    conversation_id: int,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> list[ConversationMessagePayload]:
    await authenticated_agent(session, authorization)
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    message_rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    messages = [
        ConversationMessagePayload(
            id=f"message-{message.id}",
            direction=message_direction(message),
            body=message_body(message),
            message_type=message.message_type,
            status=None,
            created_at=message.created_at,
        )
        for message in message_rows.all()
    ]

    pending_outbox_rows = await session.scalars(
        select(Outbox)
        .where(
            Outbox.conversation_id == conversation_id,
            Outbox.status != "SENT",
        )
        .order_by(Outbox.created_at.asc(), Outbox.id.asc())
    )
    messages.extend(
        ConversationMessagePayload(
            id=f"outbox-{outbox.id}",
            direction="OUTBOUND",
            body=outbox_body(outbox),
            message_type=str(outbox.payload.get("type", "text")),
            status=outbox.status,
            created_at=outbox.created_at,
        )
        for outbox in pending_outbox_rows.all()
    )
    return sorted(messages, key=lambda message: (message.created_at, message.id))


@router.get("/conversations/{conversation_id}/history")
async def list_conversation_assignment_history(
    conversation_id: int,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    authorization: Annotated[str | None, Header()] = None,
) -> list[AssignmentHistoryPayload]:
    await authenticated_agent(session, authorization)
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    conversation_id_text = str(conversation_id)
    old_conversation_id = cast(AuditEvent.old_value, JSONB)["conversation_id"].astext
    new_conversation_id = cast(AuditEvent.new_value, JSONB)["conversation_id"].astext
    events = await session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.action.in_(
                [
                    "HANDOFF_TAKEN",
                    "HANDOFF_RETURNED",
                    "CONVERSATION_MANUAL_TAKEOVER",
                ]
            ),
            or_(
                old_conversation_id == conversation_id_text,
                new_conversation_id == conversation_id_text,
            ),
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(limit)
    )
    return [
        AssignmentHistoryPayload(
            actor=event.actor,
            action=event.action,
            created_at=event.created_at,
        )
        for event in events.all()
    ]


async def latest_handoff_for_conversation(
    session: AsyncSession,
    conversation_id: int,
    *,
    locked: bool = False,
) -> Handoff | None:
    statement = (
        select(Handoff)
        .where(Handoff.conversation_id == conversation_id)
        .order_by(Handoff.id.desc())
        .limit(1)
    )
    if locked:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def latest_message_for_conversation(
    session: AsyncSession,
    conversation_id: int,
) -> Message | None:
    return await session.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(1)
    )


async def build_manual_takeover_summary(
    session: AsyncSession,
    conversation: Conversation,
    customer: Customer,
    last_messages_limit: int = 5,
) -> str:
    result = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(last_messages_limit)
    )
    messages = list(reversed(result.all()))
    lines = [
        f"Cliente: {customer.full_name or 'Sin nombre confirmado'}",
        f"Telefono: {customer.phone_number}",
        f"Conversacion: {conversation.id}",
        "Motivo: MANUAL_TAKEOVER",
        "Ultimos mensajes:",
    ]
    for message in messages:
        lines.append(f"- {message.direction}: {message_body(message)}")
    return "\n".join(lines)


async def move_conversation_to_human_active(
    session: AsyncSession,
    conversation: Conversation,
    actor: str,
    reason: str,
) -> None:
    current_state = ConversationState(conversation.state)
    if current_state == ConversationState.HUMAN_ACTIVE:
        return
    if current_state != ConversationState.WAITING_FOR_HUMAN:
        await transition_conversation(
            session,
            conversation,
            ConversationState.WAITING_FOR_HUMAN,
            actor=actor,
            reason=reason,
        )
    await transition_conversation(
        session,
        conversation,
        ConversationState.HUMAN_ACTIVE,
        actor=actor,
        reason=reason,
    )


def agent_identity_payload(agent: Agent | None) -> AgentIdentityPayload | None:
    if agent is None:
        return None
    return AgentIdentityPayload(id=agent.id, name=agent.name, role=agent.role)


def truncate_preview(text: str | None, limit: int = 120) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def append_handoff_summary_line(summary: str, direction: str, text: str) -> str:
    clean_text = " ".join(text.split())
    if not clean_text:
        return summary
    return f"{summary.rstrip()}\n- {direction}: {clean_text}"


def message_direction(message: Message) -> Literal["INBOUND", "OUTBOUND"]:
    if message.direction not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation message has invalid direction",
        )
    return message.direction


def message_body(message: Message) -> str:
    text = message.content.get("text")
    if isinstance(text, dict) and isinstance(text.get("body"), str):
        return text["body"]
    return "[mensaje no textual]"


def outbox_body(outbox: Outbox) -> str:
    text = outbox.payload.get("text")
    if isinstance(text, dict) and isinstance(text.get("body"), str):
        return text["body"]
    return "[mensaje saliente no textual]"


def handoff_payload(handoff: Handoff, customer: Customer | None = None) -> dict[str, object]:
    return {
        "id": handoff.id,
        "conversation_id": handoff.conversation_id,
        "customer_name": customer.full_name if customer is not None else None,
        "customer_phone": customer.phone_number if customer is not None else None,
        "reason": handoff.reason,
        "priority": handoff.priority,
        "summary": handoff.summary,
        "status": handoff.status,
        "assigned_to": handoff.assigned_to,
        "assigned_agent": (
            {"id": handoff.assigned_agent_id, "name": handoff.assigned_to}
            if handoff.assigned_agent_id is not None
            else None
        ),
        "created_at": handoff.created_at,
        "taken_at": handoff.taken_at,
        "resolved_at": handoff.resolved_at,
    }


def resolve_catalog_file_path(request: Request, relative_path: str) -> Path:
    raw_path = Path(relative_path.strip())
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid path")
    storage_dir = Path(request.app.state.settings.catalog_storage_dir).resolve()
    file_path = (storage_dir / raw_path).resolve()
    if not file_path.is_relative_to(storage_dir):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid path")
    return file_path


async def store_catalog_upload(
    request: Request,
    upload: UploadFile,
) -> tuple[Path, str, int, bool]:
    filename = (upload.filename or "").strip()
    normalized_filename = filename.replace("\\", "/")
    filename_path = PurePosixPath(normalized_filename)
    if (
        not filename
        or filename_path.is_absolute()
        or ".." in filename_path.parts
        or len(filename_path.parts) != 1
        or filename_path.suffix.casefold() != ".pdf"
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid PDF filename",
        )
    if upload.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only application/pdf catalogs are supported",
        )

    storage_dir = Path(request.app.state.settings.catalog_storage_dir).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = storage_dir / f".upload-{uuid4().hex}.tmp"
    max_bytes = request.app.state.settings.catalog_max_file_mb * 1024 * 1024
    digest = hashlib.sha256()
    file_size = 0
    magic = b""
    try:
        with temporary_path.open("xb") as output:
            while chunk := await upload.read(64 * 1024):
                file_size += len(chunk)
                if file_size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Catalog file exceeds configured maximum size",
                    )
                if len(magic) < 4:
                    magic = (magic + chunk)[:4]
                digest.update(chunk)
                output.write(chunk)
        if file_size == 0 or magic != b"%PDF":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Uploaded content is not a PDF",
            )

        file_hash = digest.hexdigest()
        stored_path = storage_dir / f"{file_hash[:16]}.pdf"
        created_new_file = not stored_path.exists()
        if created_new_file:
            temporary_path.replace(stored_path)
        else:
            if sha256_file(stored_path) != file_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Catalog hash prefix collision",
                )
            temporary_path.unlink()
        return stored_path, file_hash, file_size, created_new_file
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def validate_catalog_admin_file(request: Request, file_path: Path) -> int:
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File not found"
        )
    if detect_pdf_mime_type(file_path) != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only application/pdf catalogs are supported",
        )
    file_size = file_path.stat().st_size
    max_bytes = request.app.state.settings.catalog_max_file_mb * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Catalog file exceeds configured maximum size",
        )
    return file_size


def parse_catalog_event_type_mappings(
    event_types: list[CatalogEventTypeInput],
) -> list[CatalogEventTypeMappingRequest]:
    mappings: list[CatalogEventTypeMappingRequest] = []
    for entry in event_types:
        if isinstance(entry, str):
            mappings.append(CatalogEventTypeMappingRequest(event_type=entry))
        else:
            mappings.append(entry)
    return mappings


def validate_catalog_event_type_mappings(
    mappings: list[CatalogEventTypeMappingRequest],
) -> None:
    invalid = [mapping.event_type for mapping in mappings if mapping.event_type not in EVENT_TYPES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"invalid_event_types": invalid},
        )
    invalid_modes = [
        mapping.send_mode for mapping in mappings if mapping.send_mode not in CATALOG_SEND_MODES
    ]
    if invalid_modes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"invalid_send_modes": invalid_modes},
        )


def catalog_event_type_names(mappings: list[CatalogEventTypeMappingRequest]) -> list[str]:
    return [mapping.event_type for mapping in mappings]


def catalog_event_type_mapping_values(
    mappings: list[CatalogEventTypeMappingRequest],
) -> list[dict[str, str]]:
    return [mapping.model_dump() for mapping in mappings]


def blocked_date_payload(blocked_date: BlockedDate) -> BlockedDatePayload:
    return BlockedDatePayload(
        blocked_date=blocked_date.blocked_date,
        reason=blocked_date.reason,
        actor=blocked_date.actor,
        created_at=blocked_date.created_at,
        updated_at=blocked_date.updated_at,
    )


def holiday_payload(holiday: Holiday) -> HolidayPayload:
    return HolidayPayload(
        holiday_date=holiday.holiday_date,
        name=holiday.name,
        source=holiday.source,
        created_at=holiday.created_at,
        updated_at=holiday.updated_at,
    )


def appointment_day_payload(appointment: Appointment) -> AppointmentDayPayload:
    return AppointmentDayPayload(
        appointment_id=appointment.appointment_id,
        customer_id=appointment.customer_id,
        lead_id=appointment.lead_id,
        appointment_date=appointment.appointment_date,
        start_time=appointment.start_time,
        end_time=appointment.end_time,
        timezone=appointment.timezone,
        attendee_count=appointment.attendee_count,
        visit_reason=appointment.visit_reason,
        appointment_status=appointment.appointment_status,
        external_calendar_id=appointment.external_calendar_id,
        requires_reconciliation=appointment.requires_reconciliation,
    )


async def catalog_event_types(session: AsyncSession, catalog_asset_id: UUID) -> list[str]:
    return list(
        (
            await session.scalars(
                select(CatalogEventTypeMap.event_type)
                .where(CatalogEventTypeMap.catalog_asset_id == catalog_asset_id)
                .order_by(CatalogEventTypeMap.event_type)
            )
        ).all()
    )


async def catalog_event_type_mappings(
    session: AsyncSession, catalog_asset_id: UUID
) -> list[CatalogEventTypeMappingPayload]:
    rows = (
        await session.execute(
            select(CatalogEventTypeMap.event_type, CatalogEventTypeMap.send_mode)
            .where(CatalogEventTypeMap.catalog_asset_id == catalog_asset_id)
            .order_by(CatalogEventTypeMap.event_type)
        )
    ).all()
    return [
        CatalogEventTypeMappingPayload(event_type=row.event_type, send_mode=row.send_mode)
        for row in rows
    ]


async def catalog_payload(session: AsyncSession, asset: CatalogAsset) -> CatalogPayload:
    return CatalogPayload(
        catalog_asset_id=asset.catalog_asset_id,
        name=asset.name,
        file_path=asset.file_path,
        file_hash=asset.file_hash,
        mime_type=asset.mime_type,
        file_size=asset.file_size,
        media_cached=bool(asset.media_id and asset.media_uploaded_at),
        media_uploaded_at=asset.media_uploaded_at,
        active=asset.active,
        version=asset.version,
        event_types=await catalog_event_types(session, asset.catalog_asset_id),
        event_type_mappings=await catalog_event_type_mappings(session, asset.catalog_asset_id),
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )

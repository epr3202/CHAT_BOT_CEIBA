from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.catalog.service as catalog_service
from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import ExtractedEntity, IntentClassification
from app.audit.models import AuditEvent
from app.catalog.models import CatalogAsset, CatalogEventTypeMap, CatalogSend
from app.channel.inbound import process_whatsapp_webhook
from app.channel.media import sha256_file
from app.channel.models import Message, Outbox
from app.channel.outbound import WhatsAppInvalidMediaError
from app.channel.states import Channel
from app.channel.worker import process_outbox_once
from app.config.settings import get_settings
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.states import ConversationState
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.lead.models import Lead
from app.orchestrator.service import OrchestrationInput, orchestrate_inbound_message
from tests.integration.helpers import (
    app_client,
    bootstrap_agent,
    cleanup_test_environment,
    database_sessionmaker,
    login_headers,
    reset_test_database,
    whatsapp_message_payload,
)


class CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


class FakeWhatsAppAdapter:
    def __init__(
        self,
        upload_error: Exception | None = None,
        reject_first_document_media: bool = False,
        block_document_send: bool = False,
    ) -> None:
        self.upload_error = upload_error
        self.reject_first_document_media = reject_first_document_media
        self.upload_calls = 0
        self.text_calls = 0
        self.document_calls = 0
        self.sent_documents: list[dict[str, str]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not block_document_send:
            self.release.set()

    async def send_text(self, to: str, body: str) -> str:
        self.text_calls += 1
        return f"wamid.text.{self.text_calls}"

    async def upload_media(self, file_path: Path, mime_type: str) -> str:
        self.upload_calls += 1
        if self.upload_error is not None:
            raise self.upload_error
        return f"media-{self.upload_calls}"

    async def send_document(self, to: str, media_id: str, filename: str, caption: str) -> str:
        self.document_calls += 1
        self.started.set()
        await self.release.wait()
        if self.reject_first_document_media and self.document_calls == 1:
            raise WhatsAppInvalidMediaError("invalid media")
        self.sent_documents.append(
            {"to": to, "media_id": media_id, "filename": filename, "caption": caption}
        )
        return f"wamid.document.{self.document_calls}"


@pytest.fixture(autouse=True)
async def test_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[None]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba_test")
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("META_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-meta-access-token")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "123456789")
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v20.0")
    monkeypatch.setenv("WHATSAPP_API_BASE_URL", "https://graph.facebook.com")
    monkeypatch.setenv("WEBHOOK_MAX_BODY_BYTES", "1048576")
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_SECONDS", "0.01")
    monkeypatch.setenv("OUTBOX_BATCH_SIZE", "10")
    monkeypatch.setenv("OUTBOX_SENDING_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("OUTBOX_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("OUTBOX_MAX_BACKOFF_SECONDS", "300")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("OPENROUTER_MAX_RETRIES", "1")
    monkeypatch.setenv("AI_CONFIDENCE_SAFE", "0.85")
    monkeypatch.setenv("AI_CONFIDENCE_PROBABLE", "0.70")
    monkeypatch.setenv("AI_CONFIDENCE_UNCERTAIN", "0.50")
    monkeypatch.setenv("HUMAN_HOURS_DAYS", "0,1,2,3,4,5,6")
    monkeypatch.setenv("HUMAN_HOURS_START", "00:00")
    monkeypatch.setenv("HUMAN_HOURS_END", "23:59")
    monkeypatch.setenv("CATALOG_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    sessionmaker = await reset_test_database()
    await approve_base_templates(sessionmaker)
    yield
    await cleanup_test_environment()


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async for sessionmaker in database_sessionmaker():
        yield sessionmaker


@pytest.fixture
async def client_fixture() -> AsyncIterator[AsyncClient]:
    async for client in app_client():
        yield client


def pdf_file(tmp_path: Path, name: str = "catalogo-bodas.pdf", size: int = 32) -> Path:
    file_path = tmp_path / name
    file_path.write_bytes(b"%PDF-1.4\n" + (b"x" * size))
    return file_path


async def approve_catalog_templates(
    sessionmaker: async_sessionmaker[AsyncSession],
    caption: str = "Te comparto nuestro catálogo para {event_type}.",
    statuses: dict[str, str] | None = None,
) -> None:
    statuses = statuses or {}
    async with sessionmaker() as session:
        async with session.begin():
            for code in ("RESP-CATALOG-001", "RESP-CATALOG-002", "RESP-CATALOG-003"):
                existing = await session.scalar(
                    select(KnowledgeEntry).where(KnowledgeEntry.code == code)
                )
                if existing is not None:
                    await session.delete(existing)
            session.add_all(
                [
                    KnowledgeEntry(
                        code="RESP-CATALOG-001",
                        category="Catalogos",
                        question_summary="Caption catalogo",
                        answer_template=caption,
                        allowed_variables=["event_type"],
                        version=1,
                        status=statuses.get("RESP-CATALOG-001", "APPROVED"),
                    ),
                    KnowledgeEntry(
                        code="RESP-CATALOG-002",
                        category="Catalogos",
                        question_summary="Pregunta tipo evento",
                        answer_template=(
                            "Con gusto te comparto nuestro catálogo. "
                            "¿Para qué tipo de evento lo necesitas?"
                        ),
                        allowed_variables=[],
                        version=1,
                        status=statuses.get("RESP-CATALOG-002", "APPROVED"),
                    ),
                    KnowledgeEntry(
                        code="RESP-CATALOG-003",
                        category="Catalogos",
                        question_summary="Catalogo no disponible",
                        answer_template=(
                            "Para ese tipo de evento nuestro equipo te compartirá la "
                            "información directamente. Ya registré tu solicitud."
                        ),
                        allowed_variables=[],
                        version=1,
                        status=statuses.get("RESP-CATALOG-003", "APPROVED"),
                    ),
                ]
            )


async def approve_base_templates(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            session.add_all(
                [
                    KnowledgeEntry(
                        code="RESP-EVENT-DATA-004",
                        category="Datos de evento",
                        question_summary="Pregunta asistentes",
                        answer_template="¿Para cuántas personas aproximadamente?",
                        allowed_variables=[],
                        version=1,
                        status="APPROVED",
                    ),
                    KnowledgeEntry(
                        code="RESP-AI-ERROR-001",
                        category="Fallback",
                        question_summary="Error seguro",
                        answer_template="En este momento no puedo procesar esa información.",
                        allowed_variables=[],
                        version=1,
                        status="APPROVED",
                    ),
                    KnowledgeEntry(
                        code="RESP-GREETING-001",
                        category="Saludo",
                        question_summary="Saludo",
                        answer_template="Hola, soy el asistente de La Ceiba Club House.",
                        allowed_variables=[],
                        version=1,
                        status="APPROVED",
                    ),
                ]
            )


async def seed_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
    phone: str | None = None,
    event_type: str | None = None,
) -> tuple[int, UUID, UUID, int]:
    phone = phone or f"+5730{uuid4().int % 10_000_0000:08d}"
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=phone)
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                state=ConversationState.BOT_ACTIVE,
            )
            session.add(conversation)
            await session.flush()
            lead = Lead(customer_id=customer.id, channel=Channel.WHATSAPP, lead_status="QUALIFYING")
            session.add(lead)
            await session.flush()
            conversation.active_lead_id = lead.lead_id
            event = Event(lead_id=lead.lead_id, event_type=event_type)
            session.add(event)
            inbound = Message(
                external_message_id=f"wamid.in.{uuid4()}",
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": "Hola"}},
                provider_timestamp=None,
            )
            session.add(inbound)
            await session.flush()
            return conversation.id, lead.lead_id, event.event_id, inbound.id


async def add_inbound_message(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
    suffix: str,
    text: str = "mensaje",
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None
            inbound = Message(
                external_message_id=f"wamid.in.{conversation_id}.{suffix}.{uuid4()}",
                conversation_id=conversation.id,
                customer_id=conversation.customer_id,
                channel=Channel.WHATSAPP,
                direction="INBOUND",
                message_type="text",
                content={"text": {"body": text}},
                provider_timestamp=None,
            )
            session.add(inbound)
            await session.flush()
            return inbound.id


async def seed_catalog_asset(
    sessionmaker: async_sessionmaker[AsyncSession],
    file_path: Path,
    event_type: str = "WEDDING",
    active: bool = True,
    media_id: str | None = None,
    media_uploaded_at: datetime | None = None,
    send_mode: str = "ON_REQUEST",
) -> UUID:
    async with sessionmaker() as session:
        async with session.begin():
            asset = CatalogAsset(
                name="Catálogo Bodas",
                file_path=file_path.name,
                file_hash=sha256_file(file_path),
                mime_type="application/pdf",
                file_size=file_path.stat().st_size,
                media_id=media_id,
                media_uploaded_at=media_uploaded_at,
                active=active,
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
            return asset.catalog_asset_id


async def orchestrate(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: int,
    inbound_id: int,
    classification: IntentClassification,
    text: str = "mensaje",
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            conversation = await session.get(Conversation, conversation_id)
            inbound = await session.get(Message, inbound_id)
            assert conversation is not None
            assert inbound is not None
            customer = await session.get(Customer, conversation.customer_id)
            assert customer is not None
            await orchestrate_inbound_message(
                session,
                get_settings(),
                sessionmaker,
                OrchestrationInput(conversation, customer, inbound, text, "req-cat"),
                classification,
            )


def event_type_entity(quality_status: str = "PROVIDED") -> ExtractedEntity:
    return ExtractedEntity(
        entity="event_type",
        raw_value="boda",
        normalized_value="WEDDING",
        quality_status=quality_status,
        confidence=0.95,
        needs_confirmation=False,
        validation_errors=[],
    )


def classification_for_event_type(quality_status: str = "PROVIDED") -> IntentClassification:
    return IntentClassification(
        primary_intent="EVENT_INFORMATION",
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        entities={},
        extracted_entities=[event_type_entity(quality_status)],
        requested_action="COLLECT_EVENT_DATA",
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TEST",
    )


def catalog_request_classification(
    requested_action: str = "START_INFORMATION_FLOW",
) -> IntentClassification:
    return IntentClassification(
        primary_intent="GENERAL_INFORMATION",
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        information_category="catalogo",
        entities={},
        extracted_entities=[],
        requested_action=requested_action,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TEST_CATALOG",
    )


async def count_outbox(
    sessionmaker: async_sessionmaker[AsyncSession],
    message_kind: str | None = None,
) -> int:
    async with sessionmaker() as session:
        stmt = select(func.count()).select_from(Outbox)
        if message_kind is not None:
            stmt = stmt.where(Outbox.message_kind == message_kind)
        return await session.scalar(stmt) or 0


async def seed_document_outbox(
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    media_id: str | None = "media-cached",
    uploaded_at: datetime | None = None,
    file_exists: bool = True,
) -> tuple[int, UUID]:
    file_path = pdf_file(tmp_path) if file_exists else tmp_path / "missing.pdf"
    if file_exists:
        asset_id = await seed_catalog_asset(
            sessionmaker,
            file_path,
            media_id=media_id,
            media_uploaded_at=uploaded_at or datetime.now(UTC),
        )
    else:
        async with sessionmaker() as session:
            async with session.begin():
                asset = CatalogAsset(
                    name="Catálogo Bodas",
                    file_path=file_path.name,
                    file_hash="0" * 64,
                    mime_type="application/pdf",
                    file_size=10,
                    active=True,
                    version=1,
                )
                session.add(asset)
                await session.flush()
                asset_id = asset.catalog_asset_id
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker)
    async with sessionmaker() as session:
        async with session.begin():
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None
            customer = await session.get(Customer, conversation.customer_id)
            assert customer is not None
            outbox = Outbox(
                conversation_id=conversation.id,
                message_id=inbound_id,
                channel=Channel.WHATSAPP,
                recipient_phone_number=customer.phone_number,
                payload={"type": "document", "document": {"caption": "Catálogo"}},
                message_kind="DOCUMENT",
                catalog_asset_id=asset_id,
                status="PENDING",
            )
            session.add(outbox)
            await session.flush()
            return outbox.id, asset_id


@pytest.mark.asyncio
async def test_tc_cat_001_confirmed_event_type_enqueues_document_and_audit(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path), send_mode="PROACTIVE")
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture, conversation_id, inbound_id, classification_for_event_type()
    )

    async with sessionmaker_fixture() as session:
        outbox = await session.scalar(select(Outbox).where(Outbox.message_kind == "DOCUMENT"))
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "CATALOG_SEND_ENQUEUED")
        )
    assert outbox is not None
    assert outbox.catalog_asset_id is not None
    assert "catálogo" in outbox.payload["document"]["caption"]
    assert audit is not None


@pytest.mark.asyncio
async def test_tc_cat_002_inferred_event_type_does_not_enqueue_proactive_document(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path))
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        inbound_id,
        classification_for_event_type("INFERRED"),
    )

    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 0


@pytest.mark.asyncio
async def test_tc_cat_003_proactive_send_is_deduped_by_partial_unique_constraint(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    asset_id = await seed_catalog_asset(
        sessionmaker_fixture, pdf_file(tmp_path), send_mode="PROACTIVE"
    )
    conversation_id, lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture, conversation_id, inbound_id, classification_for_event_type()
    )
    second_inbound_id = await add_inbound_message(sessionmaker_fixture, conversation_id, "dup")
    await orchestrate(
        sessionmaker_fixture, conversation_id, second_inbound_id, classification_for_event_type()
    )

    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 1
    async with sessionmaker_fixture() as session:
        existing_outbox = await session.scalar(
            select(Outbox).where(Outbox.message_kind == "DOCUMENT")
        )
        assert existing_outbox is not None
        session.add(
            CatalogSend(
                lead_id=lead_id,
                catalog_asset_id=asset_id,
                trigger="PROACTIVE",
                outbound_message_id=existing_outbox.id,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_tc_cat_004_explicit_request_resends_after_proactive(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path), send_mode="PROACTIVE")
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture, conversation_id, inbound_id, classification_for_event_type()
    )
    request_inbound_id = await add_inbound_message(sessionmaker_fixture, conversation_id, "request")
    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        request_inbound_id,
        catalog_request_classification(),
        "envíame el catálogo",
    )

    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 2


@pytest.mark.asyncio
async def test_tc_cat_004b_explicit_request_sends_on_request_asset(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    asset_id = await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path))
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(
        sessionmaker_fixture, event_type="WEDDING"
    )

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        inbound_id,
        catalog_request_classification(),
        "envíame el catálogo",
    )

    async with sessionmaker_fixture() as session:
        outbox = await session.scalar(select(Outbox).where(Outbox.message_kind == "DOCUMENT"))
        catalog_send = await session.scalar(select(CatalogSend))
    assert outbox is not None
    assert outbox.catalog_asset_id == asset_id
    assert catalog_send is not None
    assert catalog_send.trigger == "EXPLICIT_REQUEST"


@pytest.mark.asyncio
async def test_tc_cat_005_explicit_request_without_event_type_asks_for_event_type(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        inbound_id,
        catalog_request_classification(),
        "¿tienen brochure?",
    )

    async with sessionmaker_fixture() as session:
        outbox = await session.scalar(select(Outbox))
    assert outbox is not None
    assert outbox.message_kind == "TEXT"
    assert "tipo de evento" in outbox.payload["text"]["body"]


@pytest.mark.asyncio
async def test_tc_cat_006_confirmed_event_type_without_mapping_is_audited_no_send(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture, conversation_id, inbound_id, classification_for_event_type()
    )

    async with sessionmaker_fixture() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "CATALOG_SEND_OMITTED")
        )
    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 0
    assert audit is not None


@pytest.mark.asyncio
async def test_tc_cat_007_worker_uses_valid_cached_media_without_upload(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_document_outbox(sessionmaker_fixture, tmp_path, media_id="media-cached")
    sender = FakeWhatsAppAdapter()

    processed = await process_outbox_once(sessionmaker_fixture, sender)

    assert processed == 1
    assert sender.upload_calls == 0
    assert sender.sent_documents[0]["media_id"] == "media-cached"


@pytest.mark.asyncio
async def test_tc_cat_008_worker_reuploads_expired_media_and_updates_cache(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    _outbox_id, asset_id = await seed_document_outbox(
        sessionmaker_fixture,
        tmp_path,
        media_id="media-old",
        uploaded_at=datetime.now(UTC) - timedelta(days=26),
    )
    sender = FakeWhatsAppAdapter()

    await process_outbox_once(sessionmaker_fixture, sender)

    async with sessionmaker_fixture() as session:
        asset = await session.get(CatalogAsset, asset_id)
    assert sender.upload_calls == 1
    assert sender.sent_documents[0]["media_id"] == "media-1"
    assert asset is not None
    assert asset.media_id == "media-1"


@pytest.mark.asyncio
async def test_tc_cat_009_invalid_media_gets_one_reupload_retry(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_document_outbox(sessionmaker_fixture, tmp_path, media_id="media-cached")
    sender = FakeWhatsAppAdapter(reject_first_document_media=True)

    await process_outbox_once(sessionmaker_fixture, sender)

    assert sender.document_calls == 2
    assert sender.upload_calls == 1
    assert sender.sent_documents[-1]["media_id"] == "media-1"


@pytest.mark.asyncio
async def test_tc_cat_010_missing_file_fails_permanently_without_worker_crash(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    outbox_id, _asset_id = await seed_document_outbox(
        sessionmaker_fixture, tmp_path, media_id=None, file_exists=False
    )
    sender = FakeWhatsAppAdapter()

    await process_outbox_once(sessionmaker_fixture, sender)

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "WHATSAPP_OUTBOX_SEND_FAILED")
        )
    assert outbox is not None
    assert outbox.status == "FAILED"
    assert outbox.attempts == 1
    assert audit is not None


@pytest.mark.asyncio
async def test_tc_cat_011_upload_failure_uses_standard_outbox_retry(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    outbox_id, asset_id = await seed_document_outbox(sessionmaker_fixture, tmp_path, media_id=None)
    sender = FakeWhatsAppAdapter(upload_error=TimeoutError("media timeout"))

    await process_outbox_once(sessionmaker_fixture, sender)

    async with sessionmaker_fixture() as session:
        outbox = await session.get(Outbox, outbox_id)
        asset = await session.get(CatalogAsset, asset_id)
    assert outbox is not None
    assert outbox.status == "PENDING"
    assert outbox.attempts == 1
    assert outbox.next_attempt_at is not None
    assert asset is not None
    assert asset.media_id is None


@pytest.mark.asyncio
async def test_tc_cat_012_two_workers_claim_same_document_once(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_document_outbox(sessionmaker_fixture, tmp_path, media_id="media-cached")
    sender = FakeWhatsAppAdapter(block_document_send=True)

    first_worker = asyncio.create_task(process_outbox_once(sessionmaker_fixture, sender))
    await sender.started.wait()
    second_processed = await process_outbox_once(sessionmaker_fixture, sender)
    sender.release.set()
    first_processed = await first_worker

    assert first_processed == 1
    assert second_processed == 0
    assert sender.document_calls == 1


@pytest.mark.asyncio
async def test_tc_cat_013_caption_over_limit_is_rejected_before_enqueue(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture, caption="x" * 1025)
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path), send_mode="PROACTIVE")
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture, conversation_id, inbound_id, classification_for_event_type()
    )

    async with sessionmaker_fixture() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "CATALOG_SEND_REJECTED")
        )
    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 0
    assert audit is not None


@pytest.mark.asyncio
async def test_tc_cat_014_inactive_asset_is_not_sent_and_is_audited(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path), active=False)
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture, conversation_id, inbound_id, classification_for_event_type()
    )

    async with sessionmaker_fixture() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "CATALOG_SEND_OMITTED")
        )
    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 0
    assert audit is not None


@pytest.mark.asyncio
async def test_tc_cat_015_admin_rejects_pdf_over_configured_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CATALOG_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("CATALOG_MAX_FILE_MB", "0")
    get_settings.cache_clear()
    await bootstrap_agent()
    pdf_file(tmp_path, size=1)

    async for client in app_client():
        headers = await login_headers(client)
        response = await client.post(
            "/admin/catalogs",
            headers=headers,
            json={
                "name": "Bodas",
                "file_path": "catalogo-bodas.pdf",
                "event_types": ["WEDDING"],
            },
        )
        break

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_tc_cat_016_admin_catalog_api_requires_valid_admin_session(
    client_fixture: AsyncClient,
) -> None:
    response = await client_fixture.get("/admin/catalogs")
    assert response.status_code == 401

    await bootstrap_agent(role="AGENT")
    headers = await login_headers(client_fixture)
    response = await client_fixture.get("/admin/catalogs", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tc_cat_017_incompatible_classifier_send_catalog_proposal_is_ignored(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path))
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)
    classification = IntentClassification(
        primary_intent="GREETING",
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        entities={},
        extracted_entities=[],
        requested_action="SEND_CATALOG",
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="INCOMPATIBLE",
    )

    await orchestrate(sessionmaker_fixture, conversation_id, inbound_id, classification)

    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 0


@pytest.mark.asyncio
async def test_tc_cat_018_missing_or_unapproved_caption_template_prevents_document_send(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path), send_mode="PROACTIVE")
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture, conversation_id, inbound_id, classification_for_event_type()
    )

    async with sessionmaker_fixture() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "CATALOG_SEND_REJECTED")
        )
    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 0
    assert audit is not None


@pytest.mark.asyncio
async def test_tc_cat_018b_unapproved_caption_rejects_document_and_sends_approved_fallback(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(catalog_service, "logger", logger)
    await approve_catalog_templates(
        sessionmaker_fixture,
        statuses={"RESP-CATALOG-001": "DRAFT", "RESP-CATALOG-003": "APPROVED"},
    )
    await seed_catalog_asset(sessionmaker_fixture, pdf_file(tmp_path), send_mode="PROACTIVE")
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(
        sessionmaker_fixture, event_type="WEDDING"
    )

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        inbound_id,
        catalog_request_classification(),
        "envíame el catálogo",
    )

    async with sessionmaker_fixture() as session:
        rejected = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "CATALOG_SEND_REJECTED")
        )
        text_outbox = await session.scalar(select(Outbox).where(Outbox.message_kind == "TEXT"))
    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 0
    assert rejected is not None
    assert text_outbox is not None
    assert "equipo te compartirá" in text_outbox.payload["text"]["body"]
    assert (
        "catalog_response_suppressed",
        {
            "conversation_id": conversation_id,
            "response_code": "RESP-CATALOG-001",
            "reason": "NOT_APPROVED",
            "request_id": "req-cat",
            "trigger": "EXPLICIT_REQUEST",
        },
    ) in logger.events


@pytest.mark.asyncio
async def test_tc_cat_018c_unrenderable_template_chain_creates_handoff_and_logs(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(catalog_service, "logger", logger)
    await approve_catalog_templates(
        sessionmaker_fixture,
        statuses={
            "RESP-CATALOG-001": "DRAFT",
            "RESP-CATALOG-002": "DRAFT",
            "RESP-CATALOG-003": "DRAFT",
        },
    )
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        inbound_id,
        catalog_request_classification(),
        "quiero información de planes románticos",
    )

    async with sessionmaker_fixture() as session:
        conversation = await session.get(Conversation, conversation_id)
        handoff = await session.scalar(
            select(Handoff).where(Handoff.conversation_id == conversation_id)
        )
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "CATALOG_HANDOFF_TEMPLATE_UNAVAILABLE"
            )
        )
    assert await count_outbox(sessionmaker_fixture) == 0
    assert conversation is not None
    assert conversation.state == ConversationState.WAITING_FOR_HUMAN.value
    assert handoff is not None
    assert handoff.status == "PENDING"
    assert handoff.priority == "NORMAL"
    assert handoff.reason == "TEMPLATE_UNAVAILABLE"
    assert "TEMPLATE_UNAVAILABLE" in handoff.summary
    assert "RESP-CATALOG-002" in handoff.summary
    assert audit is not None
    assert audit.new_value["reason"] == "TEMPLATE_UNAVAILABLE"
    assert any(
        event == "catalog_response_suppressed"
        and fields["conversation_id"] == conversation_id
        and fields["response_code"] == "RESP-CATALOG-003"
        and fields["reason"] == "NOT_APPROVED"
        and fields["request_id"] == "req-cat"
        for event, fields in logger.events
    )


@pytest.mark.asyncio
async def test_tc_cat_019_proactive_trigger_ignores_on_request_assets(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """TC-CAT-019: proactivo solo encola assets con send_mode=PROACTIVE."""
    await approve_catalog_templates(sessionmaker_fixture)
    await seed_catalog_asset(
        sessionmaker_fixture,
        pdf_file(tmp_path, "catalogo-proactivo.pdf"),
        send_mode="PROACTIVE",
    )
    for index in range(3):
        await seed_catalog_asset(
            sessionmaker_fixture,
            pdf_file(tmp_path, f"catalogo-on-request-{index}.pdf"),
            send_mode="ON_REQUEST",
        )
    conversation_id, _lead_id, _event_id, inbound_id = await seed_conversation(sessionmaker_fixture)

    await orchestrate(
        sessionmaker_fixture,
        conversation_id,
        inbound_id,
        classification_for_event_type(),
    )

    assert await count_outbox(sessionmaker_fixture, "DOCUMENT") == 1


@pytest.mark.asyncio
async def test_tc_cat_020_duplicate_catalog_webhook_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await approve_catalog_templates(sessionmaker_fixture)

    async def classify_catalog_request(
        self: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
    ) -> IntentClassification:
        return catalog_request_classification()

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_catalog_request)
    payload = json.loads(
        whatsapp_message_payload(
            "wamid.tc.cat.020",
            phone="573001117777",
            text="quiero el catálogo",
        ).decode()
    )

    await asyncio.gather(
        process_whatsapp_webhook(payload, sessionmaker_fixture, "req-cat-a"),
        process_whatsapp_webhook(payload, sessionmaker_fixture, "req-cat-b"),
    )

    async with sessionmaker_fixture() as session:
        message_count = await session.scalar(select(func.count()).select_from(Message))
        outbox_count = await session.scalar(select(func.count()).select_from(Outbox))
    assert message_count == 1
    assert outbox_count == 1


@pytest.mark.asyncio
async def test_tc_cat_021_admin_catalog_event_types_accept_send_mode_objects(
    client_fixture: AsyncClient,
    tmp_path: Path,
) -> None:
    await bootstrap_agent()
    headers = await login_headers(client_fixture)
    pdf_file(tmp_path, "catalogo-bodas.pdf")

    response = await client_fixture.post(
        "/admin/catalogs",
        headers=headers,
        json={
            "name": "Bodas",
            "file_path": "catalogo-bodas.pdf",
            "event_types": [{"event_type": "WEDDING", "send_mode": "PROACTIVE"}],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["event_types"] == ["WEDDING"]
    assert payload["event_type_mappings"] == [
        {"event_type": "WEDDING", "send_mode": "PROACTIVE"}
    ]

    replace_response = await client_fixture.put(
        f"/admin/catalogs/{payload['catalog_asset_id']}/event-types",
        headers=headers,
        json={
            "event_types": [
                "BIRTHDAY",
                {"event_type": "ROMANTIC_DINNER", "send_mode": "ON_REQUEST"},
            ]
        },
    )

    assert replace_response.status_code == 200, replace_response.text
    assert replace_response.json()["event_types"] == ["BIRTHDAY", "ROMANTIC_DINNER"]
    assert replace_response.json()["event_type_mappings"] == [
        {"event_type": "BIRTHDAY", "send_mode": "ON_REQUEST"},
        {"event_type": "ROMANTIC_DINNER", "send_mode": "ON_REQUEST"},
    ]


@pytest.mark.asyncio
async def test_tc_cat_022_admin_catalog_event_types_validate_send_mode_at_edge(
    client_fixture: AsyncClient,
    tmp_path: Path,
) -> None:
    await bootstrap_agent()
    headers = await login_headers(client_fixture)
    pdf_file(tmp_path, "catalogo-bodas.pdf")

    response = await client_fixture.post(
        "/admin/catalogs",
        headers=headers,
        json={
            "name": "Bodas",
            "file_path": "catalogo-bodas.pdf",
            "event_types": [{"event_type": "WEDDING", "send_mode": "BOTH"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {"invalid_send_modes": ["BOTH"]}


@pytest.mark.asyncio
async def test_tc_cat_023_admin_upload_stores_hash_named_pdf_and_maps_category(
    client_fixture: AsyncClient,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await bootstrap_agent()
    headers = await login_headers(client_fixture)
    content = b"%PDF-1.4\nadmin upload gender reveal"
    digest = hashlib.sha256(content).hexdigest()

    response = await client_fixture.post(
        "/admin/catalogs/upload",
        headers=headers,
        data={
            "name": "Revelación de género",
            "event_type": "GENDER_REVEAL",
            "send_mode": "ON_REQUEST",
        },
        files={"file": ("catalogo original.pdf", content, "application/pdf")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    expected_name = f"{digest[:16]}.pdf"
    assert payload["file_path"] == expected_name
    assert payload["file_hash"] == digest
    assert payload["event_types"] == ["GENDER_REVEAL"]
    assert payload["event_type_mappings"] == [
        {"event_type": "GENDER_REVEAL", "send_mode": "ON_REQUEST"}
    ]
    assert tmp_path.joinpath(expected_name).read_bytes() == content
    async with sessionmaker_fixture() as session:
        asset_count = await session.scalar(select(func.count()).select_from(CatalogAsset))
        mapping_count = await session.scalar(
            select(func.count())
            .select_from(CatalogEventTypeMap)
            .where(CatalogEventTypeMap.event_type == "GENDER_REVEAL")
        )
    assert asset_count == 1
    assert mapping_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "mime_type"),
    [
        ("catalogo.txt", b"not a pdf", "text/plain"),
        ("catalogo.pdf", b"not a pdf", "application/pdf"),
        ("../escape.pdf", b"%PDF-1.4\nvalid", "application/pdf"),
    ],
)
async def test_tc_cat_024_admin_upload_rejects_non_pdf_and_traversal_filename(
    client_fixture: AsyncClient,
    tmp_path: Path,
    filename: str,
    content: bytes,
    mime_type: str,
) -> None:
    await bootstrap_agent()
    headers = await login_headers(client_fixture)

    response = await client_fixture.post(
        "/admin/catalogs/upload",
        headers=headers,
        data={"name": "Inválido", "event_type": "WEDDING", "send_mode": "ON_REQUEST"},
        files={"file": (filename, content, mime_type)},
    )

    assert response.status_code == 422
    assert list(tmp_path.glob("*.pdf")) == []


@pytest.mark.asyncio
async def test_tc_cat_025_admin_upload_rejects_configured_oversize(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CATALOG_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("CATALOG_MAX_FILE_MB", "0")
    get_settings.cache_clear()
    await bootstrap_agent()

    async for client in app_client():
        headers = await login_headers(client)
        response = await client.post(
            "/admin/catalogs/upload",
            headers=headers,
            data={"name": "Grande", "event_type": "WEDDING", "send_mode": "ON_REQUEST"},
            files={"file": ("grande.pdf", b"%PDF-1.4\nx", "application/pdf")},
        )
        break

    assert response.status_code == 422
    assert list(tmp_path.glob("*.pdf")) == []


@pytest.mark.asyncio
async def test_tc_cat_026_admin_upload_validation_leaves_no_orphan_file(
    client_fixture: AsyncClient, tmp_path: Path
) -> None:
    await bootstrap_agent()
    headers = await login_headers(client_fixture)

    response = await client_fixture.post(
        "/admin/catalogs/upload",
        headers=headers,
        data={"name": "Inválido", "event_type": "NOT_AN_EVENT", "send_mode": "ON_REQUEST"},
        files={"file": ("valido.pdf", b"%PDF-1.4\nvalid", "application/pdf")},
    )

    assert response.status_code == 422
    assert list(tmp_path.glob("*.pdf")) == []


@pytest.mark.asyncio
async def test_tc_cat_027_admin_category_listing_has_all_17_and_correct_coverage(
    client_fixture: AsyncClient,
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await bootstrap_agent()
    headers = await login_headers(client_fixture)
    await seed_catalog_asset(
        sessionmaker_fixture, pdf_file(tmp_path, "bodas.pdf"), event_type="WEDDING"
    )
    await seed_catalog_asset(
        sessionmaker_fixture,
        pdf_file(tmp_path, "cumpleanos.pdf"),
        event_type="BIRTHDAY",
        active=False,
    )

    response = await client_fixture.get("/admin/catalogs/categories", headers=headers)

    assert response.status_code == 200, response.text
    categories = response.json()
    assert len(categories) == 17
    assert {item["event_type"] for item in categories} == {
        "WEDDING",
        "CIVIL_WEDDING",
        "PROPOSAL",
        "BIRTHDAY",
        "GRADUATION",
        "ANNIVERSARY",
        "ROMANTIC_DINNER",
        "CORPORATE_EVENT",
        "FAMILY_EVENT",
        "BAPTISM",
        "FIRST_COMMUNION",
        "BABY_SHOWER",
        "WORKSHOP",
        "POOL_DAY",
        "PRIVATE_DINNER",
        "GENDER_REVEAL",
        "OTHER",
    }
    by_type = {item["event_type"]: item for item in categories}
    assert by_type["WEDDING"]["covered"] is True
    assert by_type["WEDDING"]["active_catalog_count"] == 1
    assert len(by_type["WEDDING"]["catalogs"]) == 1
    assert by_type["BIRTHDAY"]["covered"] is False
    assert by_type["BIRTHDAY"]["active_catalog_count"] == 0
    assert len(by_type["BIRTHDAY"]["catalogs"]) == 1
    assert by_type["BIRTHDAY"]["catalogs"][0]["active"] is False
    assert by_type["GENDER_REVEAL"]["covered"] is False
    assert by_type["GENDER_REVEAL"]["catalogs"] == []

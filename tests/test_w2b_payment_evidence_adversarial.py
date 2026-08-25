from __future__ import annotations

import base64
import hashlib
import importlib
import json
import stat
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import CheckConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.client import OpenRouterIntentClient
from app.ai.models import AIExecution
from app.ai.schemas import IntentClassification
from app.audit.models import AuditEvent
from app.channel.inbound import process_whatsapp_webhook
from app.channel.media import InboundMediaFile, InboundMediaHashMismatch
from app.channel.models import Message, Outbox
from app.config.settings import Settings, get_settings
from app.conversation.models import Conversation, KnowledgeEntry
from app.customer.models import Customer
from app.handoff.models import Handoff
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    DATABASE_URL,
    app_client,
    bootstrap_agent,
    configure_test_environment,
    login_headers,
    reset_test_database,
)

PHONE = "573001112233"
NORMALIZED_PHONE = "+573001112233"
GRAPH_BASE = "https://graph.facebook.com"
JPEG_BYTES = b"payment evidence jpeg"
JPEG_SHA256 = base64.b64encode(hashlib.sha256(JPEG_BYTES).digest()).decode()


class ClassifierCalls:
    def __init__(self) -> None:
        self.messages: list[str] = []


def payment_model() -> type:
    try:
        module = importlib.import_module("app.payment.models")
    except ModuleNotFoundError:
        module = None
    model = getattr(module, "PaymentEvidence", None)
    assert isinstance(model, type), "PaymentEvidence model contract is missing"
    return model


def payment_service() -> Any:
    try:
        module = importlib.import_module("app.payment.service")
    except ModuleNotFoundError:
        module = None
    assert module is not None, "payment evidence service contract is missing"
    return module


def payment_worker() -> Any:
    try:
        module = importlib.import_module("app.payment.worker")
    except ModuleNotFoundError:
        module = None
    assert module is not None, "payment evidence worker contract is missing"
    assert callable(getattr(module, "process_payment_evidence_once", None))
    return module


@pytest.fixture
async def payment_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], ClassifierCalls]]:
    await configure_test_environment(monkeypatch)
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    calls = ClassifierCalls()

    async def classify_intent(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> IntentClassification:
        del context, conversation_id
        calls.messages.append(message_text)
        return classification("GREETING", needs_human=False, handoff_reason=None)

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_intent)
    yield sessionmaker, calls
    get_settings.cache_clear()


@pytest.fixture
async def payment_http_context(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], ClassifierCalls, httpx.AsyncClient]
]:
    sessionmaker, calls = payment_context
    async for client in app_client():
        yield sessionmaker, calls, client


def classification(
    intent: str,
    *,
    needs_human: bool,
    handoff_reason: str | None,
) -> IntentClassification:
    return IntentClassification(
        primary_intent=intent,
        secondary_intents=[],
        sub_intent=None,
        confidence=0.98,
        information_category=None,
        entities={},
        extracted_entities=[],
        requested_action=None,
        missing_fields=[],
        needs_confirmation=False,
        needs_human=needs_human,
        handoff_reason=handoff_reason,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TC_PAYMENT_EVIDENCE",
    )


def webhook_payload(
    message_id: str,
    message_type: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "from": PHONE,
                                    "id": message_id,
                                    "timestamp": "1787366893",
                                    "type": message_type,
                                    message_type: content,
                                }
                            ]
                        },
                    }
                ],
            }
        ],
    }


def image_content(media_id: str, caption: str | None = None) -> dict[str, Any]:
    content: dict[str, Any] = {
        "id": media_id,
        "mime_type": "image/jpeg",
        "sha256": JPEG_SHA256,
    }
    if caption is not None:
        content["caption"] = caption
    return content


async def seed_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    payment_handoff: bool = False,
) -> tuple[int, int]:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=NORMALIZED_PHONE, full_name="Cliente Pago")
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel="WHATSAPP",
                state="WAITING_FOR_HUMAN" if payment_handoff else "BOT_ACTIVE",
                pending_action="WAIT_FOR_HUMAN" if payment_handoff else None,
            )
            session.add(conversation)
            await session.flush()
            if payment_handoff:
                session.add(
                    Handoff(
                        conversation_id=conversation.id,
                        status="PENDING",
                        reason="PAYMENT_REVIEW",
                        priority="NORMAL",
                        summary="Pago pendiente de revisión",
                    )
                )
            return conversation.id, customer.id


async def evidence_rows(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[Any]:
    model = payment_model()
    async with sessionmaker() as session:
        return list((await session.scalars(select(model).order_by(model.id))).all())


async def audit_actions(sessionmaker: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessionmaker() as session:
        return list(
            (await session.scalars(select(AuditEvent.action).order_by(AuditEvent.id))).all()
        )


async def seed_evidence(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    media_id: str = "evidence-media",
    mime_type: str = "image/jpeg",
    attempts: int = 0,
    created_at: datetime | None = None,
    download_status: str = "PENDING",
    storage_path: str | None = None,
) -> Any:
    model = payment_model()
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=f"+57300{media_id[-7:]:0>7}")
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel="WHATSAPP",
                state="WAITING_FOR_HUMAN",
                pending_action="WAIT_FOR_HUMAN",
            )
            session.add(conversation)
            await session.flush()
            message = Message(
                external_message_id=f"wamid.{media_id}",
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel="WHATSAPP",
                direction="INBOUND",
                message_type="image",
                content={
                    "image": {
                        "media_id": media_id,
                        "mime_type": mime_type,
                        "sha256": JPEG_SHA256,
                    }
                },
            )
            session.add(message)
            await session.flush()
            evidence = model(
                conversation_id=conversation.id,
                customer_id=customer.id,
                message_id=message.id,
                media_id=media_id,
                mime_type=mime_type,
                declared_sha256=JPEG_SHA256,
                storage_path=storage_path,
                download_status=download_status,
                download_attempts=attempts,
                review_status="PENDING_REVIEW",
                created_at=created_at or datetime.now(UTC),
            )
            session.add(evidence)
            await session.flush()
            evidence_id = evidence.id
    async with sessionmaker() as session:
        return await session.get(model, evidence_id)


def worker_settings(tmp_path: Path) -> Settings:
    return Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-access-token",
        META_GRAPH_API_VERSION="v20.0",
        WHATSAPP_API_BASE_URL=GRAPH_BASE,
        OPENROUTER_API_KEY="test-openrouter-key",
        ENVIRONMENT="testing",
        PAYMENT_EVIDENCE_DIR=str(tmp_path),
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_tc_pay_001_no_caption_in_payment_context_creates_evidence_and_raises_priority(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    model = payment_model()
    sessionmaker, calls = payment_context
    await seed_conversation(sessionmaker, payment_handoff=True)
    await process_whatsapp_webhook(
        webhook_payload("wamid.pay.001", "image", image_content("media-pay-001")),
        sessionmaker,
    )

    rows = await evidence_rows(sessionmaker)
    async with sessionmaker() as session:
        message = await session.scalar(select(Message))
        handoff = await session.scalar(select(Handoff))
        ai_count = await session.scalar(select(func.count()).select_from(AIExecution))
        conversation = await session.scalar(select(Conversation))
    assert model.__tablename__ == "payment_evidence"
    assert len(rows) == 1
    assert rows[0].message_id == message.id
    assert rows[0].media_id == "media-pay-001"
    assert rows[0].download_status == "PENDING"
    assert rows[0].review_status == "PENDING_REVIEW"
    assert handoff.priority == "URGENT"
    assert conversation.last_question_code == "RESP-PAYMENT-002"
    assert calls.messages == [] and ai_count == 0
    assert {"HANDOFF_PRIORITY_RAISED", "NON_TEXT_MESSAGE_RECEIVED"} <= set(
        await audit_actions(sessionmaker)
    )


@pytest.mark.asyncio
async def test_tc_pay_002_caption_payment_creates_urgent_handoff_then_evidence(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_model()
    sessionmaker, calls = payment_context

    async def classify_payment(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> IntentClassification:
        del context, conversation_id
        calls.messages.append(message_text)
        return classification(
            "PAYMENT_MESSAGE", needs_human=True, handoff_reason="PAYMENT_REVIEW"
        )

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_payment)
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.pay.002",
            "image",
            image_content("media-pay-002", caption="pago de la reserva"),
        ),
        sessionmaker,
    )

    rows = await evidence_rows(sessionmaker)
    async with sessionmaker() as session:
        handoff = await session.scalar(select(Handoff))
    assert calls.messages == ["pago de la reserva"]
    assert len(rows) == 1
    assert handoff.reason == "PAYMENT_REVIEW"
    assert handoff.priority == "URGENT"
    assert f"evidencia #{rows[0].id}" in handoff.summary


@pytest.mark.asyncio
async def test_tc_pay_003_no_caption_without_payment_context_creates_no_evidence(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    payment_model()
    sessionmaker, _calls = payment_context
    await process_whatsapp_webhook(
        webhook_payload("wamid.pay.003", "image", image_content("media-pay-003")),
        sessionmaker,
    )
    async with sessionmaker() as session:
        conversation = await session.scalar(select(Conversation))
    assert await evidence_rows(sessionmaker) == []
    assert conversation.last_question_code == "RESP-FILE-001"


@pytest.mark.asyncio
async def test_tc_pay_004_duplicate_webhook_is_idempotent_for_all_payment_rows(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    payment_model()
    sessionmaker, _calls = payment_context
    await seed_conversation(sessionmaker, payment_handoff=True)
    payload = webhook_payload("wamid.pay.004", "image", image_content("media-pay-004"))
    await process_whatsapp_webhook(payload, sessionmaker)
    first = (
        len(await evidence_rows(sessionmaker)),
        len(await audit_actions(sessionmaker)),
    )
    await process_whatsapp_webhook(payload, sessionmaker)
    second = (
        len(await evidence_rows(sessionmaker)),
        len(await audit_actions(sessionmaker)),
    )
    async with sessionmaker() as session:
        handoff_count = await session.scalar(select(func.count()).select_from(Handoff))
    assert second == first
    assert handoff_count == 1


@pytest.mark.asyncio
async def test_tc_pay_005_two_images_create_two_evidences_and_raise_once(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    payment_model()
    sessionmaker, _calls = payment_context
    await seed_conversation(sessionmaker, payment_handoff=True)
    for suffix in ("a", "b"):
        await process_whatsapp_webhook(
            webhook_payload(
                f"wamid.pay.005.{suffix}",
                "image",
                image_content(f"media-pay-005-{suffix}"),
            ),
            sessionmaker,
        )
    async with sessionmaker() as session:
        handoffs = list((await session.scalars(select(Handoff))).all())
        raised = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "HANDOFF_PRIORITY_RAISED")
        )
    assert len(await evidence_rows(sessionmaker)) == 2
    assert len(handoffs) == 1 and handoffs[0].priority == "URGENT"
    assert raised == 1


@pytest.mark.asyncio
async def test_tc_pay_006_audio_in_payment_context_is_not_evidence(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    payment_model()
    sessionmaker, calls = payment_context
    await seed_conversation(sessionmaker, payment_handoff=True)
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.pay.006",
            "audio",
            {
                "id": "audio-pay-006",
                "mime_type": "audio/ogg; codecs=opus",
                "sha256": "hash",
                "voice": True,
            },
        ),
        sessionmaker,
    )
    async with sessionmaker() as session:
        conversation = await session.scalar(select(Conversation))
    assert await evidence_rows(sessionmaker) == []
    assert conversation.last_question_code == "RESP-FILE-003"
    assert calls.messages == []


class TrackingSessionmaker:
    def __init__(self, wrapped: async_sessionmaker[AsyncSession]) -> None:
        self.wrapped = wrapped
        self.active_sessions = 0

    def __call__(self) -> Any:
        tracker = self
        inner = self.wrapped()

        class Context:
            async def __aenter__(self) -> AsyncSession:
                tracker.active_sessions += 1
                return await inner.__aenter__()

            async def __aexit__(self, *args: object) -> None:
                try:
                    await inner.__aexit__(*args)
                finally:
                    tracker.active_sessions -= 1

        return Context()


@pytest.mark.asyncio
@respx.mock
async def test_tc_pay_007_worker_downloads_outside_db_and_writes_private_file(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    tmp_path: Path,
) -> None:
    module = payment_worker()
    sessionmaker, _calls = payment_context
    evidence = await seed_evidence(sessionmaker, media_id="media-pay-007")
    tracker = TrackingSessionmaker(sessionmaker)
    fresh_url = "https://lookaside.fbsbx.com/payment-007"

    def metadata(_request: httpx.Request) -> httpx.Response:
        assert tracker.active_sessions == 0
        return httpx.Response(
            200,
            json={
                "id": "media-pay-007",
                "url": fresh_url,
                "mime_type": "image/jpeg",
                "sha256": JPEG_SHA256,
                "file_size": len(JPEG_BYTES),
            },
        )

    respx.get(f"{GRAPH_BASE}/v20.0/media-pay-007").mock(side_effect=metadata)
    respx.get(fresh_url).mock(return_value=httpx.Response(200, content=JPEG_BYTES))
    async with httpx.AsyncClient() as http_client:
        await module.process_payment_evidence_once(
            tracker,
            settings=worker_settings(tmp_path),
            http_client=http_client,
            now=datetime.now(UTC),
        )

    rows = await evidence_rows(sessionmaker)
    stored = tmp_path / f"{evidence.id}.jpg"
    assert rows[0].download_status == "DOWNLOADED"
    assert rows[0].verified_sha256 == JPEG_SHA256
    assert rows[0].size_bytes == len(JPEG_BYTES)
    assert stored.read_bytes() == JPEG_BYTES
    assert stat.S_IMODE(stored.stat().st_mode) == 0o640
    async with sessionmaker() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "PAYMENT_EVIDENCE_DOWNLOADED")
        )
    assert "storage_path" not in json.dumps(audit.new_value)


@pytest.mark.asyncio
@respx.mock
async def test_tc_pay_008_http_500_schedules_retry_with_backoff(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    tmp_path: Path,
) -> None:
    module = payment_worker()
    sessionmaker, _calls = payment_context
    await seed_evidence(sessionmaker, media_id="media-pay-008")
    respx.get(f"{GRAPH_BASE}/v20.0/media-pay-008").mock(
        return_value=httpx.Response(500)
    )
    now = datetime.now(UTC)
    async with httpx.AsyncClient() as http_client:
        await module.process_payment_evidence_once(
            sessionmaker,
            settings=worker_settings(tmp_path),
            http_client=http_client,
            now=now,
        )
    row = (await evidence_rows(sessionmaker))[0]
    assert row.download_status == "FAILED_RETRYABLE"
    assert row.download_attempts == 1
    assert row.next_attempt_at == now + timedelta(seconds=2)
    assert "PAYMENT_EVIDENCE_DOWNLOAD_FAILED" in await audit_actions(sessionmaker)


@pytest.mark.asyncio
async def test_tc_pay_009_hash_mismatch_is_permanent_and_leaves_no_partial_file(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = payment_worker()
    sessionmaker, _calls = payment_context
    evidence = await seed_evidence(sessionmaker, media_id="media-pay-009")

    async def mismatch(*_args: object, **_kwargs: object) -> InboundMediaFile:
        raise InboundMediaHashMismatch("mismatch")

    monkeypatch.setattr(module, "download_inbound_media", mismatch)
    await module.process_payment_evidence_once(
        sessionmaker,
        settings=worker_settings(tmp_path),
        http_client=httpx.AsyncClient(),
        now=datetime.now(UTC),
    )
    row = (await evidence_rows(sessionmaker))[0]
    assert row.download_status == "FAILED_PERMANENT"
    assert not list(tmp_path.glob(f"{evidence.id}.*"))


@pytest.mark.asyncio
@respx.mock
async def test_tc_pay_010_sixth_failed_attempt_is_permanent(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    tmp_path: Path,
) -> None:
    module = payment_worker()
    sessionmaker, _calls = payment_context
    await seed_evidence(sessionmaker, media_id="media-pay-010", attempts=5)
    respx.get(f"{GRAPH_BASE}/v20.0/media-pay-010").mock(
        return_value=httpx.Response(500)
    )
    async with httpx.AsyncClient() as http_client:
        await module.process_payment_evidence_once(
            sessionmaker,
            settings=worker_settings(tmp_path),
            http_client=http_client,
            now=datetime.now(UTC),
        )
    row = (await evidence_rows(sessionmaker))[0]
    assert row.download_attempts == 6
    assert row.download_status == "FAILED_PERMANENT"


@pytest.mark.asyncio
async def test_tc_pay_011_evidence_older_than_six_days_never_calls_meta(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = payment_worker()
    sessionmaker, _calls = payment_context
    now = datetime.now(UTC)
    await seed_evidence(
        sessionmaker,
        media_id="media-pay-011",
        created_at=now - timedelta(days=6, seconds=1),
    )

    async def forbidden(*_args: object, **_kwargs: object) -> InboundMediaFile:
        pytest.fail("expired evidence must not call Meta")

    monkeypatch.setattr(module, "download_inbound_media", forbidden)
    await module.process_payment_evidence_once(
        sessionmaker,
        settings=worker_settings(tmp_path),
        http_client=httpx.AsyncClient(),
        now=now,
    )
    assert (await evidence_rows(sessionmaker))[0].download_status == "FAILED_PERMANENT"


@pytest.mark.asyncio
async def test_tc_pay_012_non_whitelisted_mime_is_permanent_without_download(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = payment_worker()
    sessionmaker, _calls = payment_context
    await seed_evidence(
        sessionmaker,
        media_id="media-pay-012",
        mime_type="image/gif",
    )

    async def forbidden(*_args: object, **_kwargs: object) -> InboundMediaFile:
        pytest.fail("unsupported MIME must not be downloaded")

    monkeypatch.setattr(module, "download_inbound_media", forbidden)
    await module.process_payment_evidence_once(
        sessionmaker,
        settings=worker_settings(tmp_path),
        http_client=httpx.AsyncClient(),
        now=datetime.now(UTC),
    )
    assert (await evidence_rows(sessionmaker))[0].download_status == "FAILED_PERMANENT"


@pytest.mark.asyncio
async def test_tc_pay_013_historical_content_id_is_accepted_as_media_id(
    payment_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    module = payment_service()
    model = payment_model()
    sessionmaker, _calls = payment_context
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=NORMALIZED_PHONE)
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel="WHATSAPP",
                state="WAITING_FOR_HUMAN",
                pending_action="WAIT_FOR_HUMAN",
            )
            session.add(conversation)
            await session.flush()
            handoff = Handoff(
                conversation_id=conversation.id,
                status="PENDING",
                reason="PAYMENT_REVIEW",
                priority="NORMAL",
                summary="Pago",
            )
            message = Message(
                external_message_id="wamid.pay.013",
                conversation_id=conversation.id,
                customer_id=customer.id,
                channel="WHATSAPP",
                direction="INBOUND",
                message_type="image",
                content={
                    "image": {
                        "id": "historical-media-id",
                        "mime_type": "image/jpeg",
                        "sha256": JPEG_SHA256,
                    }
                },
            )
            session.add_all([handoff, message])
            await session.flush()
            evidence = await module.create_payment_evidence(
                session,
                conversation,
                customer,
                message,
                handoff,
                request_id=None,
            )
    assert isinstance(evidence, model)
    assert evidence.media_id == "historical-media-id"


async def admin_seed(
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    downloaded: bool = False,
) -> Any:
    evidence = await seed_evidence(
        sessionmaker,
        media_id=f"admin-{datetime.now(UTC).timestamp()}",
        download_status="DOWNLOADED" if downloaded else "PENDING",
    )
    if downloaded:
        path = tmp_path / f"{evidence.id}.jpg"
        path.write_bytes(JPEG_BYTES)
        path.chmod(0o640)
        model = payment_model()
        async with sessionmaker() as session:
            async with session.begin():
                row = await session.get(model, evidence.id)
                row.storage_path = str(path)
                row.verified_sha256 = JPEG_SHA256
                row.size_bytes = len(JPEG_BYTES)
    return evidence


@pytest.mark.asyncio
async def test_tc_pay_014_admin_list_requires_admin_and_only_pending_review(
    payment_http_context: tuple[
        async_sessionmaker[AsyncSession],
        ClassifierCalls,
        httpx.AsyncClient,
    ],
    tmp_path: Path,
) -> None:
    payment_model()
    sessionmaker, _calls, client = payment_http_context
    pending = await admin_seed(sessionmaker, tmp_path)
    accepted = await admin_seed(sessionmaker, tmp_path)
    model = payment_model()
    async with sessionmaker() as session:
        async with session.begin():
            row = await session.get(model, accepted.id)
            row.review_status = "ACCEPTED"
    await bootstrap_agent("Agente Pago", "agent-pay", role="AGENT")
    agent_headers = await login_headers(client, "agent-pay")
    await bootstrap_agent("Admin Pago", "admin-pay", role="ADMIN")
    admin_headers = await login_headers(client, "admin-pay")

    assert (await client.get("/admin/payment-evidence")).status_code == 401
    assert (
        await client.get("/admin/payment-evidence", headers=agent_headers)
    ).status_code == 403
    response = await client.get("/admin/payment-evidence", headers=admin_headers)
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [pending.id]


@pytest.mark.asyncio
async def test_tc_pay_015_admin_download_serves_file_and_rejects_failed_evidence(
    payment_http_context: tuple[
        async_sessionmaker[AsyncSession],
        ClassifierCalls,
        httpx.AsyncClient,
    ],
    tmp_path: Path,
) -> None:
    payment_model()
    sessionmaker, _calls, client = payment_http_context
    downloaded = await admin_seed(sessionmaker, tmp_path, downloaded=True)
    failed = await admin_seed(sessionmaker, tmp_path)
    model = payment_model()
    async with sessionmaker() as session:
        async with session.begin():
            row = await session.get(model, failed.id)
            row.download_status = "FAILED_PERMANENT"
    await bootstrap_agent("Admin Descarga", "admin-download", role="ADMIN")
    headers = await login_headers(client, "admin-download")

    response = await client.get(
        f"/admin/payment-evidence/{downloaded.id}/download", headers=headers
    )
    assert response.status_code == 200
    assert response.content == JPEG_BYTES
    assert response.headers["content-type"].startswith("image/jpeg")
    assert (
        await client.get(f"/admin/payment-evidence/{failed.id}/download", headers=headers)
    ).status_code == 409


@pytest.mark.asyncio
async def test_tc_pay_016_review_transition_is_one_way_and_audited(
    payment_http_context: tuple[
        async_sessionmaker[AsyncSession],
        ClassifierCalls,
        httpx.AsyncClient,
    ],
    tmp_path: Path,
) -> None:
    model = payment_model()
    sessionmaker, _calls, client = payment_http_context
    accepted = await admin_seed(sessionmaker, tmp_path)
    rejected = await admin_seed(sessionmaker, tmp_path)
    await bootstrap_agent("Admin Revisión", "admin-review", role="ADMIN")
    headers = await login_headers(client, "admin-review")

    first = await client.post(
        f"/admin/payment-evidence/{accepted.id}/accept",
        json={"note": "Validado manualmente"},
        headers=headers,
    )
    second = await client.post(
        f"/admin/payment-evidence/{accepted.id}/accept",
        json={"note": "Duplicado"},
        headers=headers,
    )
    rejection = await client.post(
        f"/admin/payment-evidence/{rejected.id}/reject",
        json={"note": "Referencia ilegible"},
        headers=headers,
    )
    async with sessionmaker() as session:
        accepted_row = await session.get(model, accepted.id)
        rejected_row = await session.get(model, rejected.id)
        audits = list(
            (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "PAYMENT_EVIDENCE_REVIEWED"
                    )
                )
            ).all()
        )
    assert first.status_code == 200 and second.status_code == 409
    assert rejection.status_code == 200
    assert accepted_row.review_status == "ACCEPTED"
    assert accepted_row.reviewed_by_agent_id is not None
    assert rejected_row.review_status == "REJECTED"
    assert rejected_row.review_note == "Referencia ilegible"
    assert len(audits) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("template_status", ["DRAFT", "APPROVED"])
async def test_tc_pay_017_customer_notification_tracks_seed_approval(
    payment_http_context: tuple[
        async_sessionmaker[AsyncSession],
        ClassifierCalls,
        httpx.AsyncClient,
    ],
    tmp_path: Path,
    template_status: str,
) -> None:
    payment_model()
    sessionmaker, _calls, client = payment_http_context
    evidence = await admin_seed(sessionmaker, tmp_path)
    async with sessionmaker() as session:
        async with session.begin():
            entry = await session.scalar(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.code == "RESP-PAYMENT-004",
                    KnowledgeEntry.status.in_(("DRAFT", "APPROVED")),
                )
            )
            entry.status = template_status
    await bootstrap_agent(
        f"Admin Notificación {template_status}",
        f"admin-notify-{template_status.lower()}",
        role="ADMIN",
    )
    headers = await login_headers(client, f"admin-notify-{template_status.lower()}")
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        json={"note": "Revisión humana"},
        headers=headers,
    )
    async with sessionmaker() as session:
        outbox_count = await session.scalar(select(func.count()).select_from(Outbox))
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "PAYMENT_EVIDENCE_REVIEWED")
        )
    assert response.status_code == 200
    assert outbox_count == (1 if template_status == "APPROVED" else 0)
    expected = "ENQUEUED" if template_status == "APPROVED" else "DEFERRED"
    assert audit.new_value["customer_notification"] == expected


def test_tc_pay_018_model_and_migration_status_checks_are_in_parity() -> None:
    model = payment_model()
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260825_0024_payment_evidence.py"
    )
    assert migration.exists(), "payment evidence migration 0024 is missing"
    migration_text = migration.read_text(encoding="utf-8")
    model_checks = " ".join(
        str(item.sqltext)
        for item in model.__table__.constraints
        if isinstance(item, CheckConstraint)
    )
    for value in ("PENDING", "DOWNLOADED", "FAILED_RETRYABLE", "FAILED_PERMANENT"):
        assert value in model_checks and value in migration_text
    for value in ("PENDING_REVIEW", "ACCEPTED", "REJECTED"):
        assert value in model_checks and value in migration_text

from __future__ import annotations

import base64
import hashlib
import importlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai import errors as ai_errors
from app.ai.client import OpenRouterIntentClient
from app.ai.models import AIExecution
from app.ai.schemas import IntentClassification
from app.audit.models import AuditEvent
from app.channel import media as media_module
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Message, Outbox
from app.config.settings import Settings, get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import (
    DATABASE_URL,
    configure_test_environment,
    reset_test_database,
)

PHONE = "573001112233"
NORMALIZED_PHONE = "+573001112233"
GRAPH_BASE = "https://graph.facebook.com"

AUDIO_ONE = {
    "id": "1019433874424562",
    "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1019433874424562",
    "voice": True,
    "sha256": "zc3KEenfPxenEtfmKnSbUHARsFAKboIj4bJXaEfBudw=",
    "mime_type": "audio/ogg; codecs=opus",
}
AUDIO_TWO = {
    "id": "2155110562068122",
    "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=2155110562068122",
    "voice": True,
    "sha256": "X8JnuJJYPkWHI2XiHV8VISoh9LshiRcx5C0jjpJBd58=",
    "mime_type": "audio/ogg; codecs=opus",
}
AUDIO_THREE = {
    "id": "1655954096140917",
    "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1655954096140917",
    "voice": False,
    "sha256": "a+L+h90LLgHe0XR7hbnFGnS4vrrqyr47QMN4idegZpc=",
    "mime_type": "audio/ogg; codecs=opus",
}


@dataclass
class ClassifierCalls:
    general: list[str]
    services: list[str]


@dataclass
class Snapshot:
    messages: list[Message]
    outbox: list[Outbox]
    audits: list[AuditEvent]
    handoffs: list[Handoff]
    ai_execution_count: int
    conversation: Conversation


@pytest.fixture
async def media_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], ClassifierCalls]]:
    await configure_test_environment(monkeypatch)
    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    calls = ClassifierCalls(general=[], services=[])

    async def classify_intent(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> IntentClassification:
        del context, conversation_id
        calls.general.append(message_text)
        return greeting_classification()

    async def classify_services(
        _client: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
        **_kwargs: object,
    ) -> list[str]:
        del context, conversation_id
        calls.services.append(message_text)
        return []

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_intent)
    monkeypatch.setattr(OpenRouterIntentClient, "classify_services", classify_services)
    yield sessionmaker, calls
    get_settings.cache_clear()


def greeting_classification() -> IntentClassification:
    return IntentClassification(
        primary_intent="GREETING",
        secondary_intents=[],
        sub_intent=None,
        confidence=0.95,
        information_category=None,
        entities={},
        extracted_entities=[],
        requested_action="SEND_GREETING",
        missing_fields=[],
        needs_confirmation=False,
        needs_human=False,
        handoff_reason=None,
        priority="NORMAL",
        context_reference={},
        reasoning_code="TC_MEDIA_TEXT",
    )


def webhook_payload(
    message_id: str,
    message_type: str,
    content: Any,
    *,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "from": PHONE,
        "id": message_id,
        "timestamp": "1787366893",
        "type": message_type,
        message_type: content,
    }
    if errors is not None:
        message["errors"] = errors
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "123456789",
                            },
                            "contacts": [
                                {"profile": {"name": "Cliente"}, "wa_id": PHONE}
                            ],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


async def snapshot(sessionmaker: async_sessionmaker[AsyncSession]) -> Snapshot:
    async with sessionmaker() as session:
        messages = list((await session.scalars(select(Message).order_by(Message.id))).all())
        outbox = list((await session.scalars(select(Outbox).order_by(Outbox.id))).all())
        audits = list((await session.scalars(select(AuditEvent).order_by(AuditEvent.id))).all())
        handoffs = list((await session.scalars(select(Handoff).order_by(Handoff.id))).all())
        ai_count = await session.scalar(select(func.count()).select_from(AIExecution)) or 0
        conversation = await session.scalar(select(Conversation).order_by(Conversation.id))
    assert conversation is not None
    return Snapshot(messages, outbox, audits, handoffs, ai_count, conversation)


def non_text_audits(result: Snapshot) -> list[AuditEvent]:
    return [event for event in result.audits if event.action == "NON_TEXT_MESSAGE_RECEIVED"]


async def seed_conversation(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    state: str = "BOT_ACTIVE",
    pending_action: str | None = None,
    services_failed_understanding_count: int = 0,
    payment_handoff: bool = False,
) -> int:
    async with sessionmaker() as session:
        async with session.begin():
            customer = Customer(phone_number=NORMALIZED_PHONE, full_name="Cliente Media")
            session.add(customer)
            await session.flush()
            conversation = Conversation(
                customer_id=customer.id,
                channel="WHATSAPP",
                state=state,
                pending_action=pending_action,
                services_failed_understanding_count=services_failed_understanding_count,
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
            return conversation.id


def assert_safe_audit(event: AuditEvent) -> None:
    serialized = json.dumps(event.new_value)
    for forbidden in ("url", "sha256", "latitude", "longitude", NORMALIZED_PHONE):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_tc_media_001_real_voice_audio_is_routed_without_ai(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload("wamid.media.001", "audio", AUDIO_ONE),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert len(result.messages) == 1
    assert calls.general == []
    assert result.ai_execution_count == 0
    assert result.conversation.last_question_code == "RESP-FILE-003"
    assert len(non_text_audits(result)) == 1
    assert non_text_audits(result)[0].new_value["voice"] is True


@pytest.mark.asyncio
async def test_tc_media_002_two_real_audios_do_not_create_low_confidence_handoff(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload("wamid.media.002a", "audio", AUDIO_ONE),
        sessionmaker,
    )
    await process_whatsapp_webhook(
        webhook_payload("wamid.media.002b", "audio", AUDIO_TWO),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert len(result.messages) == 2
    assert calls.general == []
    assert len(result.outbox) == 2
    assert len(non_text_audits(result)) == 2
    assert not any(handoff.reason == "LOW_CONFIDENCE" for handoff in result.handoffs)
    assert result.conversation.state != "WAITING_FOR_HUMAN"


@pytest.mark.asyncio
async def test_tc_media_003_real_unsupported_routes_fallback_and_other_handoff(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.003",
            "unsupported",
            {"type": "unknown", "raw_type": "unknown"},
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert result.conversation.last_question_code == "RESP-FALLBACK-001"
    assert [(row.reason, row.priority) for row in result.handoffs] == [("OTHER", "NORMAL")]
    assert non_text_audits(result)[0].new_value["raw_type"] == "unknown"


@pytest.mark.asyncio
async def test_tc_media_004_real_non_voice_audio_preserves_voice_flag(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload("wamid.media.004", "audio", AUDIO_THREE),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert result.messages[0].content["audio"]["media_id"] == AUDIO_THREE["id"]
    assert non_text_audits(result)[0].new_value == {
        "message_type": "audio",
        "mime_type": "audio/ogg; codecs=opus",
        "has_caption": False,
        "payment_context": False,
        "voice": False,
        "duration_s": None,
    }


@pytest.mark.asyncio
async def test_tc_media_005_image_caption_is_classified_once_as_text(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    caption = "aquí está el comprobante"
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.005",
            "image",
            {
                "id": "media-image-005",
                "mime_type": "image/jpeg",
                "sha256": "declared-hash",
                "caption": caption,
            },
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == [caption]
    assert result.messages[0].content["image"]["media_id"] == "media-image-005"
    assert non_text_audits(result)[0].new_value["has_caption"] is True


@pytest.mark.asyncio
async def test_tc_media_006_image_does_not_consume_services_capture_turn(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await seed_conversation(
        sessionmaker,
        pending_action="COLLECT_SERVICES",
        services_failed_understanding_count=1,
    )
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.006",
            "image",
            {"id": "media-image-006", "mime_type": "image/jpeg", "sha256": "hash"},
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert calls.services == []
    assert result.conversation.pending_action == "COLLECT_SERVICES"
    assert result.conversation.services_failed_understanding_count == 1
    assert result.conversation.state == "BOT_ACTIVE"
    assert result.conversation.last_question_code == "RESP-FILE-001"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", [131051, 131052])
async def test_tc_media_008_unsupported_errors_are_preserved_and_audited(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
    error_code: int,
) -> None:
    sessionmaker, calls = media_context
    errors = [{"code": error_code, "title": "Unsupported message", "message": "Rejected"}]
    await process_whatsapp_webhook(
        webhook_payload(
            f"wamid.media.008.{error_code}",
            "unsupported",
            {"type": "unknown", "raw_type": "unknown"},
            errors=errors,
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert result.messages[0].content["unsupported"]["errors"] == errors
    assert non_text_audits(result)[0].new_value["error_codes"] == [error_code]
    assert str(error_code) in result.handoffs[0].summary


@pytest.mark.asyncio
async def test_tc_media_009_duplicate_media_webhook_is_fully_idempotent(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    payload = webhook_payload("wamid.media.009", "audio", AUDIO_ONE)
    await process_whatsapp_webhook(payload, sessionmaker)
    first = await snapshot(sessionmaker)
    await process_whatsapp_webhook(payload, sessionmaker)
    second = await snapshot(sessionmaker)

    assert calls.general == []
    assert len(second.messages) == len(first.messages) == 1
    assert len(second.outbox) == len(first.outbox) == 1
    assert len(second.audits) == len(first.audits)
    assert len(second.handoffs) == len(first.handoffs) == 0


def media_settings(*, max_mb: int = 16) -> Settings:
    return Settings(
        DATABASE_URL=DATABASE_URL,
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-access-token",
        META_GRAPH_API_VERSION="v20.0",
        WHATSAPP_API_BASE_URL=GRAPH_BASE,
        INBOUND_MEDIA_MAX_MB=max_mb,
        OPENROUTER_API_KEY="test-openrouter-key",
        ENVIRONMENT="testing",
        _env_file=None,
    )


@pytest.mark.asyncio
@respx.mock
async def test_tc_media_010_download_uses_fresh_meta_url_and_returns_verified_file() -> None:
    content = b"verified inbound image"
    declared_hash = base64.b64encode(hashlib.sha256(content).digest()).decode()
    stale_url = "https://lookaside.fbsbx.com/stale-webhook-url"
    fresh_url = "https://lookaside.fbsbx.com/fresh-media-url"
    metadata_route = respx.get(f"{GRAPH_BASE}/v20.0/media-010").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "media-010",
                "url": fresh_url,
                "mime_type": "image/jpeg",
                "sha256": declared_hash,
                "file_size": len(content),
            },
        )
    )
    fresh_route = respx.get(fresh_url).mock(
        return_value=httpx.Response(200, content=content, headers={"Content-Type": "image/jpeg"})
    )
    stale_route = respx.get(stale_url).mock(return_value=httpx.Response(500))
    download = getattr(media_module, "download_inbound_media", None)
    assert callable(download), "download_inbound_media contract is missing"

    async with httpx.AsyncClient() as http_client:
        result = await download(
            "media-010",
            settings=media_settings(),
            http_client=http_client,
        )

    assert result.bytes == content
    assert result.mime_type == "image/jpeg"
    assert result.sha256 == declared_hash
    assert result.size_bytes == len(content)
    assert metadata_route.called
    assert fresh_route.called
    assert not stale_route.called


@pytest.mark.asyncio
@respx.mock
async def test_tc_media_011_download_rejects_sha256_mismatch() -> None:
    fresh_url = "https://lookaside.fbsbx.com/media-011"
    respx.get(f"{GRAPH_BASE}/v20.0/media-011").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "media-011",
                "url": fresh_url,
                "mime_type": "application/pdf",
                "sha256": base64.b64encode(b"not-the-real-digest").decode(),
            },
        )
    )
    respx.get(fresh_url).mock(return_value=httpx.Response(200, content=b"actual bytes"))
    download = getattr(media_module, "download_inbound_media", None)
    mismatch_error = getattr(media_module, "InboundMediaHashMismatch", None)
    assert callable(download), "download_inbound_media contract is missing"
    assert isinstance(mismatch_error, type), "InboundMediaHashMismatch contract is missing"

    async with httpx.AsyncClient() as http_client:
        with pytest.raises(mismatch_error):
            await download("media-011", settings=media_settings(), http_client=http_client)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["content-length", "streamed-bytes"])
@respx.mock
async def test_tc_media_012_download_rejects_files_over_configured_limit(mode: str) -> None:
    fresh_url = f"https://lookaside.fbsbx.com/media-012-{mode}"
    content = b"x" * 17
    metadata: dict[str, Any] = {
        "id": f"media-012-{mode}",
        "url": fresh_url,
        "mime_type": "image/jpeg",
        "sha256": base64.b64encode(hashlib.sha256(content).digest()).decode(),
    }
    if mode == "content-length":
        metadata["file_size"] = len(content)
    respx.get(f"{GRAPH_BASE}/v20.0/media-012-{mode}").mock(
        return_value=httpx.Response(200, json=metadata)
    )
    respx.get(fresh_url).mock(return_value=httpx.Response(200, content=content))
    download = getattr(media_module, "download_inbound_media", None)
    too_large_error = getattr(media_module, "InboundMediaTooLarge", None)
    assert callable(download), "download_inbound_media contract is missing"
    assert isinstance(too_large_error, type), "InboundMediaTooLarge contract is missing"

    async with httpx.AsyncClient() as http_client:
        with pytest.raises(too_large_error):
            await download(
                f"media-012-{mode}",
                settings=media_settings(max_mb=0),
                http_client=http_client,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_input", ["", "   \t\n"])
async def test_tc_media_013_ai_client_rejects_empty_input_before_http(
    empty_input: str,
) -> None:
    empty_error = getattr(ai_errors, "EmptyClassificationInput", None)
    assert isinstance(empty_error, type), "EmptyClassificationInput contract is missing"
    transport = httpx.MockTransport(
        lambda _request: pytest.fail("HTTP must not be called for empty classification input")
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        async with OpenRouterIntentClient(
            media_settings(),
            sessionmaker=None,  # type: ignore[arg-type]
            http_client=http_client,
        ) as client:
            with pytest.raises(empty_error):
                await client.classify_intent(
                    empty_input,
                    {},
                    request_id=None,
                    external_message_id="wamid.media.013",
                )


@pytest.mark.asyncio
async def test_tc_media_014_reaction_is_audited_without_response_or_ai(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.014",
            "reaction",
            {"message_id": "wamid.original", "emoji": "👍"},
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert len(result.messages) == 1
    assert calls.general == []
    assert result.ai_execution_count == 0
    assert result.outbox == []
    event = non_text_audits(result)[0]
    assert event.new_value["emoji"] == "👍"
    assert event.new_value["reacted_message_id"] == "wamid.original"


@pytest.mark.asyncio
async def test_tc_media_015_text_message_keeps_existing_pipeline(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload("wamid.media.015", "text", {"body": "Hola"}),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == ["Hola"]
    assert len(result.messages) == 1
    assert len(result.outbox) == 1
    assert result.conversation.last_question_code == "RESP-GREETING-002"
    assert non_text_audits(result) == []


@pytest.mark.asyncio
async def test_tc_media_016_payment_image_uses_existing_payment_handoff(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await seed_conversation(
        sessionmaker,
        state="WAITING_FOR_HUMAN",
        pending_action="WAIT_FOR_HUMAN",
        payment_handoff=True,
    )
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.016",
            "image",
            {"id": "payment-proof", "mime_type": "image/jpeg", "sha256": "hash"},
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert len(result.handoffs) == 1
    assert result.handoffs[0].reason == "PAYMENT_REVIEW"
    assert result.conversation.last_question_code == "RESP-PAYMENT-002"
    assert len(result.outbox) == 1
    assert non_text_audits(result)[0].new_value["payment_context"] is True


@pytest.mark.asyncio
async def test_tc_media_017_document_preserves_filename_and_mime_type(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.017",
            "document",
            {
                "id": "document-017",
                "filename": "propuesta.pdf",
                "mime_type": "application/pdf",
                "sha256": "hash",
            },
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert result.messages[0].content["document"]["media_id"] == "document-017"
    assert result.messages[0].content["document"]["filename"] == "propuesta.pdf"
    assert result.messages[0].content["document"]["mime_type"] == "application/pdf"
    assert result.conversation.last_question_code == "RESP-FILE-004"


@pytest.mark.asyncio
async def test_tc_media_018_sticker_is_audited_silently(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.018",
            "sticker",
            {"id": "sticker-018", "mime_type": "image/webp", "sha256": "hash"},
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert len(result.messages) == 1
    assert calls.general == []
    assert result.outbox == []
    assert result.ai_execution_count == 0
    assert len(non_text_audits(result)) == 1


@pytest.mark.asyncio
async def test_tc_media_019_interactive_button_reply_becomes_text_selection(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.019",
            "interactive",
            {
                "type": "button_reply",
                "button_reply": {"id": "schedule-visit", "title": "Agendar visita"},
            },
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == ["Agendar visita"]
    assert result.messages[0].content == {
        "selection": {
            "kind": "button_reply",
            "id": "schedule-visit",
            "title": "Agendar visita",
        },
        "text": {"body": "Agendar visita"},
    }


@pytest.mark.asyncio
async def test_tc_media_020_location_audit_excludes_coordinates(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.020",
            "location",
            {
                "latitude": 7.1193,
                "longitude": -73.1227,
                "name": "Punto de encuentro",
                "address": "Bucaramanga",
            },
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert result.conversation.last_question_code == "RESP-FALLBACK-001"
    assert result.handoffs == []
    event = non_text_audits(result)[0]
    assert_safe_audit(event)


def test_tc_media_021_typed_inbound_schema_covers_media_contract() -> None:
    try:
        schemas = importlib.import_module("app.channel.schemas")
    except ModuleNotFoundError:
        pytest.fail("app.channel.schemas typed inbound contract is missing")
    message_model = getattr(schemas, "InboundWhatsAppMessage", None)
    assert message_model is not None

    parsed = message_model.model_validate(
        {
            "from": PHONE,
            "id": "wamid.media.021",
            "timestamp": "1787366893",
            "type": "document",
            "document": {
                "id": "document-021",
                "mime_type": "application/pdf",
                "sha256": "hash",
                "caption": "Cotización",
                "filename": "cotizacion.pdf",
            },
        }
    )
    assert parsed.content.media_id == "document-021"
    assert parsed.content.mime_type == "application/pdf"
    assert parsed.content.sha256 == "hash"
    assert parsed.content.caption == "Cotización"
    assert parsed.content.filename == "cotizacion.pdf"


@pytest.mark.asyncio
async def test_tc_media_022_unknown_type_preserves_raw_object_and_routes_other(
    media_context: tuple[async_sessionmaker[AsyncSession], ClassifierCalls],
) -> None:
    sessionmaker, calls = media_context
    await process_whatsapp_webhook(
        webhook_payload(
            "wamid.media.022",
            "future_media",
            {"future_field": "preserve-me", "nested": {"value": 1}},
        ),
        sessionmaker,
    )

    result = await snapshot(sessionmaker)
    assert calls.general == []
    assert result.messages[0].message_type == "unknown"
    assert result.messages[0].content["unknown"]["raw"] == {
        "future_field": "preserve-me",
        "nested": {"value": 1},
    }
    assert result.conversation.last_question_code == "RESP-FALLBACK-001"
    assert [(row.reason, row.priority) for row in result.handoffs] == [("OTHER", "NORMAL")]
    assert non_text_audits(result)[0].new_value["raw_type"] == "future_media"

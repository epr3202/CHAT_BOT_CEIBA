from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models_registry  # noqa: F401
from app.ai.client import OpenRouterIntentClient
from app.ai.schemas import IntentClassification
from app.config.database import Base
from app.config.settings import get_settings
from app.main import app
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
PHONE_NUMBER_ID = "123456789"
ADMIN_API_TOKEN = "test-admin-token"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba")


async def configure_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_VERIFY_TOKEN", VERIFY_TOKEN)
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-meta-access-token")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    monkeypatch.setenv("ADMIN_API_TOKEN", ADMIN_API_TOKEN)
    monkeypatch.setenv("META_GRAPH_API_VERSION", "v20.0")
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
    get_settings.cache_clear()

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))
    await engine.dispose()

    async def classify_as_greeting(
        self: OpenRouterIntentClient,
        message_text: str,
        context: dict[str, object],
        conversation_id: int | None = None,
    ) -> IntentClassification:
        return IntentClassification(
            primary_intent="GREETING",
            secondary_intents=[],
            sub_intent=None,
            confidence=0.91,
            entities={},
            requested_action="SEND_GREETING",
            missing_fields=[],
            needs_confirmation=False,
            needs_human=False,
            handoff_reason=None,
            priority="NORMAL",
            context_reference={},
            reasoning_code="TEST_GREETING",
        )

    monkeypatch.setattr(OpenRouterIntentClient, "classify_intent", classify_as_greeting)


async def cleanup_test_environment() -> None:
    get_settings.cache_clear()


async def app_client() -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            yield test_client


async def database_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def whatsapp_message_payload(
    message_id: str,
    phone: str = "573001112233",
    text: str = "Hola",
) -> bytes:
    payload = {
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
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Cliente"},
                                    "wa_id": phone,
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "timestamp": "1723046400",
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def signature(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"

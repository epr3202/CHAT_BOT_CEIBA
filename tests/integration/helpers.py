from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models_registry  # noqa: F401
from app.agent.auth import hash_pin
from app.agent.models import Agent
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
DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba_test",
)


def assert_safe_test_database_url(database_url: str = DATABASE_URL) -> None:
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(
            "Refusing to reset a non-test database. Set TEST_DATABASE_URL to a database "
            "whose name includes 'test'."
        )


async def ensure_test_database_exists(database_url: str = DATABASE_URL) -> None:
    assert_safe_test_database_url(database_url)
    parsed = make_url(database_url)
    database_name = parsed.database
    if database_name is None:
        raise RuntimeError("TEST_DATABASE_URL must include a database name")

    connection = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host or "localhost",
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            database_name,
        )
        if exists is None:
            quoted_name = '"' + database_name.replace('"', '""') + '"'
            await connection.execute(f"CREATE DATABASE {quoted_name}")
    finally:
        await connection.close()


async def reset_test_database(database_url: str = DATABASE_URL) -> async_sessionmaker[AsyncSession]:
    await ensure_test_database_exists(database_url)
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
    return sessionmaker


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
    get_settings.cache_clear()

    sessionmaker = await reset_test_database()
    await load_knowledge_entries(sessionmaker, list(iter_seed_entries()))

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
    assert_safe_test_database_url()
    engine = create_async_engine(DATABASE_URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def bootstrap_agent(
    name: str = "Alexandra",
    document_id: str = "1020304050",
    pin: str = "123456",
    role: str = "ADMIN",
    active: bool = True,
) -> Agent:
    engine = create_async_engine(DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        async with session.begin():
            agent = Agent(
                name=name,
                document_id=document_id,
                password_hash=hash_pin(pin),
                role=role,
                active=active,
            )
            session.add(agent)
            await session.flush()
    await engine.dispose()
    return agent


async def login_headers(
    client: AsyncClient,
    document_id: str = "1020304050",
    pin: str = "123456",
) -> dict[str, str]:
    response = await client.post(
        "/admin/login",
        json={"document_id": document_id, "pin": pin},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


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

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import respx
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models_registry  # noqa: F401
from alembic import command
from app.calendar.adapter import FakeCalendarAdapter
from app.channel import inbound
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from app.orchestrator import service as orchestrator
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from scripts.load_plans import load_plans
from tests.audio_transcription.helpers import MODEL, NOW, PHONE, TOO_LONG, WRITTEN, AudioHarness
from tests.integration.helpers import configure_test_database, ensure_test_database_exists


@pytest.fixture
async def audio_case(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AudioHarness]:
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    values = {
        "ENVIRONMENT": "testing",
        "META_ACCESS_TOKEN": "synthetic-meta-token",
        "META_PHONE_NUMBER_ID": "123456789",
        "META_GRAPH_API_VERSION": "v20.0",
        "OPENROUTER_API_KEY": "synthetic-openrouter-token",
        "OPENROUTER_MAX_RETRIES": "0",
        "CALENDAR_ADAPTER": "fake",
        "SELF_SERVICE_BOOKING_ENABLED": "true",
        "BOOKING_HOURS_END": "23:00",
        "BANK_BREB_KEY": "SYNTHETIC-KEY",
        "AUDIO_TRANSCRIPTION_ENABLED": "true",
        "AUDIO_TRANSCRIPTION_ALLOW_ALL": "false",
        "AUDIO_TRANSCRIPTION_ALLOWED_PHONES": PHONE,
        "OPENROUTER_MODEL_AUDIO": MODEL,
        "AUDIO_MAX_SECONDS": "60",
        "AUDIO_MAX_BYTES": "1048576",
        "AUDIO_TRANSCRIPTION_TIMEOUT_SECONDS": "20",
        "INBOX_MAX_BACKOFF_SECONDS": "0",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    sessions: list[AsyncSession] = []

    class ObservedSession(AsyncSession):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            sessions.append(self)

    db = async_sessionmaker(engine, class_=ObservedSession, expire_on_commit=False)
    await load_knowledge_entries(db, list(iter_seed_entries()))
    await load_plans(db)
    async with db() as session, session.begin():
        templates = {
            TOO_LONG: "Ese audio quedó un poco largo y no alcanzo a procesarlo. "
            "¿Me lo envías en menos de un minuto o me lo escribes por aquí?",
            WRITTEN: "Para dejar esto confirmado necesito que me lo escribas: "
            'respóndeme "sí" por texto, por favor.',
        }
        # Approval exists only in this synthetic test database. Production drafts
        # retain their approval gate and no seed/sync command is executed.
        for code, body in templates.items():
            session.add(
                KnowledgeEntry(
                    code=code,
                    category="Audio pruebas",
                    question_summary=code,
                    answer_template=body,
                    allowed_variables=[],
                    version=100,
                    status="APPROVED",
                )
            )
        for code in ("RESP-EVENTS-ROMANTIC-001", "RESP-EVENTS-PROPOSAL-001"):
            latest = await session.scalar(
                select(KnowledgeEntry)
                .where(
                    KnowledgeEntry.code == code,
                )
                .order_by(KnowledgeEntry.version.desc())
                .limit(1)
            )
            assert latest is not None
            session.add(
                KnowledgeEntry(
                    code=code,
                    category=latest.category,
                    question_summary=latest.question_summary,
                    answer_template=latest.answer_template,
                    allowed_variables=latest.allowed_variables,
                    version=100,
                    status="APPROVED",
                )
            )
    monkeypatch.setattr(orchestrator, "current_bogota_datetime", lambda: NOW)
    calendar = FakeCalendarAdapter()
    monkeypatch.setattr(orchestrator, "get_calendar_adapter", lambda _settings: calendar)
    original_enqueue = orchestrator.enqueue_template
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        case = AudioHarness(db, router, sessions)

        async def record_template(*args: Any, **kwargs: Any) -> None:
            conversation = args[2]
            case.codes.append((conversation.id, args[5]))
            await original_enqueue(*args, **kwargs)

        monkeypatch.setattr(orchestrator, "enqueue_template", record_template)
        monkeypatch.setattr(inbound, "enqueue_template", record_template)
        case.register_http()
        try:
            yield case
        finally:
            await engine.dispose()
            get_settings.cache_clear()

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models_registry  # noqa: F401
from app.config.database import Base
from app.conversation.faq_catalog import NO_APPROVED_ANSWER, response_code_for_category
from app.conversation.knowledge import (
    KnowledgeRenderError,
    KnowledgeRenderErrorReason,
    render_response,
)
from app.conversation.models import KnowledgeEntry
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import DATABASE_URL


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def add_entry(
    sessionmaker: async_sessionmaker[AsyncSession],
    code: str,
    template: str,
    status: str = "APPROVED",
) -> None:
    async with sessionmaker() as session:
        async with session.begin():
            session.add(
                KnowledgeEntry(
                    code=code,
                    category="Test",
                    question_summary="Test response",
                    answer_template=template,
                    allowed_variables=["customer_name"],
                    version=1,
                    status=status,
                )
            )


@pytest.mark.asyncio
async def test_render_response_with_complete_variables(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await add_entry(sessionmaker_fixture, "RESP-TEST-001", "Hola, {customer_name}.")

    rendered = await render_response(
        sessionmaker_fixture,
        "RESP-TEST-001",
        {"customer_name": "Natalia"},
    )

    assert rendered == "Hola, Natalia."


@pytest.mark.asyncio
async def test_missing_variable_does_not_render_partial_text(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await add_entry(sessionmaker_fixture, "RESP-TEST-002", "Hola, {customer_name}.")

    with pytest.raises(KnowledgeRenderError) as error:
        await render_response(sessionmaker_fixture, "RESP-TEST-002", {})

    assert error.value.reason == KnowledgeRenderErrorReason.MISSING_VARIABLE


@pytest.mark.asyncio
async def test_draft_entry_is_not_renderable(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await add_entry(
        sessionmaker_fixture,
        "RESP-TEST-003",
        "[REVISAR] Texto incompleto.",
        status="DRAFT",
    )

    with pytest.raises(KnowledgeRenderError) as error:
        await render_response(sessionmaker_fixture, "RESP-TEST-003", {})

    assert error.value.reason == KnowledgeRenderErrorReason.NOT_APPROVED


def test_unknown_category_returns_no_approved_answer() -> None:
    assert response_code_for_category("categoria inexistente") == NO_APPROVED_ANSWER


@pytest.mark.asyncio
async def test_seed_loader_is_idempotent(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    entries = list(iter_seed_entries())

    first_count = await load_knowledge_entries(sessionmaker_fixture, entries)
    second_count = await load_knowledge_entries(sessionmaker_fixture, entries)

    async with sessionmaker_fixture() as session:
        total = await session.scalar(select(func.count()).select_from(KnowledgeEntry))

    assert first_count == len(entries)
    assert second_count == 0
    assert total == len(entries)

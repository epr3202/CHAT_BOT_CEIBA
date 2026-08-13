from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conversation.faq_catalog import NO_APPROVED_ANSWER, response_code_for_category
from app.conversation.knowledge import (
    KnowledgeRenderError,
    KnowledgeRenderErrorReason,
    render_response,
)
from app.conversation.models import KnowledgeEntry
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.integration.helpers import reset_test_database


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield await reset_test_database()


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
    async with sessionmaker_fixture() as session:
        first_snapshot = (
            (
                await session.execute(
                    select(
                        KnowledgeEntry.code,
                        KnowledgeEntry.category,
                        KnowledgeEntry.question_summary,
                        KnowledgeEntry.answer_template,
                        KnowledgeEntry.allowed_variables,
                        KnowledgeEntry.version,
                        KnowledgeEntry.status,
                    ).order_by(KnowledgeEntry.code, KnowledgeEntry.version)
                )
            )
            .tuples()
            .all()
        )

    second_count = await load_knowledge_entries(sessionmaker_fixture, entries)

    async with sessionmaker_fixture() as session:
        total = await session.scalar(select(func.count()).select_from(KnowledgeEntry))
        second_snapshot = (
            (
                await session.execute(
                    select(
                        KnowledgeEntry.code,
                        KnowledgeEntry.category,
                        KnowledgeEntry.question_summary,
                        KnowledgeEntry.answer_template,
                        KnowledgeEntry.allowed_variables,
                        KnowledgeEntry.version,
                        KnowledgeEntry.status,
                    ).order_by(KnowledgeEntry.code, KnowledgeEntry.version)
                )
            )
            .tuples()
            .all()
        )

    assert first_count == len(entries)
    assert second_count == 0
    assert total == len(entries)
    assert second_snapshot == first_snapshot

from __future__ import annotations

import re
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


async def knowledge_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str, str, str, list[str], int, str]]:
    async with sessionmaker() as session:
        return (
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
    first_snapshot = await knowledge_snapshot(sessionmaker_fixture)

    second_count = await load_knowledge_entries(sessionmaker_fixture, entries)

    async with sessionmaker_fixture() as session:
        total = await session.scalar(select(func.count()).select_from(KnowledgeEntry))
    second_snapshot = await knowledge_snapshot(sessionmaker_fixture)

    assert first_count == len(entries)
    assert second_count == 0
    assert total == len(entries)
    assert second_snapshot == first_snapshot


@pytest.mark.asyncio
async def test_approved_templates_render_without_internal_enums_or_iso_dates(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    entries = list(iter_seed_entries())
    await load_knowledge_entries(sessionmaker_fixture, entries)
    safe_values = {
        "adult_guest_count": "40",
        "advisor_name": "Natalia",
        "appointment_options": "08:00, 09:00 y 11:00",
        "child_guest_count": "5",
        "customer_name": "Natalia",
        "email": "natalia@example.com",
        "event_date": "13 de septiembre de 2026",
        "event_month": "septiembre de 2026",
        "event_type": "una boda",
        "guest_count": "45",
        "guest_count_range": "entre 40 y 50",
        "map_url": "https://example.com/mapa",
        "missing_field": "la fecha del evento",
        "new_visit_date": "18 de agosto de 2026",
        "new_visit_time": "08:00",
        "pending_topic": "los servicios",
        "requested_services_summary": "el espacio",
        "resolved_date": "13 de septiembre de 2026",
        "service_name": "gastronomía",
        "total_guest_count": "45",
        "visit_attendee_count": "2",
        "visit_date": "18 de agosto de 2026",
        "visit_time": "08:00",
    }
    unsafe_enum = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
    iso_date = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")

    for entry in entries:
        if entry.status != "APPROVED":
            continue
        variables = {name: safe_values[name] for name in entry.allowed_variables}
        rendered = await render_response(sessionmaker_fixture, entry.code, variables)

        assert unsafe_enum.search(rendered) is None, entry.code
        assert iso_date.search(rendered) is None, entry.code

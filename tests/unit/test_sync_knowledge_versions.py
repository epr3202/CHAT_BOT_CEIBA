from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conversation.models import KnowledgeEntry
from data.knowledge_seed import KnowledgeSeedEntry
from scripts.sync_knowledge_versions import (
    changed_knowledge_fields,
    next_knowledge_version,
    plan_knowledge_sync,
    sync_knowledge_versions,
)
from tests.integration.helpers import reset_test_database


@pytest.fixture
async def sessionmaker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield await reset_test_database()


def seed_entry(**overrides: object) -> KnowledgeSeedEntry:
    values: dict[str, object] = {
        "code": "RESP-TEST-001",
        "category": "General",
        "question_summary": "Saludo",
        "answer_template": "Hola, {customer_name}.",
        "allowed_variables": ["customer_name"],
        "version": 1,
        "status": "APPROVED",
    }
    values.update(overrides)
    return KnowledgeSeedEntry(**values)  # type: ignore[arg-type]


def stored_entry(**overrides: object) -> KnowledgeEntry:
    values: dict[str, object] = {
        "code": "RESP-TEST-001",
        "category": "General",
        "question_summary": "Saludo",
        "answer_template": "Hola, {customer_name}.",
        "allowed_variables": ["customer_name"],
        "version": 1,
        "status": "APPROVED",
    }
    values.update(overrides)
    return KnowledgeEntry(**values)


def test_diff_compares_only_versioned_content_fields() -> None:
    seed = seed_entry(status="DRAFT", version=99)
    latest = stored_entry(status="APPROVED", version=7)

    assert changed_knowledge_fields(seed, latest) == ()
    assert plan_knowledge_sync(seed, [latest]).action == "UNCHANGED"


@pytest.mark.parametrize(
    ("override", "expected_field"),
    [
        ({"answer_template": "Texto nuevo"}, "answer_template"),
        ({"question_summary": "Resumen nuevo"}, "question_summary"),
        ({"category": "Otra"}, "category"),
        ({"allowed_variables": ["event_type"]}, "allowed_variables"),
    ],
)
def test_diff_reports_each_synchronized_field(
    override: dict[str, object],
    expected_field: str,
) -> None:
    assert changed_knowledge_fields(seed_entry(**override), stored_entry()) == (
        expected_field,
    )


def test_missing_code_starts_at_version_one() -> None:
    plan = plan_knowledge_sync(seed_entry(), [])

    assert plan.action == "CREATE"
    assert plan.new_version == 1
    assert len(plan.answer_preview) <= 60


def test_changed_code_bumps_from_highest_stored_version() -> None:
    existing = [
        stored_entry(version=9, answer_template="Anterior"),
        stored_entry(version=3),
    ]

    assert next_knowledge_version(existing) == 10
    plan = plan_knowledge_sync(seed_entry(version=1), existing)
    assert plan.action == "BUMP"
    assert plan.new_version == 10


@pytest.mark.asyncio
async def test_execute_bumps_and_inactivates_all_previous_renderable_versions(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture() as session:
        async with session.begin():
            session.add_all(
                [
                    stored_entry(version=1, status="APPROVED", answer_template="Uno"),
                    stored_entry(version=2, status="DRAFT", answer_template="Dos"),
                    stored_entry(version=4, status="INACTIVE", answer_template="Cuatro"),
                ]
            )

    plans = await sync_knowledge_versions(
        sessionmaker_fixture,
        [seed_entry(status="DRAFT", answer_template="Cinco")],
        execute=True,
    )

    async with sessionmaker_fixture() as session:
        rows = list(
            (
                await session.scalars(
                    select(KnowledgeEntry).order_by(KnowledgeEntry.version)
                )
            ).all()
        )

    assert plans[0].new_version == 5
    assert [(row.version, row.status) for row in rows] == [
        (1, "INACTIVE"),
        (2, "INACTIVE"),
        (4, "INACTIVE"),
        (5, "DRAFT"),
    ]


@pytest.mark.asyncio
async def test_default_dry_run_does_not_write(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    plans = await sync_knowledge_versions(sessionmaker_fixture, [seed_entry()])

    async with sessionmaker_fixture() as session:
        rows = list((await session.scalars(select(KnowledgeEntry))).all())

    assert plans[0].action == "CREATE"
    assert rows == []

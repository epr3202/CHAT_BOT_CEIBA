"""Bre-B payment copy and effective version contracts; initially staged off-repo."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.conversation.knowledge import (
    KnowledgeRenderError,
    KnowledgeRenderErrorReason,
    render_response,
)
from app.conversation.models import KnowledgeEntry
from data.knowledge_seed import KnowledgeSeedEntry, iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from scripts.sync_knowledge_versions import plan_knowledge_sync, sync_knowledge_versions
from tests.unit.test_knowledge import sessionmaker_fixture as sessionmaker_fixture

PAYMENT_CODE = "RESP-BOOKING-PAYMENT-001"
OLD_PAYMENT_TEMPLATE = (
    "¡Listo! Tu fecha está disponible hoy y queda asegurada al recibir el abono de "
    "{deposit_amount}. Puedes transferir a {bank_name}, {account_type} No. "
    "{account_number}, a nombre de {account_holder}. Cuando lo hagas, envíame aquí "
    "la foto del comprobante y nuestro equipo lo confirma."
)
EXPECTED_PAYMENT_TEMPLATE = (
    "¡Listo! Tu fecha está disponible hoy y queda asegurada al recibir el abono de "
    "{deposit_amount}. Puedes transferir a {bank_name}, {account_type} No. "
    "{account_number}, a nombre de {account_holder}.\n"
    "Llave Bre-B: {breb_key}\n"
    "Cuando lo hagas, envíame aquí la foto del comprobante y nuestro equipo lo confirma."
)
OLD_VARIABLES = frozenset(
    {"deposit_amount", "bank_name", "account_type", "account_number", "account_holder"}
)
PAYMENT_VARIABLES = OLD_VARIABLES | {"breb_key"}
EXPECTED_RENDERED_PAYMENT = (
    "¡Listo! Tu fecha está disponible hoy y queda asegurada al recibir el abono de "
    "$225.000. Puedes transferir a Banco Sintético, Ahorros No. 000123456, a nombre "
    "de Titular de prueba.\n"
    "Llave Bre-B: CEIBA-BREB-TEST\n"
    "Cuando lo hagas, envíame aquí la foto del comprobante y nuestro equipo lo confirma."
)


def payment_seed() -> KnowledgeSeedEntry:
    entries = [entry for entry in iter_seed_entries() if entry.code == PAYMENT_CODE]
    assert len(entries) == 1, "The payment code must remain a single seed entry"
    return entries[0]


def bank_settings() -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/ceiba_test",
        META_APP_SECRET="test",
        META_ACCESS_TOKEN="test",
        OPENROUTER_API_KEY="test",
        ENVIRONMENT="testing",
        BOOKING_BANK_NAME="Banco Sintético",
        BOOKING_ACCOUNT_TYPE="Ahorros",
        BOOKING_ACCOUNT_NUMBER="000123456",
        BOOKING_ACCOUNT_HOLDER="Titular de prueba",
        BANK_BREB_KEY="CEIBA-BREB-TEST",
        _env_file=None,
    )


def payment_variables(settings: Settings) -> dict[str, Any]:
    return {
        "deposit_amount": 225000,
        "bank_name": settings,
        "account_type": settings,
        "account_number": settings,
        "account_holder": settings,
        "breb_key": settings,
    }


def legacy_entry(version: int, status: str = "APPROVED") -> KnowledgeEntry:
    seed = payment_seed()
    return KnowledgeEntry(
        code=PAYMENT_CODE,
        category=seed.category,
        question_summary=seed.question_summary,
        answer_template=OLD_PAYMENT_TEMPLATE,
        allowed_variables=sorted(OLD_VARIABLES),
        version=version,
        status=status,
    )


async def entries(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[KnowledgeEntry]:
    async with sessionmaker() as session:
        return list(
            await session.scalars(
                select(KnowledgeEntry)
                .where(KnowledgeEntry.code == PAYMENT_CODE)
                .order_by(KnowledgeEntry.version)
            )
        )


def snapshot(rows: list[KnowledgeEntry]) -> list[tuple[Any, ...]]:
    return [
        (
            row.id,
            row.version,
            row.status,
            row.answer_template,
            row.allowed_variables,
            row.updated_at_version,
        )
        for row in rows
    ]


async def add_literal_payment(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    status: str = "APPROVED",
    allowed_variables: frozenset[str] = PAYMENT_VARIABLES,
) -> None:
    seed = payment_seed()
    async with sessionmaker.begin() as session:
        session.add(
            KnowledgeEntry(
                code=PAYMENT_CODE,
                category=seed.category,
                question_summary=seed.question_summary,
                answer_template=EXPECTED_PAYMENT_TEMPLATE,
                allowed_variables=sorted(allowed_variables),
                version=3,
                status=status,
            )
        )


def test_r2_payment_seed_has_only_the_approved_breb_line_added() -> None:
    seed = payment_seed()
    assert seed.answer_template == EXPECTED_PAYMENT_TEMPLATE
    assert set(seed.allowed_variables) == PAYMENT_VARIABLES


def test_r2_payment_seed_is_effectively_approved_version_three() -> None:
    seed = payment_seed()
    assert seed.version == 3
    assert seed.status == "APPROVED"


async def test_r2_seed_payment_renders_breb_from_backend_settings(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await load_knowledge_entries(sessionmaker_fixture, [payment_seed()])
    caught: KnowledgeRenderError | None = None
    rendered: str | None = None
    try:
        rendered = await render_response(
            sessionmaker_fixture, PAYMENT_CODE, payment_variables(bank_settings())
        )
    except KnowledgeRenderError as error:
        caught = error
    assert caught is None, f"Approved payment must render; got {caught.reason if caught else None}"
    assert rendered == EXPECTED_RENDERED_PAYMENT


@pytest.mark.parametrize(
    "customer_value",
    ["CEIBA-BREB-CLIENT", {"BANK_BREB_KEY": "CEIBA-BREB-CLIENT"}],
)
async def test_r2_breb_presenter_rejects_customer_strings_and_mappings(
    sessionmaker_fixture: async_sessionmaker[AsyncSession], customer_value: object
) -> None:
    await add_literal_payment(sessionmaker_fixture)
    variables = payment_variables(bank_settings())
    variables["breb_key"] = customer_value
    with pytest.raises(KnowledgeRenderError) as caught:
        await render_response(sessionmaker_fixture, PAYMENT_CODE, variables)
    assert caught.value.reason == KnowledgeRenderErrorReason.PRESENTATION_ERROR
    assert caught.value.variable == "breb_key"


async def test_r2_breb_key_must_be_an_allowed_template_variable(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    await add_literal_payment(sessionmaker_fixture, allowed_variables=OLD_VARIABLES)
    with pytest.raises(KnowledgeRenderError) as caught:
        await render_response(
            sessionmaker_fixture, PAYMENT_CODE, payment_variables(bank_settings())
        )
    assert caught.value.reason == KnowledgeRenderErrorReason.UNKNOWN_VARIABLE
    assert caught.value.variable == "breb_key"


async def test_r2_later_draft_does_not_revive_an_approved_payment_version(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture.begin() as session:
        session.add(legacy_entry(2))
    await add_literal_payment(sessionmaker_fixture, status="DRAFT")
    with pytest.raises(KnowledgeRenderError) as caught:
        await render_response(
            sessionmaker_fixture, PAYMENT_CODE, payment_variables(bank_settings())
        )
    assert caught.value.reason == KnowledgeRenderErrorReason.NOT_APPROVED
    assert [(row.version, row.status) for row in await entries(sessionmaker_fixture)] == [
        (2, "APPROVED"),
        (3, "DRAFT"),
    ]


async def test_r2_seed_v3_inactivates_old_versions_and_is_idempotent(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker_fixture.begin() as session:
        session.add_all([legacy_entry(1, "INACTIVE"), legacy_entry(2)])
    assert await load_knowledge_entries(sessionmaker_fixture, [payment_seed()]) == 1
    rows = await entries(sessionmaker_fixture)
    assert [(row.version, row.status) for row in rows] == [
        (1, "INACTIVE"),
        (2, "INACTIVE"),
        (3, "APPROVED"),
    ]
    assert sum(row.status == "APPROVED" for row in rows) == 1
    assert [row.answer_template for row in rows[:2]] == [OLD_PAYMENT_TEMPLATE] * 2
    assert rows[-1].answer_template == EXPECTED_PAYMENT_TEMPLATE
    before = snapshot(rows)
    assert await load_knowledge_entries(sessionmaker_fixture, [payment_seed()]) == 0
    assert snapshot(await entries(sessionmaker_fixture)) == before


def test_r2_sync_create_respects_the_payment_seed_version() -> None:
    plan = plan_knowledge_sync(payment_seed(), [])
    assert plan.action == "CREATE"
    assert plan.new_version == 3


@pytest.mark.parametrize(
    "existing_versions,expected_version", [([1], 3), ([1, 2], 3), ([1, 2, 8], 9)]
)
def test_r2_sync_changed_payment_never_precedes_its_seed_version(
    existing_versions: list[int], expected_version: int
) -> None:
    plan = plan_knowledge_sync(payment_seed(), [legacy_entry(v) for v in existing_versions])
    assert plan.action == "BUMP"
    assert plan.new_version == expected_version


async def test_r2_sync_create_executes_v3_once_and_dry_run_is_read_only(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
) -> None:
    dry = await sync_knowledge_versions(sessionmaker_fixture, [payment_seed()])
    assert await entries(sessionmaker_fixture) == []
    assert dry[0].action == "CREATE" and dry[0].new_version == 3
    first = await sync_knowledge_versions(
        sessionmaker_fixture, [payment_seed()], execute=True
    )
    assert first[0].action == "CREATE" and first[0].new_version == 3
    rows = await entries(sessionmaker_fixture)
    assert [(row.version, row.status) for row in rows] == [(3, "APPROVED")]
    before = snapshot(rows)
    second = await sync_knowledge_versions(
        sessionmaker_fixture, [payment_seed()], execute=True
    )
    assert second[0].action == "UNCHANGED"
    assert snapshot(await entries(sessionmaker_fixture)) == before


@pytest.mark.parametrize("highest_version,expected_version", [(2, 3), (8, 9)])
async def test_r2_sync_execute_keeps_one_approved_payment_and_preserves_history(
    sessionmaker_fixture: async_sessionmaker[AsyncSession],
    highest_version: int,
    expected_version: int,
) -> None:
    async with sessionmaker_fixture.begin() as session:
        session.add_all([legacy_entry(1, "INACTIVE"), legacy_entry(highest_version)])
    result = await sync_knowledge_versions(
        sessionmaker_fixture, [payment_seed()], execute=True
    )
    assert result[0].action == "BUMP" and result[0].new_version == expected_version
    rows = await entries(sessionmaker_fixture)
    assert [(row.version, row.status) for row in rows] == [
        (1, "INACTIVE"),
        (highest_version, "INACTIVE"),
        (expected_version, "APPROVED"),
    ]
    assert rows[-1].answer_template == EXPECTED_PAYMENT_TEMPLATE
    assert [row.answer_template for row in rows[:2]] == [OLD_PAYMENT_TEMPLATE] * 2
    assert sum(row.status == "APPROVED" for row in rows) == 1
    before = snapshot(rows)
    repeat = await sync_knowledge_versions(
        sessionmaker_fixture, [payment_seed()], execute=True
    )
    assert repeat[0].action == "UNCHANGED"
    assert snapshot(await entries(sessionmaker_fixture)) == before

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

import app.models_registry  # noqa: F401
from alembic import command
from app.ai.models import AIExecution
from app.config.settings import get_settings
from tests.integration.helpers import assert_safe_test_database_url, current_test_database_url

EXPECTED_AI_EXECUTION_COLUMNS = {
    "id",
    "created_at",
    "request_id",
    "external_message_id",
    "task",
    "model",
    "prompt_version",
    "input_payload",
    "raw_output",
    "parsed_output",
    "validation_status",
    "latency_ms",
    "error",
}


def quote_postgres_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture
async def migrated_database_url(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    source_url = current_test_database_url()
    assert_safe_test_database_url(source_url)
    parsed = make_url(source_url)
    database_name = f"ceiba_test_aiexec_parity_{uuid4().hex}"
    quoted_database_name = quote_postgres_identifier(database_name)

    admin_connection = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host or "localhost",
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        await admin_connection.execute(f"CREATE DATABASE {quoted_database_name}")
    finally:
        await admin_connection.close()

    database_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("META_ACCESS_TOKEN", "test-meta-access-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("ENVIRONMENT", "testing")
    get_settings.cache_clear()

    try:
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
        yield database_url
    finally:
        get_settings.cache_clear()
        admin_connection = await asyncpg.connect(
            user=parsed.username,
            password=parsed.password,
            host=parsed.host or "localhost",
            port=parsed.port or 5432,
            database="postgres",
        )
        try:
            await admin_connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await admin_connection.execute(f"DROP DATABASE {quoted_database_name}")
        finally:
            await admin_connection.close()


def column_contract(column: object) -> tuple[bool, bool, str, int | None, bool]:
    column_type = column.type  # type: ignore[attr-defined]
    return (
        bool(column.nullable),  # type: ignore[attr-defined]
        bool(column.primary_key),  # type: ignore[attr-defined]
        column_type._type_affinity.__name__,
        getattr(column_type, "length", None),
        column.server_default is not None,  # type: ignore[attr-defined]
    )


def reflected_column_contract(
    column: dict[str, object],
) -> tuple[bool, bool, str, int | None, bool]:
    column_type = column["type"]
    return (
        bool(column["nullable"]),
        bool(column.get("primary_key")),
        column_type._type_affinity.__name__,  # type: ignore[attr-defined]
        getattr(column_type, "length", None),
        column.get("default") is not None,
    )


@pytest.mark.asyncio
async def test_tc_parity_001_ai_execution_metadata_matches_migrated_database(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    try:
        async with engine.connect() as connection:
            reflected_columns = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_columns("ai_execution")
            )
    finally:
        await engine.dispose()

    metadata_columns = {column.name: column for column in AIExecution.__table__.columns}
    migrated_columns = {str(column["name"]): column for column in reflected_columns}

    assert set(metadata_columns) == EXPECTED_AI_EXECUTION_COLUMNS
    assert set(migrated_columns) == EXPECTED_AI_EXECUTION_COLUMNS
    assert {name: column_contract(column) for name, column in metadata_columns.items()} == {
        name: reflected_column_contract(column) for name, column in migrated_columns.items()
    }

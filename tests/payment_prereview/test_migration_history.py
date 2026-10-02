"""F1: revision rollback preserves append-only vision execution history."""

import asyncio
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.integration.helpers import configure_test_database, ensure_test_database_exists


async def test_0033_cycle_preserves_receipt_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    engine = create_async_engine(url)
    config = Config("alembic.ini")

    async def read_execution(execution_id: int) -> dict[str, Any] | None:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT * FROM ai_execution WHERE id = :id"), {"id": execution_id}
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await asyncio.to_thread(command.upgrade, config, "20260930_0032")
        await asyncio.to_thread(command.upgrade, config, "20260930_0033")
        async with engine.begin() as connection:
            result = await connection.execute(
                text("""
                    INSERT INTO ai_execution
                        (task, model, latency_ms, success, prompt_version,
                         input_character_count, validation_status, input_payload)
                    VALUES
                        ('RECEIPT_EXTRACTION', 'synthetic-vision', 17, true, 'receipt_v1',
                         0, 'VALID', '{"evidence_id": 123, "mime": "image/png"}'::jsonb)
                    RETURNING id
                """)
            )
            execution_id = result.scalar_one()
        original = await read_execution(execution_id)
        assert original is not None

        await asyncio.to_thread(command.downgrade, config, "20260930_0032")
        assert await read_execution(execution_id) == original, (
            "0033 downgrade must retain every field of append-only RECEIPT_EXTRACTION history"
        )
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            assert "payment_evidence_review" not in tables
            checks = await connection.run_sync(
                lambda sync: inspect(sync).get_check_constraints("ai_execution")
            )
            assert any(
                check["name"] == "ck_ai_execution_task"
                and "RECEIPT_EXTRACTION" in check["sqltext"]
                for check in checks
            ), "the expanded task CHECK is intentionally irreversible"
            assert await connection.scalar(
                text("SELECT to_regprocedure('reject_payment_review_mutation()')")
            ) is None
            assert await connection.scalar(
                text("SELECT to_regclass('ix_payment_evidence_review_evidence_id')")
            ) is None
            assert await connection.scalar(
                text("SELECT count(*) FROM pg_trigger WHERE tgname = 'payment_review_append_only'")
            ) == 0

        await asyncio.to_thread(command.upgrade, config, "20260930_0033")
        assert await read_execution(execution_id) == original
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT to_regclass('payment_evidence_review')")
            ) is not None
    finally:
        await engine.dispose()

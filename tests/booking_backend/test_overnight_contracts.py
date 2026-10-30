"""0037 must reject destructive rollback of an outstanding inquiry confirmation."""

import asyncio

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.integration.helpers import configure_test_database, ensure_test_database_exists


async def test_0037_downgrade_rejects_active_pending_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    engine = create_async_engine(url)
    config = Config("alembic.ini")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.begin() as connection:
            customer_id = await connection.scalar(
                text("INSERT INTO customer (phone_number) VALUES ('+573000003737') RETURNING id")
            )
            conversation_id = await connection.scalar(
                text(
                    "INSERT INTO conversation (customer_id, channel, state, pending_action, "
                    "failed_understanding_count, bot_enabled, pending_fields) "
                    "VALUES (:id, 'WHATSAPP', 'BOT_ACTIVE', 'CONFIRM_AVAILABILITY_BOOKING', "
                    "0, true, '[]'::jsonb) "
                    "RETURNING id"
                ),
                {"id": customer_id},
            )
        with pytest.raises(IntegrityError):
            await asyncio.to_thread(command.downgrade, config, "20261007_0036")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20261028_0037"
            )
            assert (
                await connection.scalar(
                    text("SELECT pending_action FROM conversation WHERE id=:id"),
                    {"id": conversation_id},
                )
                == "CONFIRM_AVAILABILITY_BOOKING"
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name='plan' AND column_name IN "
                        "('overnight','checkin_from','checkout_time')"
                    )
                )
                == 3
            )
        # An explicit test-owned resolution permits a clean rollback; the migration
        # itself must never clear this value to force its old CHECK through.
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE conversation SET pending_action=NULL WHERE id=:id"),
                {"id": conversation_id},
            )
        await asyncio.to_thread(command.downgrade, config, "20261007_0036")
        await asyncio.to_thread(command.upgrade, config, "20261028_0037")
    finally:
        await engine.dispose()

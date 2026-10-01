import asyncio
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.event.models import Event
from tests.integration.helpers import configure_test_database, ensure_test_database_exists


async def test_r6_0029_only_event_plan_and_full_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("20260930_0029") is not None
    assert scripts.get_revision("20260930_0029").down_revision == "20260930_0028"
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    engine = create_async_engine(url)

    async def snapshot() -> dict:
        async with engine.connect() as connection:

            def read(sync: Any) -> dict:
                inspector = inspect(sync)
                return {
                    table: {
                        "columns": [
                            (c["name"], str(c["type"]), c["nullable"])
                            for c in inspector.get_columns(table)
                        ],
                        "fks": inspector.get_foreign_keys(table),
                        "indexes": inspector.get_indexes(table),
                    }
                    for table in inspector.get_table_names()
                }

            return await connection.run_sync(read)

    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await asyncio.to_thread(command.upgrade, config, "20260930_0028")
        before = await snapshot()
        await asyncio.to_thread(command.upgrade, config, "20260930_0029")
        after = await snapshot()
        assert {k: v for k, v in before.items() if k != "event"} == {
            k: v for k, v in after.items() if k != "event"
        }
        assert set(after["event"]["columns"]) - set(before["event"]["columns"]) == {
            ("plan_id", "UUID", True)
        }
        assert any(
            fk["constrained_columns"] == ["plan_id"] and fk["referred_table"] == "plan"
            for fk in after["event"]["fks"]
        )
        assert any(
            ix["column_names"] == ["plan_id"] and not ix["unique"]
            for ix in after["event"]["indexes"]
        )
        assert Event.__table__.c.plan_id.nullable
        await asyncio.to_thread(command.downgrade, config, "20260930_0028")
        assert await snapshot() == before
        await asyncio.to_thread(command.upgrade, config, "20260930_0029")
        assert await snapshot() == after
    finally:
        await engine.dispose()

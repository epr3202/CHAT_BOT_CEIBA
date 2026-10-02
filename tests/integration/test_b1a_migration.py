"""R3/R5: run real Alembic upgrade/downgrade/upgrade on the normal test DB."""

import asyncio
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.config.database import Base
from app.config.settings import get_settings
from tests.integration.helpers import configure_test_database, ensure_test_database_exists


async def test_r3_migrated_schema_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    for key in ("META_APP_SECRET", "META_ACCESS_TOKEN", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "test")
    monkeypatch.setenv("ENVIRONMENT", "testing")
    get_settings.cache_clear()
    engine = create_async_engine(url)
    config = Config("alembic.ini")

    async def schema() -> dict[str, dict[str, Any]]:
        async with engine.connect() as connection:

            def snapshot(sync: Any) -> dict[str, dict[str, Any]]:
                inspector = inspect(sync)
                return {
                    name: {
                        "columns": {
                            c["name"]: (str(c["type"]), c["nullable"])
                            for c in inspector.get_columns(name)
                        },
                        "foreign_keys": inspector.get_foreign_keys(name),
                        "indexes": inspector.get_indexes(name),
                    }
                    for name in inspector.get_table_names()
                }

            return await connection.run_sync(snapshot)

    try:
        # The existing helper refuses databases whose name does not contain 'test'.
        # No extra database is created for this slice.
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await asyncio.to_thread(command.upgrade, config, "head")
        before = await schema()
        await asyncio.to_thread(command.downgrade, config, "base")
        down = await schema()
        assert not ({"plan", "reservation", "payment_evidence"} & down.keys())
        await asyncio.to_thread(command.upgrade, config, "head")
        after = await schema()
        assert before == after, "upgrade/downgrade/upgrade debe reconstruir el mismo esquema"
        assert {"plan", "reservation"} <= after.keys(), "B1a: faltan las tablas migradas"
        for name in ("plan", "reservation"):
            assert name in Base.metadata.tables, f"B1a: falta registrar {name}"
            table = Base.metadata.tables[name]
            assert set(after[name]["columns"]) == set(table.c.keys())
            assert {key: item[1] for key, item in after[name]["columns"].items()} == {
                column.name: column.nullable for column in table.c
            }
        assert any(
            index["column_names"] == ["starts_at", "status"]
            for index in after["reservation"]["indexes"]
        )
        evidence = after["payment_evidence"]
        assert evidence["columns"]["reservation_id"] == ("UUID", True)
        assert any(
            fk["constrained_columns"] == ["reservation_id"]
            and fk["referred_table"] == "reservation"
            and fk["referred_columns"] == ["reservation_id"]
            for fk in evidence["foreign_keys"]
        )
        assert after["reservation"]["columns"]["starts_at"][0] == "TIMESTAMP"
        async with engine.connect() as connection:
            timestamps = await connection.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='reservation' "
                    "AND column_name IN ('starts_at','ends_at','balance_due_at',"
                    "'hold_expires_at','created_at','updated_at')"
                )
            )
            rows = list(timestamps)
            assert len(rows) == 6
            assert all(row.data_type == "timestamp with time zone" for row in rows)
    finally:
        await engine.dispose()
        get_settings.cache_clear()

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.main import app
from tests.integration.test_ai_execution_migration_parity import (
    migrated_database_url as migrated_database_url,
)


@pytest.fixture
async def probe_client(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, AsyncEngine]]:
    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    monkeypatch.setattr(app.state, "db_engine", engine, raising=False)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://probes.test",
        ) as client:
            yield client, engine
    finally:
        await engine.dispose()


async def test_live_does_not_require_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "db_engine", None, raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://probes.test",
    ) as client:
        response = await client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_ready_accepts_a_database_migrated_to_head(
    probe_client: tuple[httpx.AsyncClient, AsyncEngine],
) -> None:
    client, _ = probe_client
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_rejects_a_different_database_revision(
    probe_client: tuple[httpx.AsyncClient, AsyncEngine],
) -> None:
    client, engine = probe_client
    async with engine.connect() as connection:
        original_revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": "not-current"},
            )
        response = await client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": original_revision},
            )
    restored = await client.get("/ready")
    assert restored.status_code == 200
    assert restored.json() == {"status": "ready"}

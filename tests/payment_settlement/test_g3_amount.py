import asyncio
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.main import app
from app.payment.models import PaymentEvidence
from tests.integration.helpers import (
    configure_test_database,
    ensure_test_database_exists,
    login_headers,
)
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence, seed_reservation


async def test_g3_c1_evidence_amount_stored_and_detail_never_reads_audit(client: AsyncClient):
    reservation = await seed_reservation("PAYMENT_REVIEW")
    evidence = await seed_evidence(reservation_id=reservation.reservation_id)
    headers = await login_headers(client, "90000000")
    response = await client.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=headers,
        json={"amount_cop": 50000},
    )
    assert response.status_code == 200
    assert "amount_cop" in PaymentEvidence.__table__.c, "C1: amount belongs to the evidence"
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.get(PaymentEvidence, evidence.id)
        assert saved.amount_cop == 50000
    second = await seed_evidence(reservation_id=reservation.reservation_id)
    async with app.state.db_sessionmaker.begin() as session:
        (await session.get(PaymentEvidence, second.id)).amount_cop = 25000
    statements: list[str] = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(app.state.db_engine.sync_engine, "before_cursor_execute", observe)
    try:
        detail = await client.get(
            f"/admin/reservations/{reservation.reservation_id}", headers=headers
        )
        listing = await client.get("/admin/payment-evidence", headers=headers)
    finally:
        event.remove(app.state.db_engine.sync_engine, "before_cursor_execute", observe)
    assert detail.status_code == listing.status_code == 200
    assert {row["id"]: row["amount_cop"] for row in detail.json()["evidences"]} == {
        evidence.id: 50000,
        second.id: 25000,
    }
    assert next(row for row in listing.json() if row["id"] == second.id)["amount_cop"] == 25000
    assert next(row for row in listing.json() if row["id"] == second.id)["reservation_id"] == str(
        reservation.reservation_id
    )
    assert not any("audit_event" in sql and sql.lstrip().startswith("select") for sql in statements)


async def test_g3_c1_migration_0032_nullable_integer_full_downgrade(
    monkeypatch: pytest.MonkeyPatch,
):
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert "20260930_0032" in scripts.get_heads(), "C1: migration 0032 is required"
    revision = scripts.get_revision("20260930_0032")
    assert revision is not None, "C1: migration 0032 is required"
    assert revision.down_revision == "20260930_0031"
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    engine = create_async_engine(url)

    async def snapshot() -> dict:
        async with engine.connect() as connection:

            def read(sync: Any) -> dict:
                inspector = inspect(sync)
                return {
                    table: [
                        (c["name"], str(c["type"]), c["nullable"])
                        for c in inspector.get_columns(table)
                    ]
                    for table in inspector.get_table_names()
                }

            return await connection.run_sync(read)

    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await asyncio.to_thread(command.upgrade, config, "20260930_0031")
        before = await snapshot()
        await asyncio.to_thread(command.upgrade, config, "20260930_0032")
        after = await snapshot()
        assert {k: v for k, v in before.items() if k != "payment_evidence"} == {
            k: v for k, v in after.items() if k != "payment_evidence"
        }
        assert set(after["payment_evidence"]) - set(before["payment_evidence"]) == {
            ("amount_cop", "INTEGER", True)
        }
        await asyncio.to_thread(command.downgrade, config, "20260930_0031")
        assert await snapshot() == before
        await asyncio.to_thread(command.upgrade, config, "head")
        assert await snapshot() == after
    finally:
        await engine.dispose()

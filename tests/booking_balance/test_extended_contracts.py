"""Post-G2 contract extensions; no retroactive red claim for these cases."""

import asyncio
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.config.settings import Settings
from app.conversation.pending_actions import PENDING_ACTIONS
from app.main import app
from app.reservation.models import Reservation
from tests.booking_balance.b4_helpers import DUE_AT, reserved
from tests.integration.helpers import (
    configure_test_database,
    ensure_test_database_exists,
    login_headers,
)


@pytest.mark.parametrize("balance_status", ["pending", "overdue"])
async def test_balance_filter_is_admin_only_and_returns_matching_reservations(
    client, balance_status
):
    assert "balance_overdue_at" in Reservation.__table__.c
    pending = await reserved()
    overdue = await reserved(balance_overdue_at=DUE_AT)
    await reserved(amount_paid_cop=400000, payment_kind="FULL", balance_due_at=None)
    headers = await login_headers(client, "90000000")
    response = await client.get(
        "/admin/reservations", headers=headers, params={"balance_status": balance_status}
    )
    assert response.status_code == 200, response.text
    expected = {str(overdue.reservation_id)}
    if balance_status == "pending":
        expected.add(str(pending.reservation_id))
    assert {row["reservation_id"] for row in response.json()} == expected
    assert all("balance_overdue_at" in row for row in response.json())
    denied = await client.get(
        "/admin/reservations",
        headers=await login_headers(client, "80000000"),
        params={"balance_status": balance_status},
    )
    assert denied.status_code == 403


def test_balance_settings_and_delivery_context_do_not_extend_public_state_catalog():
    assert "balance_reminders_enabled" in Settings.model_fields
    assert Settings.model_fields["balance_reminders_enabled"].default is False
    assert "PAYMENT_EVIDENCE_ACK" not in PENDING_ACTIONS
    assert "BALANCE_OVERDUE" not in PENDING_ACTIONS


async def test_0035_one_step_cycle_preserves_append_only_history(monkeypatch):
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == "20261002_0035"
    assert scripts.get_revision("20261002_0035").down_revision == "20261002_0034"
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO audit_event (actor, action, entity, reason, request_id)
                VALUES ('TEST', 'G3_HISTORY', 'reservation', 'Conservar historia', 'g3-cycle')
            """)
            )
            await connection.execute(
                text("""
                INSERT INTO ai_execution
                  (task, model, latency_ms, success, prompt_version,
                   input_character_count, validation_status)
                VALUES ('RECEIPT_EXTRACTION', 'synthetic', 1, true, 'receipt_v1', 0, 'VALID')
            """)
            )

        async def snapshot():
            async with engine.connect() as connection:
                return (
                    list((await connection.execute(text("SELECT * FROM audit_event"))).mappings()),
                    list((await connection.execute(text("SELECT * FROM ai_execution"))).mappings()),
                )

        original = await snapshot()
        await asyncio.to_thread(command.downgrade, config, "-1")
        assert await snapshot() == original
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
            assert "customer_notification" not in tables
            assert "payment_evidence_review" in tables
        await asyncio.to_thread(command.upgrade, config, "head")
        assert await snapshot() == original
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda c: {row["name"]: row for row in inspect(c).get_columns("payment_evidence")}
            )
            assert columns["prereview_claim_token"]["nullable"]
            assert columns["prereview_claimed_at"]["type"].timezone
            uniques = await connection.run_sync(
                lambda c: inspect(c).get_unique_constraints("customer_notification")
            )
            assert any(set(row["column_names"]) == {"reservation_id", "kind"} for row in uniques)
    finally:
        await engine.dispose()


async def test_invalid_balance_filter_returns_422(client):
    response = await client.get(
        "/admin/reservations",
        headers=await login_headers(client, "90000000"),
        params={"balance_status": "inventado"},
    )
    assert response.status_code == 422


async def test_overdue_filter_requires_reserved_and_positive_balance(client):
    assert "balance_overdue_at" in Reservation.__table__.c
    row = await reserved(balance_overdue_at=datetime(2026, 10, 9, tzinfo=UTC))
    async with app.state.db_sessionmaker.begin() as session:
        saved = await session.scalar(
            select(Reservation).where(Reservation.reservation_id == row.reservation_id)
        )
        saved.status = "CANCELLED"
    response = await client.get(
        "/admin/reservations",
        headers=await login_headers(client, "90000000"),
        params={"balance_status": "overdue"},
    )
    assert response.status_code == 200 and response.json() == []

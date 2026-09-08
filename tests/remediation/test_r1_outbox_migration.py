"""Reuse the existing isolated Alembic fixture, preserving all legacy business rows."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.audit.models import AuditEvent
from app.channel.models import Outbox
from app.channel.worker import claim_due_outbox_batch, recover_stale_sending_outbox
from tests.integration.test_ai_execution_migration_parity import (
    migrated_database_url as migrated_database_url,
)
from tests.remediation.test_r1_outbox import T0, Sender, evidence, process, seed, snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_claimed_at", [None, T0])
async def test_legacy_rows_upgrade_parity_recovery_and_downgrade(
    migrated_database_url: str,
    request: pytest.FixtureRequest,
    legacy_claimed_at: Any,
) -> None:
    # The reused fixture creates and attests a fresh UUID database, then upgrades to head.
    # Alembic changes schema through another engine; do not reuse prepared SELECT * plans.
    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    db = async_sessionmaker(engine, expire_on_commit=False)
    commands = ["fixture: alembic upgrade head"]
    try:
        await seed(db)
        async with db() as session, session.begin():
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="R1_SYNTHETIC_BASELINE",
                    entity="outbox",
                    new_value={"synthetic": True},
                    reason="legacy preservation",
                )
            )
        await asyncio.to_thread(command.downgrade, Config("alembic.ini"), "20260825_0024")
        commands.append("alembic downgrade 20260825_0024")
        async with db() as session, session.begin():
            for state in ("SENDING", "SENT", "FAILED"):
                await session.execute(
                    text("""
                    INSERT INTO outbox (conversation_id, message_id, channel,
                        recipient_phone_number, payload, message_kind, status, attempts,
                        claimed_at, sent_at, last_error, created_at)
                    SELECT conversation_id, message_id, channel, recipient_phone_number,
                        payload, message_kind, CAST(:state AS varchar(32)), 2,
                        CAST(:claimed AS timestamptz), CAST(:sent AS timestamptz),
                        CAST(:error AS varchar(1000)), CAST(:now AS timestamptz)
                    FROM outbox WHERE id=1
                """),
                    {
                        "state": state,
                        "sent": T0 if state == "SENT" else None,
                        "error": "synthetic terminal" if state == "FAILED" else None,
                        "claimed": legacy_claimed_at if state == "SENDING" else None,
                        "now": T0,
                    },
                )
        before = await snapshot(db)
        assert [r["status"] for r in before["outbox"]] == ["PENDING", "SENDING", "SENT", "FAILED"]
        assert all("claim_token" not in r for r in before["outbox"])
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "20260908_0025")
        commands.append("alembic upgrade 20260908_0025")
        upgraded = await snapshot(db)
        expected = {**before, "outbox": [{**r, "claim_token": None} for r in before["outbox"]]}
        assert upgraded == expected
        async with engine.connect() as connection:
            columns = await connection.run_sync(lambda c: inspect(c).get_columns("outbox"))
            actual = next(c for c in columns if c["name"] == "claim_token")
            model = Outbox.__table__.c.claim_token
            assert actual["nullable"] is model.nullable is True
            assert actual["type"]._type_affinity == model.type._type_affinity
            assert actual["default"] is None and model.server_default is None
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260908_0025"
            )
        assert await recover_stale_sending_outbox(db, T0 + timedelta(seconds=121), 120, 5, 300) == 1
        recovered = await snapshot(db)
        assert recovered["outbox"][1]["status"] == "PENDING"
        assert recovered["outbox"][1]["attempts"] == 3
        assert recovered["outbox"][1]["claim_token"] is None
        assert recovered["message"] == before["message"]
        assert recovered["audit_event"] == before["audit_event"]
        claims = await claim_due_outbox_batch(db, T0 + timedelta(seconds=140), 10)
        assert {item.id for item in claims} == {1, 2}
        assert len({item.claim_token for item in claims}) == 2
        for item in claims:
            assert await process(db, item, Sender("r1.legacy." + str(item.id))) == "APPLIED"
        final = await snapshot(db)
        assert [r["status"] for r in final["outbox"]] == ["SENT", "SENT", "SENT", "FAILED"]
        assert final["outbox"][2:] == upgraded["outbox"][2:]
        assert len(final["message"]) == 3
        assert final["audit_event"] == before["audit_event"]
        # Controlled rollback rehearsal with consumers stopped and all identities retired.
        await asyncio.to_thread(command.downgrade, Config("alembic.ini"), "20260825_0024")
        commands.append("alembic downgrade 20260825_0024 (no active consumers)")
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "20260908_0025")
        commands.append("alembic upgrade 20260908_0025")
        assert await snapshot(db) == final
        evidence(
            request,
            before=before,
            upgraded=upgraded,
            recovered=recovered,
            final=final,
            commands=commands,
            database=migrated_database_url.rsplit("/", 1)[1],
            field={
                "nullable": actual["nullable"],
                "type": str(actual["type"]),
                "default": actual["default"],
            },
        )
    finally:
        await engine.dispose()

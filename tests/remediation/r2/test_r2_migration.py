"""0025→0026 preservation, focal schema parity and selected legacy treatment."""

from __future__ import annotations

import asyncio

import pytest
import respx
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.channel import inbound, inbox
from app.channel.models import InboxJob
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from scripts.reprocess_webhook_events import adopt_unmaterialized, legacy_inventory
from tests.integration.test_ai_execution_migration_parity import (
    migrated_database_url as migrated_database_url,
)
from tests.remediation.r2.test_r2_inbox import snapshot
from tests.remediation.r2.test_r2_recovery import greeting_http, payload
from tests.remediation.r9.test_r9_migration import NEW_OUTBOX_COLUMNS, seed_pre_r9
from tests.remediation.test_r1_outbox import evidence


@pytest.mark.asyncio
async def test_0025_legacy_is_not_mass_replayed_and_new_head_parity(
    migrated_database_url: str,
    request: pytest.FixtureRequest,
) -> None:
    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    db = async_sessionmaker(engine, expire_on_commit=False)
    commands = ["fixture upgrade head", "downgrade 20260908_0025"]
    try:
        await asyncio.to_thread(command.downgrade, Config("alembic.ini"), "20260908_0025")
        await seed_pre_r9(db)
        # Seed legacy events by SQL, without invoking new-version ORM defaults/columns.
        async with db() as session, session.begin():
            for status in ("RECEIVED", "PROCESSED", "FAILED"):
                import json

                await session.execute(
                    text(
                        "INSERT INTO webhook_event (payload,status,request_id) "
                        "VALUES (CAST(:payload AS jsonb),:status,'synthetic-legacy')"
                    ),
                    {"payload": json.dumps(payload("r2.legacy." + status)), "status": status},
                )
        async with db() as session:
            before = {
                table: [
                    dict(r)
                    for r in (
                        await session.execute(text(f'SELECT * FROM "{table}" ORDER BY id'))
                    ).mappings()
                ]
                for table in ("message", "outbox", "audit_event", "webhook_event")
            }
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "20260908_0026")
        commands.append("upgrade 20260908_0026 (historical contract)")
        upgraded = await snapshot(db)
        assert upgraded["inbox_job"] == []
        for table in ("message", "outbox", "audit_event"):
            assert upgraded[table] == before[table]
        for old, new in zip(before["webhook_event"], upgraded["webhook_event"], strict=True):
            assert new == {
                **old,
                "intake_version": None,
                "ingest_attempts": 0,
                "next_attempt_at": None,
            }
        async with engine.connect() as connection:
            columns = await connection.run_sync(lambda c: inspect(c).get_columns("inbox_job"))
            checks = await connection.run_sync(
                lambda c: inspect(c).get_check_constraints("inbox_job")
            )
            indexes = await connection.run_sync(lambda c: inspect(c).get_indexes("inbox_job"))
            unique = await connection.run_sync(
                lambda c: inspect(c).get_unique_constraints("inbox_job")
            )
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260908_0026"
            )
        model = InboxJob.__table__
        assert {c["name"] for c in columns} == set(model.c.keys())
        for c in columns:
            expected = model.c[c["name"]]
            assert c["nullable"] == expected.nullable
            assert c["type"]._type_affinity == expected.type._type_affinity
        assert {c["name"] for c in checks} == {
            "ck_inbox_job_status",
            "ck_inbox_job_attempts",
            "ck_inbox_job_owner",
        }
        assert {i["name"] for i in indexes} >= {
            "ix_inbox_job_due",
            "ix_inbox_job_conversation_order",
            "ix_inbox_job_stale",
        }
        assert any(
            u["name"] == "uq_inbox_job_message" and u["column_names"] == ["message_id"]
            for u in unique
        )
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "20260910_0027")
        commands.append("upgrade 0027 before current consumer")
        current = await snapshot(db)
        assert all(row["automation_epoch"] is not None for row in current["conversation"])
        assert current == {**upgraded, "outbox": [
            {**row, **NEW_OUTBOX_COLUMNS} for row in upgraded["outbox"]], "conversation": [
            {**old, "automation_epoch": new["automation_epoch"]}
            for old, new in zip(upgraded["conversation"], current["conversation"], strict=True)]}
        upgraded = current
        before["outbox"] = [{**row, **NEW_OUTBOX_COLUMNS} for row in before["outbox"]]
        with respx.mock(assert_all_called=False):
            await inbox.process_inbox_once(db)
        assert await snapshot(db) == upgraded
        assert await legacy_inventory(db) == {"events_unproven": 3, "messages_unproven": 1}
        # Explicit selection can admit an old RECEIVED event that never created a message.
        await load_knowledge_entries(db, list(iter_seed_entries()))
        await adopt_unmaterialized(db, 1)
        with respx.mock as router:
            greeting_http(router)
            await inbox.process_inbox_once(db)
        assert (await snapshot(db))["webhook_event"][0]["status"] == "PROCESSED"
        # A new re-delivery of the old Message is ambiguous, even if an Outbox exists.
        legacy_id = before["message"][0]["external_message_id"]
        data = payload(legacy_id)
        data["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "573000000001"
        event_id = await inbound.store_webhook_event(data, db, None)
        with respx.mock(assert_all_called=False):
            await inbound.process_webhook_event(event_id, db)
        final = await snapshot(db)
        legacy_job = next(j for j in final["inbox_job"] if j["origin"] == "LEGACY")
        assert legacy_job["status"] == "REVIEW" and legacy_job["completed_at"] is None
        assert final["message"][0] == before["message"][0]
        assert final["outbox"][0] == before["outbox"][0]
        # A destructive downgrade rehearsal only, not an operational rollback guarantee.
        await asyncio.to_thread(command.downgrade, Config("alembic.ini"), "20260908_0025")
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
        commands.extend(["downgrade 20260908_0025 (synthetic consumers stopped)", "upgrade head"])
        cycled = await snapshot(db)
        assert cycled["inbox_job"] == []
        assert cycled["message"] == final["message"]
        # The deliberate downgrade removes these four new columns, not historical values.
        assert cycled["outbox"] == [{**row, **NEW_OUTBOX_COLUMNS} for row in final["outbox"]]
        assert cycled["audit_event"] == final["audit_event"]
        evidence(
            request,
            before=before,
            upgraded=upgraded,
            final=final,
            cycled=cycled,
            commands=commands,
            database=migrated_database_url.rsplit("/", 1)[1],
            checks=checks,
            indexes=indexes,
            unique=unique,
        )
    finally:
        await engine.dispose()

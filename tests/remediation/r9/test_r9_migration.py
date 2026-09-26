"""Synthetic pre-R9 history and independent 0027 reflection/default/restart proof."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.channel.models import Outbox
from app.channel.worker import process_outbox_once
from app.conversation.models import Conversation
from tests.integration.test_ai_execution_migration_parity import (
    migrated_database_url as migrated_database_url,
)
from tests.remediation.r9.helpers import Sender
from tests.remediation.test_r1_outbox import evidence, snapshot

NEW_OUTBOX_COLUMNS = {
    "delivery_context": None, "send_admission": None,
    "delivery_reason": None, "delivery_decided_at": None,
}


async def seed_pre_r9(db: Any) -> int:
    """Historical SQL fixture has no current ORM defaults or inferred permission."""
    async with db() as session, session.begin():
        customer_id = await session.scalar(text(
            "INSERT INTO customer (phone_number) VALUES ('+573000000001') RETURNING id",
        ))
        conversation_id = await session.scalar(text(
            "INSERT INTO conversation (customer_id,channel,state,pending_fields,"
            "failed_understanding_count,bot_enabled) "
            "VALUES (:customer,'WHATSAPP','BOT_ACTIVE','[]'::jsonb,0,true) RETURNING id",
        ), {"customer": customer_id})
        message_id = await session.scalar(text(
            "INSERT INTO message (external_message_id,conversation_id,customer_id,channel,"
            "direction,message_type,content) VALUES ('r9.legacy.input',:conv,:customer,"
            "'WHATSAPP','INBOUND','text','{}'::json) RETURNING id",
        ), {"conv": conversation_id, "customer": customer_id})
        return await session.scalar(text(
            "INSERT INTO outbox (conversation_id,message_id,channel,recipient_phone_number,"
            "payload,message_kind,status,attempts) VALUES (:conv,:message,'WHATSAPP',"
            "'+573000000001','{\"text\":{\"body\":\"synthetic legacy\"}}'::json,"
            "'TEXT','PENDING',0) RETURNING id",
        ), {"conv": conversation_id, "message": message_id})


@pytest.mark.asyncio
async def test_0027_preserves_history_and_quarantines_unproven_outputs(
    migrated_database_url: str, request: pytest.FixtureRequest,
) -> None:
    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    db = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await asyncio.to_thread(command.downgrade, Config("alembic.ini"), "20260908_0026")
        await seed_pre_r9(db)
        now = datetime.now(UTC)
        async with db() as session, session.begin():
            for label, state, mark in [
                ("backoff", "PENDING", None), ("sending", "SENDING", None),
                ("sent", "SENT", None), ("failed", "FAILED", None),
                ("human", "PENDING", True), ("truthy", "PENDING", "true"),
            ]:
                payload = {"type": "text", "text": {"body": "Synthetic " + label}}
                if mark is not None:
                    payload["agent"] = mark
                outbox_id = await session.scalar(text(
                    "INSERT INTO outbox (conversation_id,message_id,channel,"
                    "recipient_phone_number,payload,message_kind,status,attempts,"
                    "next_attempt_at,created_at) SELECT conversation_id,message_id,channel,"
                    "recipient_phone_number,CAST(:payload AS json),'TEXT',:state,2,:due,:created "
                    "FROM outbox WHERE id=1 RETURNING id",
                ), {"payload": json.dumps(payload), "state": state,
                    "due": now + timedelta(minutes=1) if label == "backoff" else None,
                    "created": now - timedelta(minutes=10)})
                if mark is not None:
                    await session.execute(text(
                        "INSERT INTO audit_event (actor,action,entity,new_value,reason) "
                        "VALUES ('R9 historical human','AGENT_MESSAGE_ENQUEUED','outbox',"
                        "CAST(:value AS json),'Synthetic proven server action')",
                    ), {"value": json.dumps({"outbox_id": outbox_id, "conversation_id": 1})})
        before = await snapshot(db)
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "20260910_0027")
        upgraded = await snapshot(db)
        assert upgraded == {**before, "outbox": [
            {**r, **NEW_OUTBOX_COLUMNS} for r in before["outbox"]]}
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260910_0027")
            for model in [Outbox, Conversation]:
                columns = await connection.run_sync(lambda c, table=model.__tablename__: (
                    inspect(c).get_columns(table)))
                assert {c["name"] for c in columns} == set(model.__table__.c.keys())
                for column in columns:
                    expected = model.__table__.c[column["name"]]
                    assert column["nullable"] == expected.nullable
                    assert column["type"]._type_affinity == expected.type._type_affinity
                    if column["name"] == "automation_epoch":
                        assert "gen_random_uuid()" in column["default"]
                        assert expected.server_default is not None
                    if column["name"] in NEW_OUTBOX_COLUMNS:
                        assert column["default"] is None and expected.server_default is None
            epochs = (await connection.execute(text(
                "SELECT automation_epoch FROM conversation",
            ))).scalars().all()
            assert len(epochs) == 1 and epochs[0] is not None
        async with db() as session, session.begin():
            server_epoch = await session.scalar(text(
                "INSERT INTO conversation (customer_id,channel,state,pending_fields,"
                "failed_understanding_count,bot_enabled) VALUES (1,'WHATSAPP','BOT_ACTIVE',"
                "'[]'::jsonb,0,true) RETURNING automation_epoch",
            ))
            model = Conversation(customer_id=1, channel="WHATSAPP", state="BOT_ACTIVE")
            session.add(model)
            await session.flush()
            assert len({epochs[0], server_epoch, model.automation_epoch}) == 3
        # Restart the consumer with a fresh engine; legacy origin cannot come from process memory.
        await engine.dispose()
        sender = Sender()
        await process_outbox_once(db, sender, now=now + timedelta(days=1))
        final = await snapshot(db)
        evidence(request, before=before, upgraded=upgraded, final=final, sends=sender.sends,
                 revision="20260910_0027", previous="20260908_0026", epochs=epochs)
        assert [r["status"] for r in final["outbox"]] == [
            "REVIEW", "REVIEW", "REVIEW", "SENT", "FAILED", "SENT", "REVIEW"]
        assert len(sender.sends) == 1
        assert final["outbox"][3:5] == upgraded["outbox"][3:5]
        assert final["message"][:-1] == before["message"]
        assert final["audit_event"] == before["audit_event"]
    finally:
        await engine.dispose()

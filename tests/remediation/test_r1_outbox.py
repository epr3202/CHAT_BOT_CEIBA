"""Persisted ownership regressions, executable unchanged against the R0 product."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models_registry  # noqa: F401
from app.catalog.models import CatalogAsset
from app.channel.media import PermanentCatalogMediaError
from app.channel.models import Message, Outbox
from app.channel.worker import (
    claim_due_outbox_batch,
    process_claimed_outbox_item,
    recover_stale_sending_outbox,
)
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from tests.integration.helpers import configure_test_database, reset_test_database

T0 = datetime(2026, 9, 8, 12, tzinfo=UTC)
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = configure_test_database(monkeypatch)
    engine = create_async_engine(url)
    try:
        if os.environ.get("QUALITY_STAGE") == "suite":
            await reset_test_database(url)
        else:
            # Keep the Alembic schema: only synthetic rows of this attested job are cleared.
            async with engine.begin() as connection:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version"))
                names = (
                    (
                        await connection.execute(
                            text(
                                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                                "AND tablename != 'alembic_version'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                quoted = ", ".join('"' + name.replace('"', '""') + '"' for name in names)
                await connection.execute(text("TRUNCATE " + quoted + " RESTART IDENTITY CASCADE"))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        get_settings.cache_clear()


async def seed(db: async_sessionmaker[AsyncSession], kind: str = "TEXT", **fields: Any) -> int:
    async with db() as session, session.begin():
        customer = Customer(phone_number="+573000000001")
        session.add(customer)
        await session.flush()
        conversation = Conversation(customer_id=customer.id, channel="WHATSAPP", state="BOT_ACTIVE")
        session.add(conversation)
        await session.flush()
        inbound = Message(
            external_message_id="r1.inbound." + uuid4().hex,
            conversation_id=conversation.id,
            customer_id=customer.id,
            channel="WHATSAPP",
            direction="INBOUND",
            message_type="text",
            content={"text": {"body": "synthetic input"}},
        )
        session.add(inbound)
        await session.flush()
        asset_id = None
        if kind == "DOCUMENT":
            asset = CatalogAsset(
                name="synthetic",
                file_path="r1.pdf",
                file_hash="0" * 64,
                file_size=1,
                media_id="synthetic-cache",
                media_uploaded_at=datetime.now(UTC),
            )
            session.add(asset)
            await session.flush()
            asset_id = asset.catalog_asset_id
        row = Outbox(
            conversation_id=conversation.id,
            message_id=inbound.id,
            channel="WHATSAPP",
            recipient_phone_number=customer.phone_number,
            payload={
                "text": {"body": "synthetic reply"},
                "document": {"caption": "synthetic caption"},
            },
            message_kind=kind,
            catalog_asset_id=asset_id,
            created_at=T0 - timedelta(seconds=10),
            **fields,
        )
        session.add(row)
        await session.flush()
        return row.id


async def snapshot(db: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    # Always a new session; SELECT * includes every persisted settlement field.
    async with db() as session:
        return {
            table: [
                dict(row)
                for row in (
                    await session.execute(text(f'SELECT * FROM "{table}" ORDER BY id'))
                ).mappings()
            ]
            for table in ("outbox", "message", "audit_event")
        }


def evidence(request: pytest.FixtureRequest, **states: Any) -> None:
    output = Path("/quality-output")
    if output.is_dir():
        key = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
        (output / ("rows-" + key + ".json")).write_text(
            json.dumps({"nodeid": request.node.nodeid, **states}, default=str, indent=2)
        )


class Sender:
    def __init__(self, outcome: str | Exception, blocked: bool = False) -> None:
        self.outcome = outcome
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        if not blocked:
            self.release.set()

    async def send_text(self, to: str, body: str) -> str:
        self.calls += 1
        self.started.set()
        await asyncio.wait_for(self.release.wait(), 20)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def send_document(self, to: str, media_id: str, filename: str, caption: str) -> str:
        return await self.send_text(to, caption)


async def claim(db: async_sessionmaker[AsyncSession], at: datetime = T0) -> Any:
    rows = await claim_due_outbox_batch(db, at, 1)
    assert len(rows) == 1
    return rows[0]


async def process(db: async_sessionmaker[AsyncSession], item: Any, sender: Sender) -> Any:
    return await process_claimed_outbox_item(db, item, sender, 5, 300)


async def reap(db: async_sessionmaker[AsyncSession]) -> None:
    assert await recover_stale_sending_outbox(db, T0 + timedelta(seconds=121), 120, 5, 300) == 1


@pytest.mark.parametrize("kind", ["TEXT", "DOCUMENT"])
@pytest.mark.parametrize("failure", [False, True])
async def test_current_result(
    db: Any, request: pytest.FixtureRequest, kind: str, failure: bool
) -> None:
    await seed(db, kind)
    item = await claim(db)
    sender = Sender(TimeoutError("synthetic retry") if failure else "r1.current")
    await process(db, item, sender)
    rows = await snapshot(db)
    evidence(request, final=rows)
    row = rows["outbox"][0]
    assert row["status"] == ("PENDING" if failure else "SENT")
    assert row["attempts"] == int(failure)
    assert row["claimed_at"] is None
    assert len(rows["message"]) == (1 if failure else 2)
    assert rows["audit_event"] == []
    if not failure:
        message = rows["message"][1]
        assert message["external_message_id"] == "r1.current"
        assert message["direction"] == "OUTBOUND"
        assert message["conversation_id"] == row["conversation_id"]
        assert message["message_type"] == kind.lower()


@pytest.mark.parametrize(
    "kind,outcome",
    [
        ("TEXT", "success"),
        ("TEXT", "retry"),
        ("DOCUMENT", "success"),
        ("DOCUMENT", "retry"),
        ("DOCUMENT", "permanent"),
    ],
)
@pytest.mark.parametrize("boundary", ["new_sent", "new_sending", "reaped"])
async def test_obsolete_result_preserves_all_rows(
    db: Any,
    request: pytest.FixtureRequest,
    kind: str,
    outcome: str,
    boundary: str,
) -> None:
    await seed(db, kind)
    old_claim = await claim(db)
    value = {
        "success": "r1.old",
        "retry": TimeoutError("synthetic old timeout"),
        "permanent": PermanentCatalogMediaError("synthetic old permanent"),
    }[outcome]
    old_sender = Sender(value, blocked=True)
    task = asyncio.create_task(process(db, old_claim, old_sender))
    try:
        await asyncio.wait_for(old_sender.started.wait(), 20)
        await reap(db)  # Completes while HTTP is blocked: no claim transaction across HTTP.
        if boundary != "reaped":
            new_claim = await claim(db, T0 + timedelta(seconds=130))
            if boundary == "new_sent":
                await process(db, new_claim, Sender("r1.new"))
        before = await snapshot(db)
        old_sender.release.set()
        result = await asyncio.wait_for(task, 20)
        after = await snapshot(db)
        evidence(
            request, before=before, after=after, result=result, external_old_calls=old_sender.calls
        )
        assert after == before
    finally:
        old_sender.release.set()
        await asyncio.gather(task, return_exceptions=True)

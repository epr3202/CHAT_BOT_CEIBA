"""Only forked by the attested Linux job; never launched against an operational DB."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.channel.delivery import admit_outbox
from app.conversation.models import Conversation
from app.conversation.service import transition_conversation


def checkpoint_process(url: str, connection: Any, operation: str, boundary: str,
                       conversation_id: int, outbox_id: int, token: Any) -> None:
    # fork inherits the R0 socket/asyncpg guard, including DB instance/role attestation.
    # A new NullPool engine avoids inheriting any parent's live SQLAlchemy connection.
    async def run() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        db = async_sessionmaker(engine, expire_on_commit=False)
        reached = False

        def pause_before_commit(conn: Any, cursor: Any, statement: str, parameters: Any,
                                context: Any, many: bool) -> None:
            nonlocal reached
            prefix = "update conversation" if operation == "pause" else "update outbox"
            if not reached and statement.lower().startswith(prefix):
                reached = True
                connection.send("SQL_EXECUTED_UNCOMMITTED")
                connection.recv()  # Parent kills only this child at the proven checkpoint.

        if boundary == "before_commit":
            event.listen(engine.sync_engine, "after_cursor_execute", pause_before_commit)
        try:
            if operation == "pause":
                async with db() as session, session.begin():
                    conversation = await session.get(Conversation, conversation_id,
                                                     with_for_update=True)
                    await transition_conversation(session, conversation, "WAITING_FOR_HUMAN",
                                                  "SYSTEM", "R9 synthetic process checkpoint")
            else:
                assert await admit_outbox(db, outbox_id, token) == "ADMITTED"
            connection.send("COMMITTED")
            connection.recv()
        finally:
            await engine.dispose()

    asyncio.run(run())

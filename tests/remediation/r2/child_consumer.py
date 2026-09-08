"""Disposable, attested consumer used only inside the R2 Actions job."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import respx
from sqlalchemy import text

from scripts.quality.r0.isolation import Isolation


class ConsumerDone(BaseException):
    pass


def signal(phase: str, **fields: Any) -> None:
    print("R2_SIGNAL " + json.dumps(dict(phase=phase, pid=os.getpid(), **fields)), flush=True)


async def main() -> None:
    guard = Isolation()
    guard.install()
    import app.models_registry  # noqa: F401
    from app.channel import inbox
    from app.channel.worker import _run_inbox_loop
    from app.config.database import create_engine, create_sessionmaker
    from app.config.settings import get_settings
    from tests.remediation.r2.test_r2_recovery import greeting_http

    engine = create_engine(guard.url())
    sm = create_sessionmaker(engine)
    settings = get_settings()
    mode = sys.argv[1]
    if mode == "message_commit":
        original_expand = inbox.expand_event

        async def expand(*args: Any, **kwargs: Any) -> Any:
            result = await original_expand(*args, **kwargs)
            signal(mode, message_ids=result, blocked=guard.blocked)
            await asyncio.Event().wait()

        inbox.expand_event = expand
    elif mode == "claim_commit":
        original_claim = inbox.claim_inbox_batch

        async def claim(sm: Any, now: Any, *args: Any, **kwargs: Any) -> Any:
            result = await original_claim(sm, datetime(2026, 1, 1, tzinfo=UTC), *args, **kwargs)
            if result:
                signal(mode, tokens=[str(c.claim_token) for c in result], blocked=guard.blocked)
                await asyncio.Event().wait()
            return result

        inbox.claim_inbox_batch = claim
    else:
        assert mode == "recover"
        original_once = inbox.process_inbox_once

        async def once(*args: Any, **kwargs: Any) -> Any:
            result = await original_once(*args, **kwargs)
            async with sm() as session:
                complete = await session.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM inbox_job) "
                        "AND NOT EXISTS(SELECT 1 FROM inbox_job WHERE status <> 'COMPLETED') "
                        "AND NOT EXISTS(SELECT 1 FROM webhook_event WHERE status <> 'PROCESSED')"
                    )
                )
            if complete:
                signal("recovered", counts=result, blocked=guard.blocked)
                raise ConsumerDone()
            return result

        inbox.process_inbox_once = once
    try:
        with respx.mock(assert_all_called=False) as router:
            greeting_http(router)
            await _run_inbox_loop(sm, settings)
    except ConsumerDone:
        pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

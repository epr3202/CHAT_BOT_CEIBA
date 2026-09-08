"""Kill only a signalled child; a new real worker recovers without manual replay."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import pytest

from app.channel import inbound
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.remediation.r2.test_r2_inbox import snapshot
from tests.remediation.r2.test_r2_recovery import payload
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


async def child(mode: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "tests.remediation.r2.child_consumer",
        mode,
        env=os.environ | {"INBOX_MAX_BACKOFF_SECONDS": "0", "INBOX_POLL_INTERVAL_SECONDS": "0.1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )


async def receive(process: asyncio.subprocess.Process) -> dict[str, Any]:
    assert process.stdout is not None
    lines: list[str] = []
    while True:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=40)
        assert line, "Child exited before signal: " + "".join(lines)
        decoded = line.decode()
        if decoded.startswith("R2_SIGNAL "):
            return json.loads(decoded.removeprefix("R2_SIGNAL "))
        lines.append(decoded)


@pytest.mark.parametrize("boundary", ["message_commit", "claim_commit"])
async def test_killed_consumer_is_recovered_by_new_process(
    db: Any, request: pytest.FixtureRequest, boundary: str
) -> None:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    await inbound.store_webhook_event(payload("r2.process"), db, None)
    first = await child(boundary)
    try:
        committed_signal = await receive(first)
        assert committed_signal["pid"] == first.pid and committed_signal["blocked"] == []
        committed = await snapshot(db)
        assert len(committed["message"]) == len(committed["inbox_job"]) == 1
        assert committed["outbox"] == []
        first.kill()
        await asyncio.wait_for(first.wait(), timeout=10)
        assert first.returncode == -9
    finally:
        if first.returncode is None:
            first.kill()
            await first.wait()
    second = await child("recover")
    try:
        recovered_signal = await receive(second)
        await asyncio.wait_for(second.wait(), timeout=10)
        assert second.returncode == 0 and second.pid != first.pid
        assert recovered_signal["phase"] == "recovered" and recovered_signal["blocked"] == []
    finally:
        if second.returncode is None:
            second.kill()
            await second.wait()
    final = await snapshot(db)
    evidence(
        request,
        committed=committed,
        final=final,
        committed_signal=committed_signal,
        killed_pid=first.pid,
        exit_code=first.returncode,
        recovered_signal=recovered_signal,
    )
    assert final["message"][0] == committed["message"][0]
    assert len(final["outbox"]) == 1
    assert final["inbox_job"][0]["status"] == "COMPLETED"
    assert final["webhook_event"][0]["status"] == "PROCESSED"

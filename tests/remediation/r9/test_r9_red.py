"""Functional RED on exact BASE product, frozen after both remote jobs."""

from typing import Any

import pytest
import respx

from app.channel.worker import process_outbox_once
from tests.remediation.r8.helpers import api as api
from tests.remediation.r8.helpers import snapshot
from tests.remediation.r9.helpers import Sender, enqueue, take
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("kind", ["TEXT", "DOCUMENT"])
async def test_previous_automatic_output_does_not_send_after_take(
    db: Any, api: Any, request: pytest.FixtureRequest, kind: str,
) -> None:
    sender = Sender()
    with respx.mock:
        conversation_id, _ = await enqueue(db, kind)
        await take(api, conversation_id)
        before = await snapshot(db)
        assert before["conversation"][0]["state"] == "HUMAN_ACTIVE"
        assert before["conversation"][0]["bot_enabled"] is False
        await process_outbox_once(db, sender)
        after = await snapshot(db)
    evidence(request, before=before, after=after, sends=sender.sends, uploads=sender.uploads)
    assert sender.sends == []
    assert after["outbox"][0]["status"] == "SUPPRESSED"
    assert after["message"] == before["message"]


@pytest.mark.parametrize("kind", ["TEXT", "DOCUMENT"])
async def test_active_automatic_output_keeps_sending(
    db: Any, request: pytest.FixtureRequest, kind: str,
) -> None:
    sender = Sender()
    with respx.mock:
        await enqueue(db, kind)
        await process_outbox_once(db, sender)
        after = await snapshot(db)
    evidence(request, after=after, sends=sender.sends, uploads=sender.uploads)
    assert len(sender.sends) == 1 and sender.sends[0]["kind"] == kind
    assert after["outbox"][0]["status"] == "SENT"
    assert len(after["message"]) == 2


async def test_authorized_human_output_keeps_sending(
    db: Any, api: Any, request: pytest.FixtureRequest,
) -> None:
    from tests.remediation.r8.helpers import seed_case

    client, actors = api
    sender = Sender()
    with respx.mock:
        conversation_id, _ = await seed_case(db, pending=False)
        await take(api, conversation_id)
        response = await client.post(f"/admin/conversations/{conversation_id}/messages",
                                     headers=actors["A"]["headers"],
                                     json={"text": "Respuesta humana sintetica R9"})
        assert response.status_code == 200, "Real authorized reply precondition"
        before = await snapshot(db)
        assert before["outbox"][0]["payload"]["agent"] is True
        await process_outbox_once(db, sender)
        after = await snapshot(db)
    evidence(request, before=before, after=after, sends=sender.sends)
    assert len(sender.sends) == 1
    assert after["outbox"][0]["status"] == "SENT"
    assert len(after["message"]) == 2

"""H01 persisted-row reproductions, compatible with the uncorrected R1 product."""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import text

from app.channel import inbound
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.http_doubles import unrecognized_extraction_response
from tests.integration.helpers import whatsapp_message_payload
from tests.remediation.test_r1_outbox import db as db
from tests.remediation.test_r1_outbox import evidence

pytestmark = pytest.mark.asyncio


def payload(*ids: str) -> dict[str, Any]:
    result = json.loads(whatsapp_message_payload(ids[0], text="Hola"))
    messages = result["entry"][0]["changes"][0]["value"]["messages"]
    for external_id in ids[1:]:
        extra = copy.deepcopy(messages[0])
        extra["id"] = external_id
        messages.append(extra)
    return result


def greeting_http(router: respx.MockRouter) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "messages" in body
        if body["messages"][1]["content"].startswith("Extrae el tipo de celebraci"):
            return unrecognized_extraction_response(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "primary_intent": "GREETING",
                                    "sub_intent": None,
                                    "requested_action": None,
                                    "needs_confirmation": False,
                                    "handoff_reason": None,
                                    "priority": "NORMAL",
                                    "confidence": 0.99,
                                    "entities": {},
                                    "needs_human": False,
                                    "reasoning_code": "R2_SYNTHETIC_GREETING",
                                }
                            )
                        }
                    }
                ]
            },
        )

    return router.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=respond)


async def rows(db: Any) -> dict[str, Any]:
    async with db() as session:
        return {
            name: [
                dict(r)
                for r in (
                    await session.execute(text(f'SELECT * FROM "{name}" ORDER BY id'))
                ).mappings()
            ]
            for name in ("webhook_event", "message", "outbox", "audit_event")
        }


@pytest.mark.parametrize(
    "boundary", ["normal", "message_commit", "partial_message_commit", "classified"]
)
async def test_committed_message_is_not_completion(
    db: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    data = (
        payload("r2.first", "r2.second")
        if boundary == "partial_message_commit"
        else payload("r2.first")
    )
    event_id = await inbound.store_webhook_event(data, db, None)
    if boundary in {"message_commit", "partial_message_commit"}:
        persisted = await inbound.persist_payload_phase_a(payload("r2.first"), db, None)
        assert len(persisted) == 1
    with respx.mock(assert_all_called=False) as router:
        greeting_http(router)
        if boundary == "classified":
            original = inbound.orchestrate_inbound_message

            async def interrupt_after_classification(*args: Any, **kwargs: Any) -> None:
                raise asyncio.CancelledError("synthetic interruption after classification")

            monkeypatch.setattr(
                inbound, "orchestrate_inbound_message", interrupt_after_classification
            )
            with pytest.raises(asyncio.CancelledError):
                await inbound.process_webhook_event(event_id, db)
            monkeypatch.setattr(inbound, "orchestrate_inbound_message", original)
        before = await rows(db)
        await inbound.process_webhook_event(event_id, db)
        after = await rows(db)
    evidence(request, before=before, after=after)
    expected = 2 if boundary == "partial_message_commit" else 1
    assert len(after["message"]) == expected
    assert {r["message_id"] for r in after["outbox"]} == {r["id"] for r in after["message"]}
    assert len(after["outbox"]) == expected
    assert after["webhook_event"][0]["status"] == "PROCESSED"

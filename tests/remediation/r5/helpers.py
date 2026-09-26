"""Synthetic media through the existing parser and durable SQL protocol."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.channel import inbound, inbox
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.remediation.r3.helpers import snapshot as previous_snapshot
from tests.remediation.r4.helpers import message_payload


def media_payload(
    kind: str = "image", caption: str | None = None, external_id: str = "r5.synthetic"
) -> dict[str, Any]:
    payload = message_payload(external_id)
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = kind
    content: Any = {
        "id": "r5.synthetic.media",
        "mime_type": "application/pdf" if kind == "document" else "image/jpeg",
        "sha256": "a" * 64,
    }
    if caption is not None:
        content["caption"] = caption
    message[kind] = content
    return payload


async def prepare(
    db: Any,
    *,
    kind: str = "image",
    caption: str | None = None,
    state: str = "HUMAN_ACTIVE",
    enabled: bool = False,
    payment: str | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    event = await inbound.store_webhook_event(data or media_payload(kind, caption), db, None)
    ids = await inbox.expand_event(db, event, datetime.now(UTC))
    assert len(ids) == 1, "Parser and durable intake precondition"
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state, conversation.bot_enabled = state, enabled
        conversation.pending_action = "WAIT_FOR_HUMAN" if state != "BOT_ACTIVE" else None
        customer = await session.get(Customer, conversation.customer_id)
        customer.full_name = "Cliente Sintetico R5"
        if payment:
            session.add(Handoff(
                conversation_id=conversation.id, status=payment, reason="PAYMENT_REVIEW",
                priority="NORMAL", summary="Caso sintetico R5", assigned_to="Asesor sintetico",
            ))
    return event


async def snapshot(db: Any) -> dict[str, Any]:
    result = await previous_snapshot(db)
    async with db() as session:
        result["payment_evidence"] = [
            dict(row) for row in (
                await session.execute(text("SELECT * FROM payment_evidence ORDER BY id"))
            ).mappings()
        ]
    return result


def assert_passive(before: dict[str, Any], final: dict[str, Any], captured: bool) -> None:
    assert final["message"] == before["message"]
    assert final["outbox"] == before["outbox"]
    assert final["conversation"] == before["conversation"]
    assert final["ai_execution"] == before["ai_execution"]
    assert len(final["handoff"]) == len(before["handoff"])
    assert len(final["payment_evidence"]) == int(captured)
    for old, new in zip(before["handoff"], final["handoff"], strict=True):
        for key in old:
            if captured and key in {"summary", "priority"}:
                continue
            assert new[key] == old[key], key
    if captured:
        item = final["payment_evidence"][0]
        msg = final["message"][0]
        assert item["message_id"] == msg["id"]
        assert item["customer_id"] == msg["customer_id"]
        assert item["conversation_id"] == msg["conversation_id"]
        assert item["download_status"] == "PENDING"
        assert item["review_status"] == "PENDING_REVIEW"
        assert item["storage_path"] is None and item["verified_sha256"] is None
        assert final["handoff"][0]["priority"] == "URGENT"
        assert f'evidencia #{item["id"]}' in final["handoff"][0]["summary"]
        for action in ("PAYMENT_EVIDENCE_CREATED", "HANDOFF_PRIORITY_RAISED"):
            assert sum(a["action"] == action for a in final["audit_event"]) == 1
    assert final["inbox_job"][0]["status"] == "COMPLETED"


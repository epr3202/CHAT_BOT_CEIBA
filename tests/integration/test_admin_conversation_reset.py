from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.channel.models import InboxJob, Message, Outbox
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.main import app
from tests.integration.helpers import login_headers
from tests.integration.test_admin_agents_crud import client as client

PHONE = "+573001112233"


async def seed_reset_state(inbox_status: str = "PENDING") -> dict[str, object]:
    async with app.state.db_sessionmaker() as session, session.begin():
        customer = Customer(phone_number=PHONE, full_name="Cliente de prueba")
        session.add(customer)
        await session.flush()
        conversation = Conversation(
            customer_id=customer.id, channel="WHATSAPP", state="COLLECTING_EVENT_DATA",
            pending_action="COLLECT_EVENT_TYPE", pending_fields=["event_type"],
            pending_confirmation={"field": "event_type"}, last_question_code="RESP-TEST",
            visit_draft={"reason": "prueba"}, last_intent="QUOTE_REQUEST",
            failed_understanding_count=2, services_failed_understanding_count=1,
            bot_enabled=False,
        )
        session.add(conversation)
        await session.flush()
        message = Message(
            external_message_id=f"reset-{uuid4()}", conversation_id=conversation.id,
            customer_id=customer.id, channel="WHATSAPP", direction="INBOUND",
            message_type="text", content={"text": {"body": "prueba"}},
        )
        session.add(message)
        await session.flush()
        handoff = Handoff(
            conversation_id=conversation.id, status="PENDING", reason="OTHER", summary="Prueba",
        )
        job = InboxJob(
            conversation_id=conversation.id, message_id=message.id, status=inbox_status,
            claim_token=uuid4() if inbox_status in {"PROCESSING", "EXTERNAL"} else None,
            claimed_at=datetime.now(UTC) if inbox_status in {"PROCESSING", "EXTERNAL"} else None,
        )
        outbox = Outbox(
            conversation_id=conversation.id, message_id=message.id, channel="WHATSAPP",
            recipient_phone_number=PHONE, payload={"text": {"body": "Pendiente"}},
            status="PENDING",
            delivery_context={"mode": "AUTO", "epoch": str(conversation.automation_epoch)},
        )
        session.add_all([handoff, job, outbox])
        await session.flush()
        return {"customer": customer.id, "conversation": conversation.id,
                "handoff": handoff.id, "job": job.id, "outbox": outbox.id,
                "epoch": conversation.automation_epoch}


async def snapshot() -> dict[str, list[dict]]:
    async with app.state.db_sessionmaker() as session:
        result = {}
        for model in (Customer, Conversation, Handoff, InboxJob, Outbox, Message, AuditEvent):
            rows = await session.execute(select(model.__table__).order_by(model.id))
            result[model.__tablename__] = [dict(row) for row in rows.mappings()]
        return result


async def test_reset_dry_run_counts_without_changing_database(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    ids = await seed_reset_state()
    before = await snapshot()
    response = await client.post(
        "/admin/conversations/reset", headers=headers,
        json={"phone_number": PHONE, "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["phone_number"] == PHONE
    assert body["customer_id"] == ids["customer"]
    for field in ("conversations_found", "conversations_closed", "handoffs_resolved",
                  "inbox_jobs_completed", "pending_outbox_suppressed"):
        assert body[field] == 1
    assert body["customer_name_cleared"] is True
    assert await snapshot() == before


@pytest.mark.parametrize("inbox_status", ["PENDING", "FAILED", "REVIEW"])
async def test_reset_closes_and_fences_work_and_audits(
    client: AsyncClient, inbox_status: str,
) -> None:
    headers = await login_headers(client, "90000000")
    ids = await seed_reset_state(inbox_status)
    before = await snapshot()
    response = await client.post(
        "/admin/conversations/reset", headers=headers,
        json={"phone_number": PHONE, "dry_run": False, "reason": "prueba"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["inbox_jobs_completed"] == body["pending_outbox_suppressed"] == 1
    assert body["request_id"].startswith("admin-reset-")
    async with app.state.db_sessionmaker() as session:
        conversation = await session.get(Conversation, ids["conversation"])
        assert conversation.state == "CLOSED"
        assert conversation.pending_action is None
        assert conversation.pending_fields == []
        assert conversation.pending_confirmation is None
        assert conversation.visit_draft is None
        assert conversation.last_question_code is None
        assert conversation.bot_enabled is True
        assert conversation.assigned_agent_id is None
        assert conversation.automation_epoch != ids["epoch"]
        handoff = await session.get(Handoff, ids["handoff"])
        assert handoff.status == "RESOLVED"
        assert handoff.resolved_at is not None
        job = await session.get(InboxJob, ids["job"])
        assert job.status == "COMPLETED"
        assert job.last_error == "RESET_BY_ADMIN"
        assert job.claim_token is None
        assert (await session.get(Outbox, ids["outbox"])).status == "PENDING"
        assert (await session.get(Customer, ids["customer"])).full_name is None
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "ADMIN_CONVERSATION_RESET")
        )
        assert audit is not None
        assert audit.actor == "Admin"
        assert audit.reason == "Admin conversation reset"
        assert audit.new_value["reason"] == "prueba"
        assert audit.request_id == body["request_id"]
        assert audit.old_value["customer"]["full_name"] == "Cliente de prueba"
    after = await snapshot()
    assert after["message"] == before["message"]
    assert after["outbox"] == before["outbox"]
    assert after["audit_event"][:-1] == before["audit_event"]


async def test_unknown_phone_is_empty_and_invalid_phone_is_422(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    response = await client.post(
        "/admin/conversations/reset", headers=headers, json={"phone_number": PHONE},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] is None
    for field in ("conversations_found", "conversations_closed", "handoffs_resolved",
                  "inbox_jobs_completed", "pending_outbox_suppressed"):
        assert body[field] == 0
    invalid = await client.post(
        "/admin/conversations/reset", headers=headers, json={"phone_number": "invalid"},
    )
    assert invalid.status_code == 422


@pytest.mark.parametrize("inbox_status", ["PROCESSING", "EXTERNAL"])
async def test_reset_rejects_inflight_processing_without_mutation(
    client: AsyncClient, inbox_status: str,
) -> None:
    headers = await login_headers(client, "90000000")
    await seed_reset_state(inbox_status)
    before = await snapshot()
    response = await client.post(
        "/admin/conversations/reset", headers=headers,
        json={"phone_number": PHONE, "dry_run": False, "reason": "prueba"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Conversation is being processed; retry shortly"
    assert await snapshot() == before


async def test_agent_cannot_reset_conversation(client: AsyncClient) -> None:
    headers = await login_headers(client, "80000000")
    response = await client.post(
        "/admin/conversations/reset", headers=headers, json={"phone_number": PHONE},
    )
    assert response.status_code == 403


async def test_execute_reset_requires_nonempty_reason(client: AsyncClient) -> None:
    headers = await login_headers(client, "90000000")
    for reason in (None, "", "   "):
        response = await client.post(
            "/admin/conversations/reset", headers=headers,
            json={"phone_number": PHONE, "dry_run": False, "reason": reason},
        )
        assert response.status_code == 422

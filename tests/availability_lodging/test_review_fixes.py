import json
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.channel.inbound import process_whatsapp_webhook
from app.config.settings import Settings
from app.conversation.fixed_price_booking import SELF_SERVICE_BOOKING_REASON
from app.conversation.models import Conversation, KnowledgeEntry
from app.orchestrator import service
from tests.availability_lodging.helpers import AGENDA_ERROR, seed_booking
from tests.booking_conversation.helpers import code, draft_of
from tests.integration.helpers import whatsapp_message_payload
from tests.visit_booking_guard.helpers import PHONE, Harness


async def test_V_classify_message_after_fallback_enters_deterministic_booking(
    harness: Harness,
) -> None:
    await harness.seed(pending="CLASSIFY_MESSAGE")
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        (await session.get(Conversation, conversation.id)).last_question_code = "RESP-FALLBACK-004"
    context = {
        "state": "BOT_ACTIVE",
        "bot_enabled": True,
        "pending_action": "CLASSIFY_MESSAGE",
        "pending_confirmation": None,
        "last_question_code": "RESP-FALLBACK-004",
        "booking_event": {"event_type": "ROMANTIC_DINNER", "plans": []},
    }
    result = service.deterministic_booking_or_catalog_classification(
        "quiero reservar cena romantica",
        context,
        Settings(_env_file=None, SELF_SERVICE_BOOKING_ENABLED=True),
    )
    assert result is not None
    assert result.reasoning_code == SELF_SERVICE_BOOKING_REASON
    await harness.send("quiero reservar cena romantica")
    await harness.assert_completed()
    assert harness.classifier_calls == []
    assert harness.codes == [code("PLAN")]
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_PLAN"


@pytest.mark.parametrize(
    "message,pending_confirmation",
    [
        ("quiero reservar cena romantica", {"field": "event_type"}),
        ("quiero hablar con un asesor para reservar cena romantica", None),
    ],
    ids=["pending-confirmation", "explicit-advisor"],
)
def test_V_confirmation_and_explicit_advisor_defer_to_classifier(
    message: str, pending_confirmation: dict[str, str] | None
) -> None:
    result = service.deterministic_booking_or_catalog_classification(
        message,
        {
            "state": "BOT_ACTIVE",
            "bot_enabled": True,
            "pending_action": "CLASSIFY_MESSAGE",
            "pending_confirmation": pending_confirmation,
            "last_question_code": "RESP-FALLBACK-004",
            "booking_event": {"event_type": "ROMANTIC_DINNER", "plans": []},
        },
        Settings(_env_file=None, SELF_SERVICE_BOOKING_ENABLED=True),
    )
    assert result is None


async def test_R_agenda_error_backup_notice_keeps_primary_request_id(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_booking(harness)
    before = draft_of(await harness.conversation())
    async with harness.db.begin() as session:
        entry = await session.scalar(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.code == AGENDA_ERROR)
            .order_by(KnowledgeEntry.version.desc())
            .limit(1)
        )
        entry.status = "DRAFT"
    attempts: list[tuple[str, str | None]] = []
    enqueue = service.enqueue_template

    async def observe(*args: Any, **kwargs: Any) -> None:
        attempts.append((args[5], kwargs.get("request_id")))
        await enqueue(*args, **kwargs)

    monkeypatch.setattr(service, "enqueue_template", observe)
    harness.calendar.raise_on.add("list_events")
    request_id = uuid4()
    payload = json.loads(
        whatsapp_message_payload(
            f"review.{request_id.hex}",
            phone=PHONE.removeprefix("+"),
            text="17 de noviembre 7 pm",
        )
    )
    await process_whatsapp_webhook(payload, harness.db, request_id=request_id)
    await harness.assert_completed()
    assert len(attempts) == 2
    assert attempts[0][0] == AGENDA_ERROR
    assert attempts[1][0] in {"RESP-HANDOFF-001", "RESP-HANDOFF-002"}
    assert attempts[0][1] == str(request_id)
    assert attempts[1][1] == attempts[0][1]
    render_failure = next(
        row for row in await harness.rows(AuditEvent) if row.action == "TEMPLATE_RENDER_FAILED"
    )
    assert render_failure.request_id == attempts[1][1]
    assert draft_of(await harness.conversation()) == before

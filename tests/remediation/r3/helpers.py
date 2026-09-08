"""Strict synthetic provider boundaries and real R2 persistence for H04."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx
import respx
from sqlalchemy import text

from app.ai.prompts import get_intent_prompt
from app.ai.prompts.event_type_extraction_v1 import event_type_extraction_prompt
from app.ai.prompts.services_v1 import services_classification_prompt
from app.channel import inbound, inbox
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.event.models import Event
from app.lead.models import Lead
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.remediation.r2.test_r2_inbox import snapshot as inbox_snapshot
from tests.remediation.r2.test_r2_recovery import payload
from tests.unit.test_ai_client import completion_payload, valid_classification

MAIN = "INTENT_CLASSIFICATION"
EXTRACT = "EVENT_TYPE_EXTRACTION"
SERVICES = "SERVICES_CLASSIFICATION"
SENSITIVE = (
    "R3_SYNTHETIC_PRIVATE body=synthetic headers=synthetic https://user:secret@example.invalid"
)


class Provider:
    def __init__(self, router: respx.MockRouter, outcomes: dict[str, list[Any]]) -> None:
        self.outcomes = {task: list(values) for task, values in outcomes.items()}
        self.calls: Counter[str] = Counter()
        self.timeouts: list[Any] = []
        self.route = router.post("https://openrouter.ai/api/v1/chat/completions").mock(
            side_effect=self.respond
        )

    def respond(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        prompts = {
            get_intent_prompt(get_settings().ai_prompt_version).content: MAIN,
            event_type_extraction_prompt(): EXTRACT,
            services_classification_prompt(): SERVICES,
        }
        task = prompts[body["messages"][0]["content"]]
        instruction = {
            MAIN: "Clasifica el siguiente",
            EXTRACT: "Extrae el tipo",
            SERVICES: "Clasifica los servicios",
        }[task]
        assert body["messages"][1]["content"].startswith(instruction)
        self.calls[task] += 1
        self.timeouts.append(request.extensions.get("timeout"))
        assert self.outcomes.get(task), "Unexpected task or attempt: " + task
        result = self.outcomes[task].pop(0)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=completion_payload(result))

    def exhausted(self) -> None:
        assert all(not values for values in self.outcomes.values()), self.outcomes


async def prepare(
    db: Any,
    *,
    external_id: str = "r3.synthetic",
    state: str = "BOT_ACTIVE",
    pending: str | None = None,
    enabled: bool = True,
) -> int:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    data = payload(external_id)
    data["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = (
        "consulta sintetica zzz"
    )
    event_id = await inbound.store_webhook_event(data, db, None)
    await inbox.expand_event(db, event_id, datetime.now(UTC))
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, 1)
        conversation.state, conversation.bot_enabled = state, enabled
        conversation.pending_action = pending
        if pending in {"COLLECT_EVENT_TYPE", "COLLECT_SERVICES"}:
            lead = Lead(customer_id=conversation.customer_id, channel="WHATSAPP")
            session.add(lead)
            await session.flush()
            session.add(
                Event(
                    lead_id=lead.lead_id,
                    event_type="BIRTHDAY" if pending == "COLLECT_SERVICES" else None,
                )
            )
            conversation.active_lead_id = lead.lead_id
            conversation.last_question_code = (
                "RESP-EVENT-DATA-006"
                if pending == "COLLECT_SERVICES"
                else "RESP-EVENT-DATA-013"
            )
            conversation.pending_fields = [
                "services" if pending == "COLLECT_SERVICES" else "event_type"
            ]
    return event_id


async def snapshot(db: Any) -> dict[str, Any]:
    result = await inbox_snapshot(db)
    async with db() as session:
        for table in ("ai_execution", "event_service_request", "appointment", "quote_request"):
            result[table] = [
                dict(r)
                for r in (await session.execute(text(f'SELECT * FROM "{table}"'))).mappings()
            ]
    return result


def valid() -> dict[str, Any]:
    return valid_classification()

from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import respx
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channel import inbound, inbox
from app.channel.models import InboxJob, Message, Outbox
from app.config.settings import get_settings
from app.conversation.models import Conversation, KnowledgeEntry
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from tests.unit.test_ai_client import completion_payload, valid_classification

NOW = datetime(2026, 10, 7, 15, tzinfo=UTC)
BOGOTA = ZoneInfo("America/Bogota")
PHONE = "+573000000701"
TWIN_PHONE = "+573000000702"
FIXTURES = Path(__file__).parents[1] / "fixtures" / "audio"
MODEL = "google/gemini-2.5-flash"
TOO_LONG = "RESP-AUDIO-TOO-LONG-001"
WRITTEN = "RESP-AUDIO-WRITTEN-CONFIRM-001"
COMMIT_ACTIONS = (
    "CONFIRM_BOOKING",
    "CONFIRM_APPOINTMENT",
    "CONFIRM_RESCHEDULE",
    "CONFIRM_VISIT_CANCELLATION",
    "CONFIRM_QUOTE_REQUEST",
)
CONTEXT_FIELDS = (
    "state",
    "pending_action",
    "pending_confirmation",
    "booking_draft",
    "visit_draft",
    "failed_understanding_count",
    "services_failed_understanding_count",
    "last_question_code",
)


def new_module(name: str) -> Any:
    assert importlib.util.find_spec(name) is not None, f"W2-c requiere {name}"
    return importlib.import_module(name)


async def require_transcription_table(db: async_sessionmaker[AsyncSession]) -> None:
    async with db() as session:
        exists = await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='message_transcription')"
            )
        )
    assert exists, "W2-c requiere la migración message_transcription"


def context_of(row: Conversation, *, last_question: bool = True) -> dict[str, Any]:
    return {
        name: getattr(row, name)
        for name in CONTEXT_FIELDS
        if last_question or name != "last_question_code"
    }


@dataclass
class AudioHarness:
    db: async_sessionmaker[AsyncSession]
    router: respx.MockRouter
    sessions: list[AsyncSession]
    transcript: str = "hola"
    is_speech: bool = True
    language: str | None = "es"
    asr_failure: str | None = None
    declared_size: int | None = None
    fixture: str = "ok_5s.ogg"
    mime: str = "audio/ogg; codecs=opus"
    asr_requests: list[dict[str, Any]] = field(default_factory=list)
    classifier_requests: list[dict[str, Any]] = field(default_factory=list)
    metadata_calls: int = 0
    download_calls: int = 0
    check_transactions: bool = False
    after_asr: Any = None
    codes: list[tuple[int, str]] = field(default_factory=list)
    turn: int = 0

    @property
    def content(self) -> bytes:
        return (FIXTURES / self.fixture).read_bytes()

    @property
    def media_url(self) -> str:
        return "https://audio-fixture.invalid/synthetic.ogg"

    @property
    def media_id(self) -> str:
        return "audio-synthetic-object"

    async def no_transaction(self) -> None:
        assert not any(session.in_transaction() for session in self.sessions), (
            "HTTP iniciado con transacción del inbox abierta"
        )
        try:
            async with self.db() as other, other.begin():
                for model in (Customer, Conversation, InboxJob, Message):
                    await other.execute(select(model).with_for_update(nowait=True))
        except DBAPIError as error:
            raise AssertionError("HTTP iniciado con locks retenidos") from error

    async def metadata(self, _request: httpx.Request) -> httpx.Response:
        import hashlib

        if self.check_transactions:
            await self.no_transaction()
        self.metadata_calls += 1
        return httpx.Response(
            200,
            json={
                "url": self.media_url,
                "mime_type": self.mime,
                "sha256": hashlib.sha256(self.content).hexdigest(),
                "file_size": len(self.content)
                if self.declared_size is None
                else self.declared_size,
            },
        )

    async def download(self, _request: httpx.Request) -> httpx.Response:
        if self.check_transactions:
            await self.no_transaction()
        self.download_calls += 1
        return httpx.Response(200, content=self.content, headers={"Content-Type": self.mime})

    async def provider(self, request: httpx.Request) -> httpx.Response:
        if self.check_transactions:
            await self.no_transaction()
        payload = json.loads(request.content)
        audio = any(
            isinstance(message.get("content"), list)
            and any(part.get("type") == "input_audio" for part in message["content"])
            for message in payload.get("messages", [])
        )
        if audio:
            self.asr_requests.append(payload)
            if self.asr_failure == "timeout":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            if self.asr_failure == "500":
                return httpx.Response(500, json={"error": {"message": "synthetic failure"}})
            if self.asr_failure == "json":
                response = completion_payload("{")
            elif self.asr_failure == "schema":
                response = completion_payload({"transcript": "hola", "is_speech": "true"})
            else:
                response = completion_payload(
                    {
                        "transcript": self.transcript,
                        "is_speech": self.is_speech,
                        "language": self.language,
                    }
                )
            response["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            if self.after_asr:
                await self.after_asr()
            return httpx.Response(200, json=response)
        self.classifier_requests.append(payload)
        # Deterministic matchers retain priority; every actual model call gets a
        # conservative synthetic classification, never authority to commit actions.
        return httpx.Response(200, json=completion_payload(valid_classification()))

    def register_http(self) -> None:
        settings = get_settings()
        self.router.get(
            "https://graph.facebook.com/" + settings.meta_graph_api_version + "/" + self.media_id
        ).mock(side_effect=self.metadata)
        self.router.get(self.media_url).mock(side_effect=self.download)
        self.router.post(settings.openrouter_base_url.rstrip("/") + "/chat/completions").mock(
            side_effect=self.provider
        )

    async def seed(self, phone: str = PHONE, **values: Any) -> int:
        async with self.db() as session, session.begin():
            customer = Customer(phone_number=phone, full_name="Mateo Prueba")
            session.add(customer)
            await session.flush()
            lead = Lead(customer_id=customer.id, channel="WHATSAPP", lead_status="QUALIFYING")
            session.add(lead)
            await session.flush()
            session.add(Event(lead_id=lead.lead_id, event_type="ROMANTIC_DINNER"))
            row = Conversation(
                customer_id=customer.id,
                channel="WHATSAPP",
                state="BOT_ACTIVE",
                active_lead_id=lead.lead_id,
            )
            for name, value in values.items():
                setattr(row, name, value)
            session.add(row)
            await session.flush()
            return row.id

    def payload(
        self,
        *,
        audio: bool = True,
        body: str | None = None,
        phone: str = PHONE,
        external_id: str | None = None,
        wrong_hash: bool = False,
        age_days: int = 0,
    ) -> dict[str, Any]:
        import hashlib

        self.turn += 1
        kind = "audio" if audio else "text"
        content: dict[str, Any] = {"body": body or "hola"}
        if audio:
            content = {
                "id": self.media_id,
                "mime_type": self.mime,
                "voice": True,
                "sha256": "0" * 64 if wrong_hash else hashlib.sha256(self.content).hexdigest(),
            }
            if body is not None:
                content["caption"] = body
        message = {
            "from": phone.removeprefix("+"),
            "id": external_id or f"audio-g2-{self.turn}",
            "timestamp": str(int((datetime.now(UTC) - timedelta(days=age_days)).timestamp())),
            "type": kind,
            kind: content,
        }
        return {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "test-account",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": "123456789"},
                                "messages": [message],
                            },
                        }
                    ],
                }
            ],
        }

    async def send(self, **kwargs: Any) -> None:
        await inbound.process_whatsapp_webhook(self.payload(**kwargs), self.db, request_id=uuid4())

    async def rows(self, model: Any) -> list[Any]:
        async with self.db() as session:
            return list(await session.scalars(select(model)))

    async def conversation(self, conversation_id: int = 1) -> Conversation:
        async with self.db() as session:
            row = await session.get(Conversation, conversation_id)
        assert row is not None
        return row

    async def transcriptions(self) -> list[dict[str, Any]]:
        await require_transcription_table(self.db)
        async with self.db() as session:
            result = await session.execute(text("SELECT * FROM message_transcription ORDER BY id"))
            return [dict(row) for row in result.mappings()]

    async def response_codes(self, conversation_id: int = 1) -> list[str]:
        return [code for owner, code in self.codes if owner == conversation_id]

    async def assert_template(self, code: str, *, count: int = 1) -> None:
        outbox = await self.rows(Outbox)
        assert len(outbox) == count
        async with self.db() as session:
            template = await session.scalar(
                select(KnowledgeEntry)
                .where(
                    KnowledgeEntry.code == code,
                    KnowledgeEntry.status == "APPROVED",
                )
                .order_by(KnowledgeEntry.version.desc())
                .limit(1)
            )
        assert template is not None
        assert outbox[-1].payload["text"]["body"] == template.answer_template
        assert (await self.response_codes())[-1] == code

    async def assert_completed(self) -> None:
        jobs = await self.rows(InboxJob)
        assert jobs and all(row.status == "COMPLETED" for row in jobs)
        audio_ids = {row.id for row in await self.rows(Message) if row.message_type == "audio"}
        assert all(row.external_operation is None for row in jobs if row.message_id in audio_ids)

    async def claim(self, *, now: datetime | None = None) -> inbox.InboxClaim:
        claims = await inbox.claim_inbox_batch(self.db, now or datetime.now(UTC), 10)
        assert len(claims) == 1
        return claims[0]

    async def prepare(self, **kwargs: Any) -> inbox.InboxClaim:
        event_id = await inbound.store_webhook_event(self.payload(**kwargs), self.db, uuid4())
        await inbox.expand_event(self.db, event_id, datetime.now(UTC))
        return await self.claim()


def request_id() -> UUID:
    return uuid4()

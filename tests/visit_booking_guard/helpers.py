from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.calendar.adapter import BusyInterval, FakeCalendarAdapter
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import InboxJob, Outbox
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from tests.integration.helpers import whatsapp_message_payload
from tests.unit.test_ai_client import completion_payload, valid_classification

BOGOTA = ZoneInfo("America/Bogota")
TODAY = date(2026, 9, 29)
NOW = datetime(2026, 9, 29, 10, tzinfo=BOGOTA)
VISIT_DATE = date(2026, 10, 7)
SLOTS = [time(8), time(9), time(10), time(11)]
PHONE = "+573000000189"  # Synthetic; the incident's real number is not a fixture.

# Verbatim customer messages from conversation 189; do not correct spelling/case.
ROMANTIC_INFO = "Quiero informacion sobre citas romanticas"
BOOK_ABSOLUTE = "me gustria agendar para el miercoles 7 de octubre"
DATE_TIME = "7 de octubre a las 8 am"
TIME_ONLY = "08:00"
ATTENDEES = "3"
REASON = "si una boda"
NAME = "Emerson"
CONFIRM = "Si"


class ObservedCalendar(FakeCalendarAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.queried_dates: list[date] = []

    async def get_busy_intervals(
        self, target_date: date, calendar_ids: Iterable[str]
    ) -> list[BusyInterval]:
        self.queried_dates.append(target_date)
        return await super().get_busy_intervals(target_date, calendar_ids)


@dataclass
class Harness:
    db: async_sessionmaker[AsyncSession]
    calendar: ObservedCalendar
    classifier_calls: list[dict[str, Any]] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    ai_result: dict[str, Any] = field(default_factory=valid_classification)
    turn: int = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.classifier_calls.append(json.loads(request.content))
        return httpx.Response(200, json=completion_payload(self.ai_result))

    async def seed(
        self,
        event_type: str | None = "ROMANTIC_DINNER",
        *,
        with_lead: bool = True,
        state: str = "BOT_ACTIVE",
        pending: str | None = None,
        draft: dict[str, Any] | None = None,
        full_name: str | None = NAME,
    ) -> None:
        async with self.db() as session, session.begin():
            customer = Customer(phone_number=PHONE, full_name=full_name)
            session.add(customer)
            await session.flush()
            lead = None
            if with_lead:
                lead = Lead(customer_id=customer.id, channel="WHATSAPP", lead_status="QUALIFYING")
                session.add(lead)
                await session.flush()
                session.add(Event(lead_id=lead.lead_id, event_type=event_type))
            session.add(
                Conversation(
                    customer_id=customer.id,
                    channel="WHATSAPP",
                    state=state,
                    active_lead_id=lead.lead_id if lead else None,
                    pending_action=pending,
                    visit_draft=draft,
                )
            )

    async def send(self, body: str, *, intent: str = "UNKNOWN", confidence: float = 0.95) -> None:
        self.turn += 1
        self.codes.clear()
        self.ai_result = dict(
            valid_classification(),
            primary_intent=intent,
            confidence=confidence,
            requested_action=None,
            reasoning_code="G2_INCIDENT_189",
        )
        payload = json.loads(
            whatsapp_message_payload(
                f"g2.189.{self.turn}",
                phone=PHONE.removeprefix("+"),
                text=body,
            )
        )
        await process_whatsapp_webhook(payload, self.db, request_id=f"g2.189.{self.turn}")

    async def rows(self, model: Any) -> list[Any]:
        async with self.db() as session:
            return list(await session.scalars(select(model)))

    async def conversation(self) -> Conversation:
        rows = await self.rows(Conversation)
        assert len(rows) == 1
        return rows[0]

    async def assert_completed(self) -> None:
        jobs = await self.rows(InboxJob)
        assert jobs and all(job.status == "COMPLETED" for job in jobs), [
            (job.id, job.status, job.last_error) for job in jobs
        ]

    async def bodies(self) -> list[str]:
        return [row.payload["text"]["body"] for row in await self.rows(Outbox)]


def date_draft(**fields: Any) -> dict[str, Any]:
    return {"mode": "SCHEDULE", "resume": None, **fields}


def time_draft(**fields: Any) -> dict[str, Any]:
    return date_draft(
        visit_date=VISIT_DATE.isoformat(),
        offered_slots=[t.strftime("%H:%M") for t in SLOTS],
        **fields,
    )

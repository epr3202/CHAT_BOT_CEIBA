"""PR #49: existing confirmed booking survives reset and cannot be duplicated."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.admin.conversation_reset import reset_conversation_by_phone
from app.audit.models import AuditEvent
from app.channel.inbound import process_whatsapp_webhook
from app.channel.models import Outbox
from app.conversation.models import Conversation, KnowledgeEntry
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.lead.models import Lead
from app.reservation.models import Reservation
from data.knowledge_seed import CONDITIONAL_DRAFT_CODES, iter_seed_entries
from scripts.reset_local_conversation import reset_local_conversation
from tests.booking_conversation.helpers import selected_plan
from tests.clock import FreezeAppClock
from tests.integration.helpers import login_headers, whatsapp_message_payload
from tests.visit_booking_guard import helpers as visit_helpers
from tests.visit_booking_guard.helpers import BOGOTA, Harness

PHONE = "+573000008100"  # Synthetic identity with the incident's suffix only.
START = datetime(2026, 11, 7, 15, tzinfo=BOGOTA)
CODE = "RESP-BOOKING-DUPLICATE-001"
COPY = (
    "Ya tienes confirmada {plan_name} para el {date} a las {time}. "
    "Si quieres reservar otra fecha u hora, cuéntame cuál y la reviso."
)


@pytest.fixture(autouse=True)
async def approved_duplicate(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, freeze_app_clock: FreezeAppClock
) -> None:
    freeze_app_clock(datetime(2026, 10, 29, 10, tzinfo=BOGOTA))
    monkeypatch.setattr(visit_helpers, "PHONE", PHONE)
    async with harness.db.begin() as session:
        # Approval was explicitly confirmed by Emerson; runtime contracts use
        # an independent literal, while the seed contract below checks publication.
        session.add(
            KnowledgeEntry(
                code=CODE,
                category="Reservas",
                question_summary="Duplicado confirmado",
                answer_template=COPY,
                allowed_variables=["plan_name", "date", "time"],
                version=100,
                status="APPROVED",
            )
        )


async def existing_booking(
    harness: Harness, *, status: str = "RESERVED", other_customer: bool = False
) -> Reservation:
    await harness.seed()
    plan = await selected_plan(harness)
    async with harness.db.begin() as session:
        conversation = await session.scalar(select(Conversation))
        customer_id = conversation.customer_id
        event = await session.scalar(select(Event))
        lead_id = event.lead_id
        if other_customer:
            customer = Customer(phone_number="+573000008101", full_name="Otro cliente")
            session.add(customer)
            await session.flush()
            lead = Lead(customer_id=customer.id, channel="WHATSAPP")
            session.add(lead)
            await session.flush()
            event = Event(lead_id=lead.lead_id, event_type=plan.event_type)
            session.add(event)
            await session.flush()
            customer_id, lead_id = customer.id, lead.lead_id
        row = Reservation(
            lead_id=lead_id,
            event_id=event.event_id,
            customer_id=customer_id,
            conversation_id=None if other_customer else conversation.id,
            plan_id=plan.plan_id,
            status=status,
            starts_at=START,
            ends_at=START + timedelta(hours=3),
            price_cop=250000,
            amount_paid_cop=250000 if status == "RESERVED" else 0,
            payment_kind="FULL" if status == "RESERVED" else None,
        )
        session.add(row)
        await session.flush()
        return row


async def latest(harness: Harness) -> Conversation:
    async with harness.db() as session:
        return await session.scalar(select(Conversation).order_by(Conversation.id.desc()).limit(1))


async def send(harness: Harness, text: str) -> None:
    import json

    harness.turn += 1
    harness.codes.clear()
    payload = json.loads(
        whatsapp_message_payload(f"pr49.{harness.turn}", phone=PHONE.lstrip("+"), text=text)
    )
    await process_whatsapp_webhook(payload, harness.db, request_id=uuid4())
    await harness.assert_completed()


async def assert_blocked(harness: Harness, row: Reservation) -> None:
    assert harness.codes == [CODE]
    conversation = await latest(harness)
    assert conversation.pending_action == "SELECT_BOOKING_DATETIME"
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.bot_enabled is True
    draft = conversation.booking_draft
    assert draft["plan_id"] == str(row.plan_id)
    assert not {"date", "time", "date_confirmation", "checkout"}.intersection(draft)
    assert len(await harness.rows(Reservation)) == 1
    assert await harness.rows(Handoff) == []
    audits = [a for a in await harness.rows(AuditEvent) if a.action == "BOOKING_DUPLICATE_BLOCKED"]
    assert len(audits) == 1
    assert audits[0].new_value == {
        "reservation_id": str(row.reservation_id),
        "plan_code": "RITUAL_CORAZON",
        "starts_at": START.astimezone(UTC).isoformat(),
    }
    assert audits[0].actor == "SYSTEM" and audits[0].request_id
    bodies = [o.payload["text"]["body"] for o in await harness.rows(Outbox)]
    assert bodies[-1] == COPY.format(
        plan_name="Ritual del Corazón", date="7 de noviembre de 2026", time="15:00"
    )


async def test_R_literal_8100_reset_then_same_confirmed_booking(harness: Harness) -> None:
    row = await existing_booking(harness)
    async with harness.db.begin() as session:
        await reset_conversation_by_phone(
            session,
            raw_phone_number=PHONE,
            dry_run=False,
            actor="TEST_ADMIN",
            reason="Reproducir reset del incidente",
            request_id="pr49.reset",
        )
    await send(harness, "Quiero reservar Ritual del Corazón el 7 de noviembre de 2026 a las 3 pm")
    assert len(await harness.rows(Conversation)) == 2
    await assert_blocked(harness, row)


@pytest.mark.parametrize("hour", [14, 15, 17])
async def test_R_overlap_reports_existing_time_not_requested_time(
    harness: Harness, hour: int
) -> None:
    row = await existing_booking(harness)
    await send(
        harness, f"Quiero reservar Ritual del Corazón el 7 de noviembre de 2026 a las {hour}:00"
    )
    await assert_blocked(harness, row)


async def test_R_final_check_blocks_reservation_confirmed_after_proposal(harness: Harness) -> None:
    row = await existing_booking(harness, status="CANCELLED")
    await send(harness, "Quiero reservar Ritual del Corazón el 7 de noviembre de 2026 a las 3 pm")
    assert (await latest(harness)).pending_action == "CONFIRM_BOOKING"
    async with harness.db.begin() as session:
        saved = await session.get(Reservation, row.reservation_id)
        saved.status = "RESERVED"
        saved.amount_paid_cop = saved.price_cop
    await send(harness, "Sí")
    await assert_blocked(harness, row)


@pytest.mark.parametrize("case", ["adjacent_hour", "other_customer", "other_plan"])
async def test_V_nonduplicates_continue_normally(harness: Harness, case: str) -> None:
    await existing_booking(harness, other_customer=case == "other_customer")
    plan = "Romance entre Copas" if case == "other_plan" else "Ritual del Corazón"
    hour = "6 pm" if case == "adjacent_hour" else "3 pm"
    await send(harness, f"Quiero reservar {plan} el 7 de noviembre de 2026 a las {hour}")
    assert (await latest(harness)).pending_action == "CONFIRM_BOOKING"
    await send(harness, "Sí")
    rows = await harness.rows(Reservation)
    assert len(rows) == 2 and sum(r.status == "PAYMENT_PENDING" for r in rows) == 1
    assert CODE not in harness.codes
    assert not any(a.action == "BOOKING_DUPLICATE_BLOCKED" for a in await harness.rows(AuditEvent))


@pytest.mark.parametrize("status", ["PAYMENT_PENDING", "PAYMENT_REVIEW"])
async def test_V_pending_global_guard_remains(harness: Harness, status: str) -> None:
    await existing_booking(harness, status=status)
    await send(harness, "Quiero reservar Romance entre Copas el 8 de noviembre de 2026 a las 6 pm")
    assert harness.codes == ["RESP-BOOKING-PENDING-001"]
    assert (await latest(harness)).state == "WAITING_FOR_HUMAN"
    assert len(await harness.rows(Reservation)) == 1


async def test_R_unapproved_duplicate_template_uses_pending_handoff(harness: Harness) -> None:
    await existing_booking(harness)
    async with harness.db.begin() as session:
        session.add(
            KnowledgeEntry(
                code=CODE,
                category="Reservas",
                question_summary="No aprobada",
                answer_template=COPY,
                allowed_variables=["plan_name", "date", "time"],
                version=101,
                status="DRAFT",
            )
        )
    await send(harness, "Quiero reservar Ritual del Corazón el 7 de noviembre de 2026 a las 3 pm")
    assert harness.codes[-1] == "RESP-BOOKING-PENDING-001"
    assert (await latest(harness)).state == "WAITING_FOR_HUMAN"
    assert len(await harness.rows(Reservation)) == 1


def test_R_exact_template_published_approved_v1() -> None:
    entries = [entry for entry in iter_seed_entries() if entry.code == CODE]
    assert len(entries) == 1, "Falta la publicación aprobada por Leandro y confirmada por Emerson"
    assert entries[0].status == "APPROVED" and entries[0].version == 1
    assert entries[0].answer_template == COPY
    assert set(entries[0].allowed_variables) == {"plan_name", "date", "time"}
    assert CODE not in CONDITIONAL_DRAFT_CODES


@pytest.mark.parametrize("via", ["script", "panel"])
async def test_R_reset_clears_draft_and_reports_live_reservations(
    harness: Harness, api: AsyncClient, via: str
) -> None:
    row = await existing_booking(harness)
    async with harness.db.begin() as session:
        conversation = await session.get(Conversation, (await latest(harness)).id)
        conversation.booking_draft = {
            "plan_id": str(row.plan_id),
            "date": "2026-11-07",
            "time": "15:00",
        }
    if via == "script":
        summary: Any = await reset_local_conversation(harness.db, PHONE, dry_run=False)
        live = getattr(summary, "live_reservations", None)
    else:
        response = await api.post(
            "/admin/conversations/reset",
            headers=await login_headers(api, "90000000"),
            json={"phone_number": PHONE, "dry_run": False, "reason": "Prueba PR49"},
        )
        assert response.status_code == 200, response.text
        live = response.json().get("live_reservations")
    assert live and len(live) == 1
    assert live[0]["reservation_id"] == str(row.reservation_id)
    assert live[0]["status"] == "RESERVED"
    assert datetime.fromisoformat(live[0]["starts_at"]) == START
    assert (await latest(harness)).booking_draft is None
    audits = [
        a for a in await harness.rows(AuditEvent) if a.action == "RESET_LEFT_LIVE_RESERVATIONS"
    ]
    assert len(audits) == 1 and audits[0].new_value["reservations"] == live
    assert (await harness.rows(Reservation))[0].status == "RESERVED"

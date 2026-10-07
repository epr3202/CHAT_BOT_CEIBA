"""G2: the October 6 plan-selection incident, including an older pending request."""

from __future__ import annotations

import json
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from app.ai.models import AIExecution
from app.conversation.fixed_price_booking import BOOKING_ACTIONS
from app.conversation.knowledge import render_response
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.event.models import Event
from app.handoff.models import Handoff
from app.lead.models import Lead
from app.orchestrator import service as orchestrator
from app.plan.models import Plan
from app.reservation.models import Reservation
from scripts.load_plans import PLAN_SEED
from tests.booking_conversation.helpers import code, draft_of
from tests.booking_conversation.test_fixed_price_catalog_context_g2 import (
    PROPOSAL_CATALOG,
    ROMANTIC_CATALOG,
    classifier_output,
    literal_classifier,  # noqa: F401 -- register the literal HTTP classifier fixture
    seed_assets,
    send,
    text_bodies,
)
from tests.visit_booking_guard.helpers import BOGOTA, Harness

# Verbatim production transcript, conversation 206. G1 found no T2 ai_execution,
# so there is no production parsed_output to recreate in the HTTP double.
INCIDENT_T1 = "Hola Me gustaría agendar una pedida de mano para el 14"
INCIDENT_T2 = "Me interesa confesión bajo la luna"


@pytest.fixture(autouse=True)
def incident_clock(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    set_clock(monkeypatch, date(2026, 10, 6))


def set_clock(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    monkeypatch.setattr(
        orchestrator,
        "current_bogota_datetime",
        lambda: datetime.combine(today, time(10), tzinfo=BOGOTA),
    )


async def current_conversation(harness: Harness) -> Conversation:
    rows = [row for row in await harness.rows(Conversation) if row.state != "CLOSED"]
    assert len(rows) == 1
    return rows[0]


async def seed_older_pending_request(harness: Harness) -> UUID:
    """A separate, closed conversation still has this customer's unpaid request."""
    async with harness.db.begin() as session:
        customer = await session.scalar(select(Customer))
        plan = await session.scalar(select(Plan).where(Plan.code == "RITUAL_CORAZON"))
        assert customer is not None and plan is not None
        lead = Lead(customer_id=customer.id, channel="WHATSAPP", lead_status="QUALIFYING")
        session.add(lead)
        await session.flush()
        event = Event(lead_id=lead.lead_id, event_type="ROMANTIC_DINNER")
        previous = Conversation(
            customer_id=customer.id,
            channel="WHATSAPP",
            state="CLOSED",
            active_lead_id=lead.lead_id,
        )
        session.add_all([event, previous])
        await session.flush()
        start = datetime(2026, 9, 30, 19, tzinfo=BOGOTA)
        reservation = Reservation(
            lead_id=lead.lead_id,
            event_id=event.event_id,
            customer_id=customer.id,
            conversation_id=previous.id,
            plan_id=plan.plan_id,
            starts_at=start,
            ends_at=start + timedelta(minutes=plan.duration_minutes),
            price_cop=plan.price_cop,
            amount_paid_cop=0,
            status="PAYMENT_PENDING",
            calendar_status="NONE",
        )
        session.add(reservation)
        await session.flush()
        return reservation.reservation_id


async def assert_no_ai_or_handoff(harness: Harness) -> None:
    assert harness.classifier_calls == []
    assert await harness.rows(AIExecution) == []
    assert await harness.rows(Handoff) == []


async def assert_selected_plan(harness: Harness, plan_code: str) -> Plan:
    conversation = await current_conversation(harness)
    assert conversation.state == "COLLECTING_EVENT_DATA"
    draft = draft_of(conversation)
    plan = next(plan for plan in await harness.rows(Plan) if plan.code == plan_code)
    assert draft["plan_id"] == str(plan.plan_id)
    event = next(
        event
        for event in await harness.rows(Event)
        if event.lead_id == conversation.active_lead_id
    )
    assert event.event_type == plan.event_type
    await assert_no_ai_or_handoff(harness)
    return plan


async def assert_plan_options(harness: Harness, event_type: str) -> None:
    conversation = await current_conversation(harness)
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert conversation.pending_action == "SELECT_BOOKING_PLAN"
    assert harness.codes == [code("PLAN")]
    assert not draft_of(conversation).get("plan_id")
    plans = sorted(
        [
            plan
            for plan in await harness.rows(Plan)
            if plan.active and plan.event_type == event_type
        ],
        key=lambda plan: (plan.sort_order, plan.code),
    )
    body = (await text_bodies(harness))[-1]
    assert all(f"{index}. {plan.name}" in body for index, plan in enumerate(plans, 1))
    assert all(
        plan.name not in body
        for plan in await harness.rows(Plan)
        if not plan.active or plan.event_type != event_type
    )
    await assert_no_ai_or_handoff(harness)


@pytest.mark.parametrize("older_pending", [False, True])
async def test_g2_literal_incident_selects_proposal_and_preserves_catalog_date(
    harness: Harness, tmp_path: Path, older_pending: bool
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    if older_pending:
        await seed_older_pending_request(harness)

    await send(harness, INCIDENT_T1)
    conversation = await current_conversation(harness)
    assert harness.codes == ["RESP-EVENTS-PROPOSAL-001"]
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None
    assert conversation.pending_fields == []

    await send(harness, INCIDENT_T2)
    plan = await assert_selected_plan(harness, "CONFESION_LUNA")
    assert plan.price_cop == 900000
    conversation = await current_conversation(harness)
    assert conversation.pending_action == "SELECT_BOOKING_DATETIME"
    assert draft_of(conversation)["date"] == "2026-10-14"
    assert draft_of(conversation)["date_confirmation"] is True
    assert harness.codes == ["RESP-EVENT-DATA-003"]
    assert (await text_bodies(harness))[-1] == await render_response(
        harness.db, "RESP-EVENT-DATA-003", {"resolved_date": date(2026, 10, 14)}
    )

    await send(harness, "sí")
    assert (await current_conversation(harness)).pending_action == "SELECT_BOOKING_TIME"
    assert harness.codes == [code("TIME")]
    await assert_no_ai_or_handoff(harness)
    assert len(await harness.rows(Reservation)) == int(older_pending)


@pytest.mark.parametrize("prefix", ["me interesa ", "quiero ", "el de ", ""])
@pytest.mark.parametrize("accented", [False, True])
async def test_g2_proposal_name_variants_enter_booking_without_llm(
    harness: Harness, tmp_path: Path, prefix: str, accented: bool
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    name = "confesión bajo la luna" if accented else "confesion bajo la luna"
    await send(harness, prefix + name)
    await assert_selected_plan(harness, "CONFESION_LUNA")
    assert (await current_conversation(harness)).pending_action == "SELECT_BOOKING_DATETIME"
    assert harness.codes == [code("DATETIME")]


@pytest.mark.parametrize(
    "plan_code,plan_name,event_type,price",
    [(row[0], row[1], row[2], row[3]) for row in PLAN_SEED],
)
async def test_g2_all_eight_active_plans_select_with_catalog_event_context(
    harness: Harness,
    tmp_path: Path,
    plan_code: str,
    plan_name: str,
    event_type: str,
    price: int,
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG if event_type == "PROPOSAL" else ROMANTIC_CATALOG)
    name = "".join(
        character
        for character in unicodedata.normalize("NFD", plan_name)
        if not unicodedata.combining(character)
    )
    await send(harness, f"me interesa {name}")
    selected = await assert_selected_plan(harness, plan_code)
    assert selected.price_cop == price
    assert harness.codes == [code("DATETIME")]


@pytest.mark.parametrize(
    "message",
    [
        "me interesa Confesión bajo la Luna o Noche Inolvidable",
        "me interesa un plan desconocido",
        "quiero un plan que no existe",
        "el de otro nombre",
        "plan inexistente",
        "estrellas perdidas",
    ],
)
async def test_g2_ambiguous_or_unknown_plan_asks_existing_plan_list(
    harness: Harness, tmp_path: Path, message: str
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await seed_older_pending_request(harness)
    await send(harness, PROPOSAL_CATALOG)
    await send(harness, message)
    await assert_plan_options(harness, "PROPOSAL")


async def test_g2_homonymous_active_plans_require_selection(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    async with harness.db.begin() as session:
        session.add(
            Plan(
                code="SYNTHETIC_CONFESION_LUNA",
                name="Confesión bajo la Luna",
                event_type="PROPOSAL",
                price_cop=950000,
                duration_minutes=180,
                active=True,
                sort_order=99,
            )
        )
    await send(harness, PROPOSAL_CATALOG)
    await send(harness, INCIDENT_T2)
    await assert_plan_options(harness, "PROPOSAL")


@pytest.mark.parametrize("inactive", [False, True])
async def test_g2_plan_selection_stays_with_active_lead_event_type(
    harness: Harness, tmp_path: Path, inactive: bool
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    if inactive:
        async with harness.db.begin() as session:
            plan = await session.scalar(select(Plan).where(Plan.code == "CONFESION_LUNA"))
            assert plan is not None
            plan.active = False
    await send(harness, PROPOSAL_CATALOG)
    await send(harness, INCIDENT_T2 if inactive else "me interesa cinema y amor")
    await assert_plan_options(harness, "PROPOSAL")
    conversation = await current_conversation(harness)
    event = next(
        event
        for event in await harness.rows(Event)
        if event.lead_id == conversation.active_lead_id
    )
    assert event.event_type == "PROPOSAL"


@pytest.mark.parametrize(
    "today,day,candidate",
    [
        (date(2026, 10, 6), 14, date(2026, 10, 14)),
        (date(2026, 10, 6), 31, date(2026, 10, 31)),
        (date(2026, 10, 31), 14, date(2026, 11, 14)),
        (date(2026, 10, 31), 31, date(2026, 10, 31)),
        (date(2026, 11, 1), 31, date(2026, 12, 31)),
    ],
)
async def test_g2_catalog_day_without_month_survives_until_plan_confirmation(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    today: date,
    day: int,
    candidate: date,
) -> None:
    set_clock(monkeypatch, today)
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, f"Hola Me gustaría agendar una pedida de mano para el {day}")
    conversation = await current_conversation(harness)
    assert conversation.pending_action is None
    assert draft_of(conversation).get("date") == candidate.isoformat()
    assert draft_of(conversation).get("date_confirmation") is True
    await send(harness, INCIDENT_T2)
    await assert_selected_plan(harness, "CONFESION_LUNA")
    assert draft_of(await current_conversation(harness))["date"] == candidate.isoformat()
    assert harness.codes == ["RESP-EVENT-DATA-003"]
    assert (await text_bodies(harness))[-1] == await render_response(
        harness.db, "RESP-EVENT-DATA-003", {"resolved_date": candidate}
    )
    await send(harness, "sí")
    assert (await current_conversation(harness)).pending_action == "SELECT_BOOKING_TIME"
    assert harness.codes == [code("TIME")]
    await assert_no_ai_or_handoff(harness)


async def test_g2_romantic_cinema_and_love_regression(harness: Harness, tmp_path: Path) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, ROMANTIC_CATALOG)
    await send(harness, "me interesa cinema y amor")
    await assert_selected_plan(harness, "CINEMA_AMOR")
    assert harness.codes == [code("DATETIME")]


async def test_g2_informational_date_keeps_classifier_route(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    await send(harness, PROPOSAL_CATALOG)
    output = classifier_output(catalog=False)
    await send(harness, "el 7 de octubre es nuestro aniversario", output=output)
    executions = await harness.rows(AIExecution)
    assert len(harness.classifier_calls) == len(executions) == 1
    assert executions[0].parsed_output == json.loads(output)
    assert (await current_conversation(harness)).pending_action not in BOOKING_ACTIONS
    assert await harness.rows(Reservation) == []
    assert await harness.rows(Handoff) == []


async def test_g2_older_pending_request_still_blocks_final_creation(
    harness: Harness, tmp_path: Path
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await seed_assets(harness, tmp_path)
    prior_id = await seed_older_pending_request(harness)
    await send(harness, INCIDENT_T1)
    await send(harness, INCIDENT_T2)
    await assert_selected_plan(harness, "CONFESION_LUNA")
    await send(harness, "sí")
    await send(harness, "7 pm")
    assert (await current_conversation(harness)).pending_action == "CONFIRM_BOOKING"
    assert harness.codes == [code("CONFIRM")]
    await assert_no_ai_or_handoff(harness)

    await send(harness, "sí")
    conversation = await current_conversation(harness)
    assert conversation.state == "WAITING_FOR_HUMAN"
    handoffs = await harness.rows(Handoff)
    assert len(handoffs) == 1
    assert handoffs[0].reason == "RESERVATION_CONFIRMATION"
    assert "solicitud pendiente de pago" in handoffs[0].summary
    reservations = await harness.rows(Reservation)
    assert [reservation.reservation_id for reservation in reservations] == [prior_id]
    assert reservations[0].status == "PAYMENT_PENDING"
    assert harness.classifier_calls == []
    assert await harness.rows(AIExecution) == []

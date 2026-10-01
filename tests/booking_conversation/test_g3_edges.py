from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.audit.models import AuditEvent
from app.channel.delivery import eligibility
from app.channel.models import Outbox
from app.config.settings import get_settings
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.pending_actions import PENDING_ACTIONS
from app.conversation.presentation import present_variables
from app.customer.models import Customer
from app.event.models import Event
from app.lead.models import Lead
from app.plan.models import Plan
from app.reservation.booking import create_pending_reservation
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import (
    START,
    code,
    review_fixture,
    send_catalog_information,
    to_confirmation,
)
from tests.integration.helpers import login_headers
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import BOOK_ABSOLUTE, Harness


async def test_g3_date_after_delivered_catalog(harness: Harness, tmp_path: Path) -> None:
    await harness.seed()
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await send_catalog_information(harness)
    async with harness.db.begin() as session:
        row = await session.scalar(select(Outbox).where(Outbox.catalog_asset_id.is_not(None)))
        row.status = "SENT"
    before = len(harness.classifier_calls)
    await harness.send("7 de octubre a las 7 pm")
    assert harness.codes == [code("PLAN")]
    assert len(harness.classifier_calls) == before


async def test_g3_relative_date_confirmation_and_time(harness: Harness) -> None:
    await harness.seed()
    await harness.send("quiero reservar el próximo miércoles")
    await harness.send("1")
    assert harness.codes == ["RESP-EVENT-DATA-003"]
    await harness.send("sí")
    assert harness.codes == [code("TIME")]
    assert not harness.classifier_calls


async def test_g3_price_change_requires_new_confirmation(harness: Harness) -> None:
    await to_confirmation(harness)
    async with harness.db.begin() as session:
        plan = await session.scalar(select(Plan).where(Plan.code == "RITUAL_CORAZON"))
        plan.price_cop = 300000
    await harness.send("sí")
    assert not await harness.rows(Reservation)
    assert harness.codes == [code("CONFIRM")]
    assert "$300.000" in (await harness.bodies())[-1]


async def test_g3_calendar_changes_after_confirmation_offer(harness: Harness) -> None:
    await to_confirmation(harness)
    harness.calendar.add_event("business-main", "exclusividad", START, START + timedelta(hours=3))
    await harness.send("sí")
    assert not await harness.rows(Reservation) and harness.codes == [code("UNAVAILABLE")]


async def test_g3_calendar_unavailable_handoff(harness: Harness) -> None:
    await harness.seed()
    await harness.send(BOOK_ABSOLUTE)
    await harness.send("1")
    harness.calendar.raise_on.add("list_events")
    await harness.send("7 pm")
    await harness.assert_completed()
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"


async def test_g3_payment_notification_authorized_while_paused(harness: Harness, api: AsyncClient):
    evidence = await review_fixture(harness)
    async with harness.db.begin() as session:
        conversation = await session.get(Conversation, evidence.conversation_id)
        conversation.state = "WAITING_FOR_HUMAN"
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=await login_headers(api, "90000000"),
        json={"amount_cop": 250000},
    )
    assert response.status_code == 200 and response.json()["reservation"]["balance_due_at"] is None
    outboxes = await harness.rows(Outbox)
    assert len(outboxes) == 1 and "$0" in outboxes[0].payload["text"]["body"]
    async with harness.db() as session:
        row = await session.get(Outbox, outboxes[0].id)
        conversation = await session.get(Conversation, row.conversation_id)
        assert (await eligibility(session, conversation, row))[0] == "ELIGIBLE"


async def test_g3_render_failure_skips_without_breaking_accept(harness: Harness, api: AsyncClient):
    evidence = await review_fixture(harness)
    async with harness.db.begin() as session:
        entry = await session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.code == code("CONFIRMED"), KnowledgeEntry.version == 100
            )
        )
        entry.answer_template = "Variable faltante: {unknown_required}"
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        headers=await login_headers(api, "90000000"),
        json={"amount_cop": 125000},
    )
    assert response.status_code == 200 and response.json()["result"] == "RESERVED"
    assert not await harness.bodies()
    assert any(a.action == "NOTIFICATION_SKIPPED" for a in await harness.rows(AuditEvent))


async def test_g3_draft_template_never_emits_booking(harness: Harness) -> None:
    async with harness.db.begin() as session:
        entry = await session.scalar(
            select(KnowledgeEntry).where(
                KnowledgeEntry.code == code("PLAN"), KnowledgeEntry.version == 100
            )
        )
        entry.status = "DRAFT"
    await harness.seed()
    await harness.send("quiero reservar")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert not any("experiencias disponibles" in b for b in await harness.bodies())


async def test_g3_flag_disabled_mid_flow(harness: Harness, monkeypatch: pytest.MonkeyPatch):
    await harness.seed()
    await harness.send("quiero reservar")
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "false")
    get_settings.cache_clear()
    await harness.send("1")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"


@pytest.mark.parametrize("variable", ["plan_options", "plan_name", "bank_name", "account_number"])
def test_g3_customer_text_rejected_by_closed_presenters(variable: str) -> None:
    with pytest.raises(ValueError):
        present_variables({variable: "texto libre del cliente"})


async def test_g3_pending_check_matches_model_and_migration(harness: Harness) -> None:
    spec = spec_from_file_location(
        "booking_migration", "alembic/versions/20260930_0031_booking_draft.py"
    )
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.BEFORE + migration.ADDED == PENDING_ACTIONS
    async with harness.db() as session:
        definition = await session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_conversation_pending_action'"
            )
        )
        assert all(f"'{value}'" in definition for value in PENDING_ACTIONS)


async def test_g3_step_failure_counter_is_persisted(harness: Harness) -> None:
    await to_confirmation(harness)
    await harness.send("lo que sea")
    assert (await harness.conversation()).failed_understanding_count == 1
    await harness.send("no entiendo")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"


async def test_g3_customer_pending_manual_request_prevents_duplicate(harness: Harness) -> None:
    await to_confirmation(harness)
    await harness.send("sí")
    async with harness.db.begin() as session:
        reservation = await session.scalar(select(Reservation))
        reservation.conversation_id = None  # Manual request for this same customer.
    await harness.send("quiero reservar")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert len(await harness.rows(Reservation)) == 1


async def test_g3_pending_request_appearing_during_slots_prevents_duplicate(
    harness: Harness,
) -> None:
    await to_confirmation(harness)
    current = await harness.conversation()
    async with harness.db.begin() as session:
        conversation = await session.get(Conversation, current.id)
        customer = await session.get(Customer, conversation.customer_id)
        lead = await session.get(Lead, conversation.active_lead_id)
        event = await session.scalar(select(Event).where(Event.lead_id == lead.lead_id))
        plan = await session.get(Plan, UUID(conversation.booking_draft["plan_id"]))
        await create_pending_reservation(
            session, lead=lead, event=event, plan=plan, conversation=None,
            customer=customer, starts_at=START, actor="Asesor", request_id="g3.manual",
        )
    await harness.send("sí")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert len(await harness.rows(Reservation)) == 1

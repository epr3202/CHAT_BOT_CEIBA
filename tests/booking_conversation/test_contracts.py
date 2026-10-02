from datetime import timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.config.settings import get_settings
from app.conversation.models import Conversation, KnowledgeEntry
from app.conversation.pending_actions import PENDING_ACTIONS
from app.conversation.presentation import present_variables
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence
from app.reservation.models import Reservation
from data.knowledge_seed import CONDITIONAL_DRAFT_CODES, iter_seed_entries
from tests.booking_conversation.helpers import (
    START,
    TEMPLATES,
    code,
    draft_of,
    review_fixture,
    selected_plan,
    send_catalog_information,
    send_evidence,
    to_confirmation,
)
from tests.integration.helpers import login_headers
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import BOOK_ABSOLUTE, Harness


@pytest.mark.parametrize("enabled", [True, False])
async def test_b_r1_flag(harness: Harness, monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", str(enabled))
    get_settings.cache_clear()
    await harness.seed()
    await harness.send(BOOK_ABSOLUTE)
    await harness.assert_completed()
    assert not harness.classifier_calls
    assert bool(await harness.rows(Handoff)) is (not enabled)
    if enabled:
        assert harness.codes == [code("PLAN")]


@pytest.mark.parametrize(
    "message,expected",
    [
        (BOOK_ABSOLUTE, "SELECT_BOOKING_TIME"),
        ("quiero reservar el 7 de octubre a las 7 pm", "CONFIRM_BOOKING"),
    ],
)
async def test_b_r2_initial_slots(harness: Harness, message: str, expected: str) -> None:
    await harness.seed()
    await harness.send(message)
    draft = draft_of(await harness.conversation())
    assert draft["date"] == "2026-10-07"
    await harness.send("1")
    assert (await harness.conversation()).pending_action == expected
    assert not harness.classifier_calls


@pytest.mark.parametrize("choice", ["1", "RITUAL DEL CORAZÓN", "ritual del corazon"])
async def test_b_r3_plan_normalized(harness: Harness, choice: str) -> None:
    await harness.seed()
    await harness.send("quiero reservar")
    await harness.send(choice)
    assert draft_of(await harness.conversation())["plan_id"] == str(
        (await selected_plan(harness)).plan_id
    )
    assert harness.codes == [code("DATETIME")]


async def test_b_r3_two_failures_and_human_interrupt(harness: Harness) -> None:
    await harness.seed()
    await harness.send("quiero reservar")
    await harness.send("ninguno desconocido")
    assert harness.codes == [code("PLAN")]
    await harness.send("plan inexistente")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert len(await harness.rows(Handoff)) == 1


async def test_b_r4_human_interrupt(harness: Harness) -> None:
    await harness.seed()
    await harness.send("quiero reservar")
    await harness.send("quiero hablar con un asesor")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert (await harness.rows(Handoff))[0].reason == "CUSTOMER_REQUEST"


@pytest.mark.parametrize(
    "message,expected",
    [
        ("7 de octubre a las 8 am", "TIME"),
        ("7 de octubre", "TIME"),
        ("mañana", "DATE_CONFIRM"),
        ("jueves 7 de octubre", "DATE_CONFIRM"),
    ],
)
async def test_b_r4_dates(harness: Harness, message: str, expected: str) -> None:
    await harness.seed()
    await harness.send("quiero reservar")
    await harness.send("1")
    await harness.send(message)
    assert harness.codes == (
        ["RESP-EVENT-DATA-003"] if expected == "DATE_CONFIRM" else [code(expected)]
    )
    if expected == "TIME":
        assert (await harness.conversation()).pending_action == "SELECT_BOOKING_TIME"


@pytest.mark.parametrize("blocked", [True, False])
async def test_b_r5_availability(harness: Harness, blocked: bool) -> None:
    await harness.seed()
    if blocked:
        harness.calendar.add_event(
            "business-main", "EXCLUSIVIDAD", START, START + timedelta(hours=3)
        )
    await harness.send(BOOK_ABSOLUTE)
    await harness.send("1")
    await harness.send("7 pm")
    await harness.assert_completed()
    assert harness.codes == [code("UNAVAILABLE" if blocked else "CONFIRM")]
    draft = draft_of(await harness.conversation())
    assert draft["plan_id"] == str((await selected_plan(harness)).plan_id)
    assert (await harness.conversation()).pending_action == (
        "SELECT_BOOKING_DATETIME" if blocked else "CONFIRM_BOOKING"
    )
    if not blocked:
        body = (await harness.bodies())[-1]
        assert all(
            value in body
            for value in (
                "Ritual del Corazón",
                "7 de octubre de 2026",
                "19:00",
                "250.000",
                "125.000",
            )
        )


async def test_b_r6_confirm(harness: Harness) -> None:
    await to_confirmation(harness)
    await harness.send("sí")
    await harness.assert_completed()
    rows = await harness.rows(Reservation)
    assert len(rows) == 1 and rows[0].status == "PAYMENT_PENDING"
    assert rows[0].starts_at == START and rows[0].amount_paid_cop == 0
    assert rows[0].price_cop == 250000 and rows[0].calendar_status == "NONE"
    conversation = await harness.conversation()
    assert conversation.booking_draft is None and conversation.pending_action is None
    assert conversation.state == "BOT_ACTIVE"
    assert harness.codes == [code("PAYMENT")]
    body = (await harness.bodies())[-1]
    assert all(
        value in body
        for value in ("125.000", "Banco Ficticio", "Ahorros", "000123456", "Club de Prueba")
    )
    assert "{" not in body and not harness.classifier_calls
    assert "RESERVATION_CREATED" in {a.action for a in await harness.rows(AuditEvent)}


async def test_b_r6_missing_bank(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    await to_confirmation(harness)
    monkeypatch.setenv("BOOKING_ACCOUNT_NUMBER", "")
    get_settings.cache_clear()
    await harness.send("sí")
    assert code("PAYMENT") not in harness.codes
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert "datos bancarios no configurados" in (await harness.rows(Handoff))[0].summary
    assert all("{" not in b for b in await harness.bodies())


async def test_b_r6_deny(harness: Harness) -> None:
    await to_confirmation(harness)
    await harness.send("no")
    assert harness.codes == [code("DATETIME")]
    assert draft_of(await harness.conversation())["plan_id"]
    assert not await harness.rows(Reservation)


@pytest.mark.parametrize("caption", [None, "Aquí mi comprobante"])
async def test_b_r7_evidence(harness: Harness, caption: str | None) -> None:
    await to_confirmation(harness)
    await harness.send("sí")
    await send_evidence(harness, caption)
    assert (await harness.rows(Reservation))[0].status == "PAYMENT_REVIEW"
    assert len(await harness.rows(PaymentEvidence)) == 1
    assert harness.codes == [code("EVIDENCE")]
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"


async def test_b_r7_no_duplicate_request(harness: Harness) -> None:
    await to_confirmation(harness)
    await harness.send("sí")
    await harness.send("quiero reservar otra vez")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert len(await harness.rows(Reservation)) == 1


@pytest.mark.parametrize("result", ["RESERVED", "PARTIAL", "REJECTED", "CONFLICT"])
async def test_b_r8_notifications(harness: Harness, api: AsyncClient, result: str) -> None:
    evidence = await review_fixture(harness)
    if result == "CONFLICT":
        harness.calendar.add_event(
            "business-main", "exclusividad", START, START + timedelta(hours=3)
        )
    action = "reject" if result == "REJECTED" else "accept"
    body = (
        {"note": "Revisión"}
        if action == "reject"
        else {"amount_cop": 50000 if result == "PARTIAL" else 125000}
    )
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/{action}",
        json=body,
        headers=await login_headers(api, "90000000"),
    )
    assert response.status_code == 200, response.text
    if result == "CONFLICT":
        assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
        assert (
            "franja ya reservada; requiere reprogramación"
            in (await harness.rows(Handoff))[0].summary
        )
    else:
        assert harness.codes, "No se encoló la notificación esperada"
        assert harness.codes[-1] == code("CONFIRMED" if result == "RESERVED" else result)
        body = (await harness.bodies())[-1]
        assert "{" not in body
        if result == "RESERVED":
            assert "125.000" in body and "6 de octubre de 2026" in body


@pytest.mark.parametrize("linked", [True, False])
async def test_b_r8_draft_or_no_conversation(
    harness: Harness, api: AsyncClient, linked: bool
) -> None:
    evidence = await review_fixture(harness, conversation_linked=linked)
    async with harness.db.begin() as session:
        entry = await session.scalar(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.code == code("CONFIRMED"))
            .order_by(KnowledgeEntry.version.desc())
            .limit(1)
        )
        entry.status = "DRAFT"
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        json={"amount_cop": 125000},
        headers=await login_headers(api, "90000000"),
    )
    assert response.status_code == 200 and response.json()["result"] == "RESERVED"
    assert not await harness.bodies()
    skipped = [a for a in await harness.rows(AuditEvent) if a.action == "NOTIFICATION_SKIPPED"]
    assert bool(skipped) is linked


def test_b_r9_presenters() -> None:
    from app.conversation.presentation import VARIABLE_PRESENTERS

    assert {"total_amount", "deposit_amount", "missing_amount"} <= set(VARIABLE_PRESENTERS)
    values = present_variables(
        {"total_amount": 250000, "deposit_amount": 125000, "missing_amount": 0}
    )
    assert values == {
        "total_amount": "$250.000",
        "deposit_amount": "$125.000",
        "missing_amount": "$0",
    }
    with pytest.raises(ValueError):
        present_variables({"total_amount": "texto libre del cliente"})


async def test_b_r9_five_ordered_plans(harness: Harness) -> None:
    await harness.seed()
    await harness.send("quiero reservar")
    body = (await harness.bodies())[-1]
    names = [
        "Ritual del Corazón",
        "Romance entre Copas",
        "Mañanas de Encanto",
        "Cinema y Amor",
        "Refugio para Dos",
    ]
    assert all(f"{i}. {name}" in body for i, name in enumerate(names, 1))
    assert "250.000" not in body and "Noche Inolvidable" not in body


def test_b_r10_seed_literals_and_lineage() -> None:
    entries = {e.code: e for e in iter_seed_entries()}
    for name, literal in TEMPLATES.items():
        key = code(name)
        assert key not in CONDITIONAL_DRAFT_CODES and key in entries
        assert entries[key].status == "APPROVED" and entries[key].answer_template == literal
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_revision("20260930_0032") is not None
    assert scripts.get_revision("20260930_0032").down_revision == "20260930_0031"
    assert scripts.get_revision("20260930_0031").down_revision == "20260930_0030"
    expected = {
        "SELECT_BOOKING_PLAN",
        "SELECT_BOOKING_DATETIME",
        "SELECT_BOOKING_TIME",
        "CONFIRM_BOOKING",
    }
    assert expected <= set(PENDING_ACTIONS)
    assert "booking_draft" in Conversation.__table__.c


async def test_b_r11_literal_e2e(harness: Harness, api: AsyncClient, tmp_path: Path) -> None:
    await harness.seed()
    await seed_catalog(harness.db, tmp_path, event_type="ROMANTIC_DINNER", send_mode="PROACTIVE")
    await send_catalog_information(harness)
    from app.channel.models import Outbox

    assert any(row.catalog_asset_id is not None for row in await harness.rows(Outbox))
    await harness.send(BOOK_ABSOLUTE)
    assert harness.codes == [code("PLAN")]
    await harness.send("Ritual del Corazón")
    assert harness.codes == [code("TIME")]
    await harness.send("7 pm")
    assert harness.codes == [code("CONFIRM")]
    await harness.send("Si")
    assert harness.codes == [code("PAYMENT")]
    await send_evidence(harness)
    assert harness.codes == [code("EVIDENCE")]
    evidence = (await harness.rows(PaymentEvidence))[0]
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        json={"amount_cop": 125000},
        headers=await login_headers(api, "90000000"),
    )
    assert response.status_code == 200 and response.json()["calendar_synced"] is True
    assert (await harness.rows(Reservation))[0].status == "RESERVED"
    assert harness.codes[-1] == code("CONFIRMED")
    assert harness.calendar.created_event_ids == [
        (await harness.rows(Reservation))[0].reservation_id.hex
    ]
    await harness.assert_completed()

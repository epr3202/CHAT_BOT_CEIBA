"""B1b-3: active catalog names, fixed-price capture and durable text/PDF order."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.channel.models import Outbox
from app.channel.worker import claim_due_outbox_batch
from app.config.settings import get_settings
from app.conversation.fixed_price_booking import (
    BOOKING_ACTIONS,
    GENERIC_CAPTURE_ACTIONS,
    match_booking_plan,
)
from app.conversation.models import KnowledgeEntry
from app.event.models import Event
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import code, draft_of, send_catalog_information
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize(
    "message",
    [
        "RITUAL DEL CORAZÓN",
        "ritual del corazon",
        "Quiero el Ritual del Corazón",
        "ritual del corazn",
        "Quiero Ritual de Corazón para el 7 de octubre a las 7 pm",
    ],
)
async def test_b1b3_r1_named_plan_starts_and_selects_without_llm(
    harness: Harness,
    message: str,
) -> None:
    await harness.seed(event_type=None, with_lead=False)
    await harness.send(message)
    await harness.assert_completed()
    conversation = await harness.conversation()
    assert conversation.pending_action in BOOKING_ACTIONS, "Plan name did not start BOOKING"
    plan = next(p for p in await harness.rows(Plan) if p.code == "RITUAL_CORAZON")
    assert draft_of(conversation)["plan_id"] == str(plan.plan_id)
    assert not harness.classifier_calls
    assert not await harness.rows(Reservation), "A plan proposal cannot confirm a reservation"
    assert (await harness.rows(Event))[0].event_type == "ROMANTIC_DINNER"


@pytest.mark.parametrize("message", ["quiero visitar Ritual del Corazón", "ritual desconocido"])
async def test_b1b3_r1_visit_or_unknown_name_does_not_start_booking(
    harness: Harness,
    message: str,
) -> None:
    await harness.seed()
    await harness.send(message)
    assert (await harness.conversation()).pending_action not in BOOKING_ACTIONS
    assert harness.classifier_calls


async def test_b1b3_r1_inactive_plan_never_selected(harness: Harness) -> None:
    await harness.seed()
    async with harness.db.begin() as session:
        plan = await session.scalar(select(Plan).where(Plan.code == "RITUAL_CORAZON"))
        plan.active = False
    await harness.send("Ritual del Corazón")
    assert (await harness.conversation()).pending_action not in BOOKING_ACTIONS
    assert harness.classifier_calls


@pytest.mark.parametrize(
    "message,matched",
    [
        ("¡RITUAL DEL CORAZÓN!", True),
        ("Quiero: Ritual-del-Corazón.", True),
        ("ritual del corazn", True),
        ("ritual de corazon", True),
        ("1", False),
        ("ritual", False),
        ("otro plan", False),
        ("Quiero visitar Ritual del Corazón", False),
        ("Ritual del Corazón y Romance entre Copas", False),
    ],
)
def test_b1b3_r1_name_match_is_bounded_and_unambiguous(message: str, matched: bool) -> None:
    plans = [
        {"plan_id": "a", "name": "Ritual del Corazón"},
        {"plan_id": "b", "name": "Romance entre Copas"},
    ]
    assert (match_booking_plan(message, plans) is not None) is matched
    if matched:
        assert match_booking_plan(message, plans)["plan_id"] == "a"


def test_b1b3_r1_ambiguous_typo_does_not_choose_either_plan() -> None:
    plans = [
        {"plan_id": "a", "name": "Ritual del Corazón"},
        {"plan_id": "b", "name": "Ritual del CorazoX"},
    ]
    assert match_booking_plan("Ritual del Corazo", plans) is None


async def test_b1b3_r1_flag_off_named_plan_keeps_classifier(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "false")
    get_settings.cache_clear()
    await harness.seed()
    await harness.send("Ritual del Corazón")
    assert (await harness.conversation()).pending_action not in BOOKING_ACTIONS
    assert harness.classifier_calls


async def test_b1b3_r1_named_plan_starts_on_first_customer_message(harness: Harness) -> None:
    await harness.seed(state="NEW", with_lead=False)
    await harness.send("Ritual del Corazón")
    await harness.assert_completed()
    assert not harness.classifier_calls, "First-message plan name unnecessarily called the LLM"
    conversation = await harness.conversation()
    assert conversation.pending_action == "SELECT_BOOKING_DATETIME"
    assert conversation.state == "COLLECTING_EVENT_DATA"
    assert draft_of(conversation)["plan_id"]


async def test_b1b3_r1_name_tolerance_also_applies_after_plan_question(harness: Harness) -> None:
    await harness.seed()
    await harness.send("quiero reservar")
    await harness.send("quiero el ritual del corazn")
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_DATETIME"
    assert harness.codes == [code("DATETIME")]


@pytest.mark.parametrize("enabled", [True, False])
async def test_b1b3_r2_fixed_price_suppresses_generic_capture_only_when_enabled(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    enabled: bool,
) -> None:
    monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", str(enabled))
    get_settings.cache_clear()
    await harness.seed(state="COLLECTING_EVENT_DATA", pending="COLLECT_GUEST_COUNT")
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await harness.send("Me interesa esta experiencia", intent="QUOTE_REQUEST")
    conversation = await harness.conversation()
    if enabled:
        assert conversation.pending_action is None, "Generic fixed-price capture was not suppressed"
        assert conversation.state == "BOT_ACTIVE"
        assert conversation.pending_fields == []
        assert harness.codes == ["RESP-EVENTS-ROMANTIC-001"]
        assert not await harness.rows(Reservation)
    else:
        assert conversation.pending_action == "COLLECT_GUEST_COUNT"
        assert harness.codes == ["RESP-EVENT-DATA-004"]


@pytest.mark.parametrize("pending", sorted(GENERIC_CAPTURE_ACTIONS))
async def test_b1b3_r2_named_plan_interrupts_stale_generic_capture(
    harness: Harness,
    pending: str,
) -> None:
    await harness.seed(state="COLLECTING_EVENT_DATA", pending=pending)
    await harness.send("Ritual del Corazón")
    assert (await harness.conversation()).pending_action == "SELECT_BOOKING_DATETIME"
    assert not harness.classifier_calls


async def test_b1b3_r2_fixed_price_information_clears_stale_generic_action(
    harness: Harness,
    tmp_path,
) -> None:
    await harness.seed(state="COLLECTING_EVENT_DATA", pending="COLLECT_GUEST_COUNT")
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await send_catalog_information(harness)
    conversation = await harness.conversation()
    assert conversation.pending_action is None, "FAQ restored generic fixed-price capture"
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_fields == []


async def test_b1b3_r3_fixed_price_text_precedes_pdf_and_concurrent_claims_wait(
    harness: Harness,
    tmp_path,
) -> None:
    await harness.seed()
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await send_catalog_information(harness)
    rows = sorted(await harness.rows(Outbox), key=lambda row: row.id)
    assert [row.message_kind for row in rows] == ["TEXT", "DOCUMENT"], "PDF was queued first"
    assert rows[0].created_at == rows[1].created_at, "Test must cover equal transaction timestamps"
    now = datetime.now(UTC) + timedelta(minutes=1)
    first = await claim_due_outbox_batch(harness.db, now, 10)
    assert [claim.id for claim in first] == [rows[0].id], "PDF claimed before text delivery"
    assert await claim_due_outbox_batch(harness.db, now, 10) == [], (
        "Concurrent worker overtook text"
    )
    async with harness.db.begin() as session:
        row = await session.get(Outbox, rows[0].id)
        row.status = "SENT"
        row.sent_at = now
    second = await claim_due_outbox_batch(harness.db, now, 10)
    assert [claim.id for claim in second] == [rows[1].id]


async def test_b1b3_r3_retrying_text_blocks_pdf(harness: Harness, tmp_path) -> None:
    await harness.seed()
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await send_catalog_information(harness)
    rows = sorted(await harness.rows(Outbox), key=lambda row: row.id)
    async with harness.db.begin() as session:
        row = next(item for item in rows if item.message_kind == "TEXT")
        text_row = await session.get(Outbox, row.id)
        text_row.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    assert await claim_due_outbox_batch(harness.db, datetime.now(UTC), 10) == [], (
        "PDF must wait while approved text is scheduled for retry"
    )


async def test_b1b3_r3_unapproved_information_hands_off_without_pdf(
    harness: Harness,
    tmp_path,
) -> None:
    await harness.seed()
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    async with harness.db.begin() as session:
        latest = await session.scalar(
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.code == "RESP-EVENTS-ROMANTIC-001",
            )
            .order_by(KnowledgeEntry.version.desc())
            .limit(1)
        )
        latest.status = "DRAFT"
    await send_catalog_information(harness)
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert not any(row.message_kind == "DOCUMENT" for row in await harness.rows(Outbox))

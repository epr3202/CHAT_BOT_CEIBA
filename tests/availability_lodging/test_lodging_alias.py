from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai.models import AIExecution
from app.audit.models import AuditEvent
from app.catalog.models import CatalogSend
from app.channel.models import Outbox
from app.config.settings import Settings, get_settings
from app.conversation.fixed_price_booking import is_fixed_price_catalog_followup
from app.conversation.models import Conversation
from app.event.models import Event, EventServiceRequest
from app.lead.models import Lead
from app.main import app
from app.plan.models import Plan
from tests.availability_lodging.helpers import LODGING, get_plan, seed_booking, symbol
from tests.booking_conversation.helpers import code, draft_of
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize(
    "message",
    [
        "HOTEL",
        "hoteles",
        "hospedaje",
        "hospedar",
        "hospedarme",
        "hospedarnos",
        "habitación",
        "habitaciones",
        "alojamiento",
        "alojar",
        "alojarnos",
        "estadía",
        "posada",
        "motel",
        "dormir",
        "pasar la noche",
        "noche de pareja",
        "amanecer juntos",
    ],
)
def test_R_lodging_whole_word_vocabulary(message: str) -> None:
    assert symbol("app.conversation.lodging", "is_lodging_inquiry")(message) is True


@pytest.mark.parametrize(
    "message", ["noche", "buenas noches", "hoteleria", "posadasx", "hospedajesx"]
)
def test_V_no_lodging_substrings_or_night_alone(message: str) -> None:
    # A missing recognizer has the baseline behavior (no deterministic alias).
    from importlib import import_module

    try:
        module = import_module("app.conversation.lodging")
    except ModuleNotFoundError as exc:
        assert exc.name == "app.conversation.lodging"
        return
    matcher = getattr(module, "is_lodging_inquiry", lambda _: False)
    assert matcher(message) is False


# Phrases supplied in the prompt; the fourth represents G1's HOSPEDAJE marker.
# Never retrieve or copy production customer bodies into a test fixture.
@pytest.mark.parametrize(
    "message,matched",
    [
        ("hay hotel también?", "hotel"),
        ("habitación para pareja para hoy", "habitacion"),
        ("No es celebración es para hospedaje", "hospedaje"),
        ("busco hospedaje para dos", "hospedaje"),
    ],
    ids=["B-7279", "B-7281", "B-7285", "B-7295-synthetic"],
)
async def test_R_case_B_alias_orders_catalog_without_classifier(
    harness: Harness, tmp_path: Path, message: str, matched: str
) -> None:
    await harness.seed(with_lead=False)
    asset_id = await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await harness.send(message)
    await harness.assert_completed()
    assert harness.codes == [LODGING]
    assert harness.classifier_calls == []
    assert await harness.rows(AIExecution) == []
    conversation = await harness.conversation()
    assert conversation.state == "BOT_ACTIVE"
    assert conversation.pending_action is None
    assert conversation.last_question_code == LODGING
    leads, events = await harness.rows(Lead), await harness.rows(Event)
    assert len(leads) == len(events) == 1
    assert events[0].event_type == "ROMANTIC_DINNER"
    assert conversation.active_lead_id == events[0].lead_id == leads[0].lead_id
    outboxes = sorted(await harness.rows(Outbox), key=lambda row: row.id)
    assert [row.message_kind for row in outboxes] == ["TEXT", "DOCUMENT"]
    assert outboxes[1].catalog_asset_id == asset_id
    assert outboxes[1].delivery_context["after_outbox_id"] == outboxes[0].id
    assert (await get_plan(harness, "REFUGIO_DOS")).name in outboxes[0].payload["text"]["body"]
    resolutions = [
        row
        for row in await harness.rows(AuditEvent)
        if row.action == "CATALOG_EVENT_TYPE_RESOLVED"
        and row.new_value.get("source") == "LODGING_ALIAS"
    ]
    assert len(resolutions) == 1
    assert resolutions[0].new_value["matched_label"] == matched
    assert resolutions[0].new_value["event_type"] == "ROMANTIC_DINNER"


async def test_V_collect_services_keeps_accommodation_capture(harness: Harness) -> None:
    await harness.seed(
        event_type="BIRTHDAY", state="COLLECTING_EVENT_DATA", pending="COLLECT_SERVICES"
    )
    await harness.send("hospedaje")
    await harness.assert_completed()
    requests = await harness.rows(EventServiceRequest)
    assert any(
        row.service_name == "ACCOMMODATION" and row.status == "REQUESTED" for row in requests
    )
    assert LODGING not in harness.codes
    assert await harness.rows(CatalogSend) == []


@pytest.mark.parametrize("state", ["WAITING_FOR_HUMAN", "HUMAN_ACTIVE"])
async def test_V_A7_paused_lodging_stays_silent(harness: Harness, state: str) -> None:
    await harness.seed(state=state, pending="WAIT_FOR_HUMAN")
    await harness.send("hay hotel también?")
    await harness.assert_completed()
    assert harness.codes == []
    assert await harness.rows(Outbox) == []
    assert (await harness.conversation()).state == state


async def test_V_active_booking_draft_is_not_interrupted(harness: Harness) -> None:
    await seed_booking(harness, pending=None)
    before = draft_of(await harness.conversation())
    await harness.send("hotel")
    await harness.assert_completed()
    assert LODGING not in harness.codes
    assert await harness.rows(CatalogSend) == []
    assert draft_of(await harness.conversation()) == before


async def test_R_lodging_catalog_context_selects_refugio(harness: Harness) -> None:
    assert is_fixed_price_catalog_followup("ROMANTIC_DINNER", LODGING), (
        "El catálogo de hospedaje debe permitir seleccionar el plan posterior"
    )
    await harness.seed()
    conversation = await harness.conversation()
    async with harness.db.begin() as session:
        (await session.get(Conversation, conversation.id)).last_question_code = LODGING
    await harness.send("me interesa refugio para dos")
    await harness.assert_completed()
    selected = await get_plan(harness, "REFUGIO_DOS")
    assert draft_of(await harness.conversation())["plan_id"] == str(selected.plan_id)
    assert harness.codes == [code("DATETIME")]
    assert harness.classifier_calls == []


@pytest.mark.parametrize("inactive", [False, True], ids=["missing", "inactive"])
async def test_R_lodging_setting_fails_startup_for_invalid_plan(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, inactive: bool
) -> None:
    assert "lodging_plan_code" in Settings.model_fields, "Falta LODGING_PLAN_CODE en Settings"
    selected_code = "REFUGIO_DOS" if inactive else "NONEXISTENT_G2"
    if inactive:
        async with harness.db.begin() as session:
            (await session.scalar(select(Plan).where(Plan.code == selected_code))).active = False
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LODGING_PLAN_CODE", selected_code)
    get_settings.cache_clear()
    error = None
    try:
        async with app.router.lifespan_context(app):
            pass
    except ValueError as exc:
        error = exc
    assert error is not None, "Readiness debe rechazar el plan de hospedaje inexistente/inactivo"
    assert "LODGING_PLAN_CODE" in str(error)


def test_R_information_words_do_not_select_a_catalog_plan() -> None:
    words = symbol("app.conversation.fixed_price_booking", "_PLAN_INFORMATION_WORDS")
    assert {"hotel", "hospedaje", "habitacion"} <= words

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.conversation.models import Conversation
from app.plan.models import Plan
from app.reservation.models import Reservation
from tests.booking_conversation.helpers import code
from tests.booking_conversation.test_duplicate_reserved_guard_g2 import existing_booking
from tests.booking_conversation.test_prefilled_experience import EXPERIENCE_FORM, converse
from tests.clock import FreezeAppClock
from tests.visit_booking_guard.helpers import BOGOTA, Harness

START = datetime(2026, 11, 23, 20, tzinfo=BOGOTA)
AVAILABLE = "RESP-AVAILABILITY-AVAILABLE-001"


@pytest.fixture
async def occupied_romance(harness: Harness, freeze_app_clock: FreezeAppClock) -> None:
    freeze_app_clock(datetime(2026, 11, 21, 14, 12, tzinfo=BOGOTA))
    row = await existing_booking(harness, other_customer=True)
    async with harness.db.begin() as session:
        romance = await session.scalar(select(Plan).where(Plan.code == "ROMANCE_COPAS"))
        reserved = await session.get(Reservation, row.reservation_id)
        reserved.plan_id = romance.plan_id
        reserved.price_cop = reserved.amount_paid_cop = romance.price_cop
        reserved.starts_at, reserved.ends_at = START, START + timedelta(hours=3)
    form = EXPERIENCE_FORM.replace("31 de octubre de 2026", "23 deNoviembre  de 2026")
    assert await converse(harness, form, "8") == [code("TIME"), code("UNAVAILABLE")]


async def test_customer_checks_another_plan_for_same_slot(
    harness: Harness, occupied_romance: None
) -> None:
    for message in ("Y ritual del corazón", "23 Noviembre 8 pm"):
        assert await converse(harness, message) == [AVAILABLE]
        assert "Ritual del Corazón" in (await harness.bodies())[-1]
        conversation = await harness.conversation()
        assert conversation.pending_action == "CONFIRM_AVAILABILITY_BOOKING"
        assert conversation.booking_draft["plan_code"] == "RITUAL_CORAZON"
    checks = [
        r.new_value
        for r in await harness.rows(AuditEvent)
        if r.action == "AVAILABILITY_INQUIRY_ANSWERED"
    ]
    assert [(c["plan_code"], c["starts_at"], c["available"]) for c in checks][-2:] == [
        ("RITUAL_CORAZON", START.isoformat(), True),
        ("RITUAL_CORAZON", START.isoformat(), True),
    ]
    assert len(await harness.rows(Reservation)) == 1
    assert await converse(harness, "sí") == ["RESP-SERVICES-003", code("CONFIRM")]
    assert "violín en vivo" in (await harness.bodies())[-2].casefold()
    assert (await harness.conversation()).booking_draft["price_cop"] == 250000


async def test_alternative_obeys_exclusive_block_and_new_slot(
    harness: Harness, occupied_romance: None
) -> None:
    harness.calendar.add_event("business-main", "Exclusividad", START, START + timedelta(hours=2))
    assert await converse(harness, "¿Y el Ritual del Corazón?") == [code("UNAVAILABLE")]
    assert (await harness.conversation()).booking_draft["plan_code"] == "RITUAL_CORAZON"
    assert await converse(harness, "24 de noviembre a las 7 pm") == [AVAILABLE]
    draft = (await harness.conversation()).booking_draft
    assert (draft["plan_code"], draft["date"], draft["time"]) == (
        "RITUAL_CORAZON",
        "2026-11-24",
        "19:00",
    )


async def test_alternative_with_new_date_and_time(harness: Harness, occupied_romance: None) -> None:
    assert await converse(harness, "Mejor Ritual del Corazón el 25 de noviembre a las 6 pm") == [
        AVAILABLE
    ]
    draft = (await harness.conversation()).booking_draft
    assert (draft["plan_code"], draft["date"], draft["time"]) == (
        "RITUAL_CORAZON",
        "2026-11-25",
        "18:00",
    )


async def test_legacy_draft_can_change_plan_without_guessing_a_slot(
    harness: Harness, occupied_romance: None
) -> None:
    async with harness.db.begin() as session:
        conv = await session.scalar(select(Conversation))
        conv.booking_draft = {
            "plan_id": conv.booking_draft["plan_id"],
            "plan_code": "ROMANCE_COPAS",
        }
    assert await converse(harness, "Y Ritual del Corazón") == [code("DATETIME")]
    assert await converse(harness, "23 Noviembre 8 pm") == [AVAILABLE]
    assert (await harness.conversation()).booking_draft["plan_code"] == "RITUAL_CORAZON"


@pytest.mark.parametrize(
    "reply",
    [
        "sí",
        "No quiero Ritual del Corazón el 24 de noviembre a las 7 pm",
        "¿Ritual del Corazón o Romance entre Copas?",
    ],
)
async def test_rejected_or_ambiguous_choice_does_not_offer_a_slot(
    harness: Harness, occupied_romance: None, reply: str
) -> None:
    assert await converse(harness, reply) == [code("DATETIME")]
    draft = (await harness.conversation()).booking_draft
    assert draft["plan_code"] == "ROMANCE_COPAS"
    assert not draft.get("date") and not draft.get("time")
    assert len(await harness.rows(Reservation)) == 1


async def test_repeated_slot_is_checked_again_after_new_block(
    harness: Harness, occupied_romance: None
) -> None:
    assert await converse(harness, "Y Ritual del Corazón") == [AVAILABLE]
    harness.calendar.add_event("business-main", "Exclusividad", START, START + timedelta(hours=1))
    assert await converse(harness, "23 Noviembre 8 pm") == [code("UNAVAILABLE")]
    assert (await harness.conversation()).booking_draft["plan_code"] == "RITUAL_CORAZON"
    assert len(await harness.rows(Reservation)) == 1


async def test_unspecified_new_schedule_keeps_alternative_and_asks_for_missing_details(
    harness: Harness, occupied_romance: None
) -> None:
    assert await converse(harness, "Y Ritual del Corazón para otra noche") == [code("DATETIME")]
    assert await converse(harness, "23 Noviembre 8 pm") == [AVAILABLE]
    assert (await harness.conversation()).booking_draft["plan_code"] == "RITUAL_CORAZON"

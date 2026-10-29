import re
from collections.abc import AsyncIterator

import pytest

from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from tests.booking_conversation.conftest import api, base_harness  # noqa: F401
from tests.booking_conversation.conftest import harness as booking_harness  # noqa: F401
from tests.clock import BALANCE_NOW, FreezeAppClock, FrozenDateTime
from tests.payment_settlement.conftest import calendar, client  # noqa: F401
from tests.visit_booking_guard.helpers import Harness

BALANCE_TEMPLATES = {
    "RESP-BOOKING-BALANCE-PAID-001": (
        "¡Recibimos el pago completo de tu reserva! {plan_name}, el {booking_date} "
        "a las {booking_time}. ¡Nos vemos en La Ceiba!"
    ),
    "RESP-BOOKING-BALANCE-PARTIAL-001": (
        "Registramos tu pago. El saldo pendiente es {missing_amount} y debe estar "
        "pagado a más tardar el {balance_due_date}."
    ),
}


class BookingBalanceClock(FrozenDateTime):
    instant = BALANCE_NOW


@pytest.fixture(autouse=True)
def balance_clock(freeze_app_clock: FreezeAppClock) -> None:
    freeze_app_clock(BALANCE_NOW)


@pytest.fixture
async def harness(
    booking_harness: Harness,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    freeze_app_clock: FreezeAppClock,
) -> AsyncIterator[Harness]:
    monkeypatch.setenv("STAFF_NOTIFICATIONS_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(BookingBalanceClock, "instant", BALANCE_NOW)
    freeze_app_clock(BookingBalanceClock)
    async with booking_harness.db.begin() as session:
        # Approved, literal templates in a synthetic DB; no production knowledge is edited.
        for code, body in BALANCE_TEMPLATES.items():
            session.add(
                KnowledgeEntry(
                    code=code,
                    category="Reservas",
                    question_summary="Liquidación humana del saldo",
                    answer_template=body,
                    allowed_variables=sorted(set(re.findall(r"{(\w+)}", body))),
                    version=100,
                    status="APPROVED",
                )
            )
    yield booking_harness
    get_settings.cache_clear()

from __future__ import annotations

from datetime import time

import pytest

from tests.test_slice2a2_calendar_description_adversarial import (
    NEW_DATE,
    TODAY,
    at_bogota,
    seed_confirmed_appointment,
    service,
)
from tests.visit_booking_guard.helpers import Harness

pytestmark = pytest.mark.asyncio


async def test_r6_create_translates_event_type(harness: Harness) -> None:
    from tests.test_slice2a2_calendar_description_adversarial import (
        ORIGINAL_DATE,
        seed_customer,
    )

    customer_id, conversation_id, lead_id = await seed_customer(harness.db, with_lead=True)
    result = await service(harness.db, harness.calendar).confirm_appointment(
        customer_id=customer_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        visit_date=ORIGINAL_DATE,
        visit_time=time(9),
        attendee_count=2,
        visit_reason="si una boda",
        customer_confirmation=True,
        now=at_bogota(TODAY, 9),
    )
    assert result.appointment_id is not None
    event = await harness.calendar.get_event(result.appointment_id.hex)
    assert "Tipo de evento: Boda" in event.description
    assert "WEDDING" not in event.description
    assert "Motivo de la visita: si una boda" in event.description


@pytest.mark.parametrize("external_exists", [True, False], ids=["reschedule", "recreate-missing"])
async def test_r6_reschedule_and_recreation_translate_event_type(
    harness: Harness,
    external_exists: bool,
) -> None:
    appointment = await seed_confirmed_appointment(
        harness.db,
        harness.calendar,
        external_exists=external_exists,
    )
    result = await service(harness.db, harness.calendar).reschedule_appointment(
        appointment_id=appointment.appointment_id,
        new_date=NEW_DATE,
        new_time=time(10),
        actor="CUSTOMER",
        now=at_bogota(TODAY, 9),
    )
    assert result.response_code == "RESP-RESCHEDULE-004"
    event = await harness.calendar.get_event(appointment.appointment_id.hex)
    assert "Tipo de evento: Boda" in event.description
    assert "WEDDING" not in event.description
    assert event.description.count("Tipo de evento:") == 1
    assert "Motivo de la visita: Conocer el salón" in event.description

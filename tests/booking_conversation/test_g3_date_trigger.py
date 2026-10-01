import pytest
from sqlalchemy import select

from app.channel.models import Outbox
from tests.booking_conversation.helpers import code, send_catalog_information
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize(
    "message,booking",
    [
        ("el 7 de octubre es nuestro aniversario", False),
        ("el 7 de octubre a las 7 pm", True),
        ("quiero reservar el 7 de octubre", True),
    ],
)
async def test_g3_c3_explicit_date_requires_booking_expression_or_time(
    harness: Harness, tmp_path, message, booking
):
    await harness.seed()
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await send_catalog_information(harness)
    async with harness.db.begin() as session:
        row = await session.scalar(select(Outbox).where(Outbox.catalog_asset_id.is_not(None)))
        row.status = "SENT"
    before = len(harness.classifier_calls)
    await harness.send(message)
    if booking:
        assert harness.codes == [code("PLAN")]
        assert len(harness.classifier_calls) == before
    else:
        assert len(harness.classifier_calls) == before + 1
        assert code("PLAN") not in harness.codes

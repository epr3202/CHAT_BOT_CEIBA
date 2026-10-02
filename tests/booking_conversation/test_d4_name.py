import pytest

from app.audit.models import AuditEvent
from app.customer.models import Customer
from app.handoff.models import Handoff
from tests.b1a_contracts import require_symbol
from tests.booking_conversation.helpers import code
from tests.booking_conversation.test_d1_clock import seed_booking


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Emerson Pulgarín", "Emerson Pulgarín"),
        ("me llamo laura gómez", "Laura Gómez"),
        ("Soy Ana", "Ana"),
        ("¡Hola! mi nombre es maría josé", "María José"),
        ("habla Ana", "Ana"),
        ("con José", "José"),
        ("Ana-María O'Neill", "Ana-María O'Neill"),
        ("7 pm", None),
        ("https://x.co", None),
        ("a", None),
        ("@ana", None),
        ("a b c d e f", None),
        ("X" * 61, None),
    ],
)
def test_d4_pure_name(message, expected):
    extract = require_symbol("app.orchestrator.booking_flow", "extract_booking_name")
    assert extract(message) == expected


async def test_d4_collects_name_then_confirms_without_echo(harness):
    await seed_booking(harness, full_name=None)
    await harness.send("7 pm")
    assert (await harness.conversation()).pending_action == "COLLECT_BOOKING_NAME"
    assert harness.codes == ["RESP-CUSTOMER-001"]
    await harness.send("me llamo laura gómez")
    await harness.assert_completed()
    assert (await harness.rows(Customer))[0].full_name == "Laura Gómez"
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    assert harness.codes == [code("CONFIRM")]
    assert "Laura" not in (await harness.bodies())[-1]
    audit = [a for a in await harness.rows(AuditEvent) if a.action == "CUSTOMER_NAME_CAPTURED"]
    assert len(audit) == 1 and audit[0].reason == "Nombre capturado en flujo de reserva"
    assert not harness.classifier_calls


async def test_d4_two_invalid_names_handoff(harness):
    await seed_booking(harness, full_name=None)
    await harness.send("7 pm")
    assert (await harness.conversation()).pending_action == "COLLECT_BOOKING_NAME"
    await harness.send("https://x.co")
    assert harness.codes == ["RESP-CUSTOMER-003"]
    assert (await harness.conversation()).pending_action == "COLLECT_BOOKING_NAME"
    await harness.send("7 pm")
    assert (await harness.conversation()).state == "WAITING_FOR_HUMAN"
    assert "Nombre no reconocido en reserva" in (await harness.rows(Handoff))[0].summary
    assert (await harness.rows(Customer))[0].full_name is None


async def test_d4_existing_name_skips_collection(harness):
    await seed_booking(harness, full_name="Ana")
    await harness.send("7 pm")
    assert (await harness.conversation()).pending_action == "CONFIRM_BOOKING"
    assert "RESP-CUSTOMER-001" not in harness.codes

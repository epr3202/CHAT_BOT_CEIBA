import httpx
import pytest
import respx
from pydantic import ValidationError

from app.channel.outbound import WhatsAppOutboundClient, provider_send_error
from app.orchestrator.booking_flow import extract_booking_name
from app.payment.customer_reason import CustomerRejectionReason, sanitize_customer_reason
from tests.booking_backend.helpers import settings


@pytest.mark.parametrize(
    "changes",
    [
        {"STAFF_WINDOW_SAFETY_MINUTES": -1},
        {"STAFF_WINDOW_SAFETY_MINUTES": 181},
        {"STAFF_DEFERRED_MAX_AGE_HOURS": 0},
        {"STAFF_OUTBOX_MAX_ATTEMPTS": 0},
        {"STAFF_TEMPLATE_LANGUAGE": ""},
        {"BOOKING_LATEST_START": "24:00"},
        {"BOOKING_HOURS_END": "24:01"},
        {"BOOKING_HOURS_END": "21:00"},
        {"BOOKING_LATEST_START": "12:00"},
        {"BOOKING_HOURS_START": "22:00"},
    ],
)
def test_invalid_staff_and_booking_settings(changes):
    with pytest.raises(ValidationError):
        settings(**changes)


@pytest.mark.parametrize(
    "code",
    [
        131026,
        131047,
        131051,
        132000,
        132001,
        132005,
        132007,
        132012,
        132015,
        132016,
        132018,
        100,
        190,
    ],
)
@pytest.mark.parametrize("status", [400, 429, 503])
def test_permanent_codes_never_retry_even_on_transient_http_status(code, status):
    request = httpx.Request("POST", "https://graph.facebook.com/test/messages")
    response = httpx.Response(status, json={"error": {"code": code}}, request=request)
    error = provider_send_error(
        httpx.HTTPStatusError("failure", request=request, response=response)
    )
    assert error.code == code and not error.retryable


@pytest.mark.parametrize("message", ["hola", "¡Hola!", "me llamo", "soy", "Buenas tardes"])
def test_salutation_or_empty_name_prefix_is_not_a_name(message):
    assert extract_booking_name(message) is None


@pytest.mark.parametrize(
    "message,expected",
    [("¡Hola! me llamo ana maría.", "Ana María"), ("buenas, soy José-Luis", "José-Luis")],
)
def test_name_prefix_after_salutation(message, expected):
    assert extract_booking_name(message) == expected


async def test_customer_send_text_keeps_network_error_contract():
    config = settings(META_PHONE_NUMBER_ID="test-staff")
    with respx.mock:
        respx.post("https://graph.facebook.com/v20.0/test-staff/messages").mock(
            side_effect=httpx.ConnectError("offline")
        )
        async with WhatsAppOutboundClient(config) as sender:
            with pytest.raises(httpx.ConnectError):
                await sender.send_text("+573000000123", "Respuesta aprobada")


def test_truncation_at_a_space_still_produces_a_renderable_human_reason():
    reason = sanitize_customer_reason("x" * 199 + " texto adicional")
    assert reason == "x" * 199
    assert CustomerRejectionReason(reason).text == reason

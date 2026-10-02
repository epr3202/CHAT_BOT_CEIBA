"""F3: structured receipt output and the shared bounded OpenRouter transport."""

import json
from unittest.mock import Mock

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from app.ai import client as ai_client
from app.ai.receipt import ReceiptExtraction, ReceiptModelError, extract_receipt
from app.config.settings import Settings

FIELDS = {
    "amount_cop": 125000,
    "currency": "COP",
    "transaction_date": "2026-10-01",
    "transaction_time": "09:31",
    "reference": "TX-123",
    "bank": "Banco sintético",
    "destination_account_last4": "1234",
    "sender_name": "Ana Prueba",
    "confidence": 0.95,
    "notes": None,
}


def settings(**changes: object) -> Settings:
    return Settings(
        _env_file=None,
        **(
            {
                "DATABASE_URL": "postgresql+asyncpg://ceiba:ceiba@localhost/ceiba_f3_test",
                "ENVIRONMENT": "testing",
                "META_APP_SECRET": "test",
                "META_ACCESS_TOKEN": "test",
                "OPENROUTER_API_KEY": "test-receipt-token",
                "OPENROUTER_TIMEOUT_SECONDS": 0.2,
                "OPENROUTER_MAX_RETRIES": 1,
            }
            | changes
        ),
    )


def completion(**changes: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(FIELDS | changes)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        },
    )


@respx.mock
async def test_receipt_sends_its_complete_strict_json_schema() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=completion()
    )
    result = await extract_receipt(b"private image", "image/png", settings())
    payload = json.loads(route.calls[0].request.content)
    assert payload["response_format"]["type"] == "json_schema"
    structured = payload["response_format"]["json_schema"]
    assert structured["name"] == "receipt_extraction"
    assert structured["strict"] is True
    assert structured["schema"] == ReceiptExtraction.model_json_schema()
    assert structured["schema"]["additionalProperties"] is False
    assert set(structured["schema"]["required"]) == set(FIELDS)
    assert payload.get("provider") == {"require_parameters": True}
    assert result._telemetry["prompt_tokens"] == 12


async def test_classifier_and_receipt_share_the_same_http_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport_type = getattr(ai_client, "OpenRouterHTTPClient", None)
    assert transport_type is not None, "classifiers and vision must share OpenRouter transport"
    calls: list[dict[str, object]] = []

    async def post(
        self: ai_client.OpenRouterHTTPClient,
        endpoint: str,
        payload: dict[str, object],
    ) -> httpx.Response:
        assert endpoint == "chat/completions"
        calls.append(payload)
        return completion()

    monkeypatch.setattr(transport_type, "post", post)
    configured = settings()
    async with ai_client.OpenRouterIntentClient(configured, Mock()) as classifier:
        await classifier._post_with_retries("chat/completions", {"task": "classifier"})
    await extract_receipt(b"image", "image/png", configured)
    assert len(calls) == 2
    assert calls[0] == {"task": "classifier"}
    assert calls[1]["response_format"]["type"] == "json_schema"


@respx.mock
async def test_receipt_retries_http_once_then_succeeds() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[httpx.Response(503), completion()]
    )
    result = await extract_receipt(b"private image", "image/png", settings())
    assert result.amount_cop == 125000
    assert route.call_count == 2
    assert result._telemetry["completion_tokens"] == 8


@pytest.mark.parametrize("failure", ["timeout", "network", "status"])
@respx.mock
async def test_receipt_http_exhaustion_is_bounded_and_private(failure: str) -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions")
    if failure == "status":
        route.mock(return_value=httpx.Response(503, text="private image/base64/provider reply"))
    else:
        error_type = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        route.mock(side_effect=error_type("private image/base64/provider reply"))
    with capture_logs() as logs, pytest.raises(ReceiptModelError) as error:
        await extract_receipt(b"private image", "image/png", settings())
    assert route.call_count == 2, "HTTP requests are bounded by OPENROUTER_MAX_RETRIES + 1"
    assert str(error.value) == "MODEL_UNAVAILABLE"
    assert error.value.__cause__ is None
    assert error.value.telemetry["prompt_tokens"] == 0
    assert "private" not in json.dumps(logs)
    assert "base64" not in json.dumps(error.value.telemetry)


@pytest.mark.parametrize("invalid", [{"extra": "injection"}, {"amount_cop": "125000"}])
@respx.mock
async def test_receipt_invalid_schema_never_retries_the_parse(invalid: dict[str, object]) -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=completion(**invalid)
    )
    with pytest.raises(ReceiptModelError) as error:
        await extract_receipt(b"image", "image/png", settings(OPENROUTER_MAX_RETRIES=2))
    assert str(error.value) == "INVALID_SCHEMA"
    assert route.call_count == 1


@respx.mock
async def test_classifier_and_receipt_use_the_same_auth_and_explicit_timeout() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=completion()
    )
    configured = settings()
    async with ai_client.OpenRouterIntentClient(configured, Mock()) as classifier:
        await classifier._post_with_retries("chat/completions", {"task": "classifier"})
    await extract_receipt(b"image", "image/png", configured)
    assert route.call_count == 2
    for call in route.calls:
        assert call.request.headers["authorization"] == "Bearer test-receipt-token"
        assert call.request.extensions["timeout"] == {
            "connect": 0.2,
            "read": 0.2,
            "write": 0.2,
            "pool": 0.2,
        }


async def test_shared_transport_closes_only_the_client_it_owns() -> None:
    transport_type = getattr(ai_client, "OpenRouterHTTPClient", None)
    assert transport_type is not None, "OpenRouter transport must manage HTTP client ownership"
    async with httpx.AsyncClient() as supplied:
        async with transport_type(settings(), http_client=supplied):
            assert not supplied.is_closed
        assert not supplied.is_closed
    async with transport_type(settings()) as owned:
        opened = owned._http_client
        assert opened is not None and not opened.is_closed
    assert opened.is_closed

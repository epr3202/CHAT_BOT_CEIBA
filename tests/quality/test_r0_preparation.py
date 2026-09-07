from __future__ import annotations

import os

import httpx
import pytest
import respx

from app.ai.prompts.event_type_extraction_v1 import event_type_extraction_prompt
from app.config.settings import get_settings
from tests.http_doubles import (
    EXTRACTION_URL,
    unrecognized_event_type_mock,
    unrecognized_extraction_response,
)
from tests.integration.helpers import configure_test_database, current_test_database_url


def test_explicit_database_selection_clears_cache_and_restores_environment() -> None:
    original = os.environ.get("DATABASE_URL")
    try:
        get_settings()
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("DATABASE_URL", "postgresql+asyncpg://unused.invalid/obsolete_test")
            selected = configure_test_database(patch)
            assert get_settings.cache_info().currsize == 0
            assert selected == os.environ["TEST_DATABASE_URL"]
            assert current_test_database_url() == selected
            assert get_settings().database_url == selected
        assert os.environ.get("DATABASE_URL") == original
    finally:
        get_settings.cache_clear()


def test_database_preparation_requires_explicit_test_destination() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("TEST_DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="explicitly supplied"):
            configure_test_database(patch)


def extraction_payload() -> dict[str, object]:
    return {
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": event_type_extraction_prompt()},
            {"role": "user", "content": "Extrae el tipo de celebración del mensaje. Sintético"},
        ],
    }


@pytest.mark.parametrize("violation", ["host", "endpoint", "method", "task"])
def test_extractor_double_rejects_wrong_request_contract(violation: str) -> None:
    url, method, payload = EXTRACTION_URL, "POST", extraction_payload()
    if violation == "host":
        url = "https://unexpected.invalid/api/v1/chat/completions"
    elif violation == "endpoint":
        url = "https://openrouter.ai/api/v1/models"
    elif violation == "method":
        method = "GET"
    else:
        payload["messages"] = [{"role": "system", "content": "Classify intent"}]
    with pytest.raises(AssertionError):
        unrecognized_extraction_response(httpx.Request(method, url, json=payload))


@pytest.mark.asyncio
async def test_extractor_mock_is_used_and_removed_after_context() -> None:
    async with httpx.AsyncClient() as client:
        with unrecognized_event_type_mock() as route:
            response = await client.post(EXTRACTION_URL, json=extraction_payload())
            assert response.status_code == 200
            assert route.call_count == 1
        with respx.mock(assert_all_mocked=True):
            with pytest.raises(AssertionError, match="not mocked"):
                await client.post(EXTRACTION_URL, json=extraction_payload())


def test_extractor_mock_rejects_missing_expected_call() -> None:
    with pytest.raises(AssertionError):
        with unrecognized_event_type_mock():
            pass

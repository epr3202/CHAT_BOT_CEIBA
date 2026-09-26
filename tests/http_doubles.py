"""Explicit HTTP contract for tests that expect no recognized event type."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import respx

from app.ai.prompts.event_type_extraction_v1 import event_type_extraction_prompt

EXTRACTION_URL = "https://openrouter.ai/api/v1/chat/completions"


def unrecognized_extraction_response(request: httpx.Request) -> httpx.Response:
    """Reject wrong endpoints/tasks while retaining the real response parser."""
    assert request.method == "POST"
    assert str(request.url) == EXTRACTION_URL
    payload = json.loads(request.content)
    assert payload["response_format"] == {"type": "json_object"}
    messages = payload["messages"]
    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": event_type_extraction_prompt()}
    assert messages[1]["role"] == "user"
    assert messages[1]["content"].startswith("Extrae el tipo de celebración del mensaje.")
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": json.dumps({"event_type": "synthetic unsupported event"})}}
            ]
        },
    )


@contextmanager
def unrecognized_event_type_mock() -> Iterator[respx.Route]:
    """One exact extractor call; other HTTP calls and missing calls fail."""
    with respx.mock(assert_all_called=True, assert_all_mocked=True) as router:
        route = router.post(EXTRACTION_URL).mock(side_effect=unrecognized_extraction_response)
        yield route
        assert route.call_count == 1

"""Bounded multimodal extraction. This module never executes domain actions."""

import base64
import time
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from app.ai.client import OpenRouterHTTPClient, extract_message_content
from app.ai.errors import AIUnavailable
from app.ai.prompts.receipt_v1 import RECEIPT_PROMPT
from app.config.settings import Settings


class ReceiptExtraction(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    amount_cop: int | None = Field(ge=0, le=2147483647)
    currency: str | None = Field(max_length=16)
    transaction_date: date | None
    transaction_time: str | None = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")
    reference: str | None = Field(max_length=255)
    bank: str | None = Field(max_length=255)
    destination_account_last4: str | None = Field(pattern=r"^\d{4}$")
    sender_name: str | None = Field(max_length=255)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    notes: str | None = Field(max_length=1000)

    _telemetry: dict[str, Any] = PrivateAttr(default_factory=dict)


class ReceiptModelError(Exception):
    def __init__(self, code: str, telemetry: dict[str, Any]) -> None:
        super().__init__(code)
        self.telemetry = telemetry


async def extract_receipt(image_bytes: bytes, mime: str, settings: Settings) -> ReceiptExtraction:
    """Bounded shared HTTP retries and one strict parse; never log provider content."""
    started = time.monotonic()
    telemetry: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0}
    try:
        if mime not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("unsupported_image")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": settings.openrouter_model_vision,
            "messages": [
                {"role": "system", "content": RECEIPT_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extrae los campos visibles del comprobante."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{encoded}"
                            },
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 1000,
            "provider": {"require_parameters": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "receipt_extraction",
                    "strict": True,
                    "schema": ReceiptExtraction.model_json_schema(),
                },
            },
        }
        async with OpenRouterHTTPClient(settings) as client:
            response = await client.post("chat/completions", payload)
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("invalid_response")
        usage = body.get("usage") or {}
        if not isinstance(usage, dict):
            raise ValueError("invalid_usage")
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            telemetry[key] = value if type(value) is int and value >= 0 else 0
        extraction = ReceiptExtraction.model_validate_json(extract_message_content(body))
    except (AIUnavailable, httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as error:
        telemetry["latency_ms"] = int((time.monotonic() - started) * 1000)
        code = "INVALID_SCHEMA" if isinstance(error, ValidationError) else "MODEL_UNAVAILABLE"
        raise ReceiptModelError(code, telemetry) from None
    telemetry["latency_ms"] = int((time.monotonic() - started) * 1000)
    extraction._telemetry = telemetry
    return extraction

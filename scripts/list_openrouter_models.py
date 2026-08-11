from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List live OpenRouter models.")
    parser.add_argument("--grep", default=None, help="Case-insensitive filter over model id.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    if not settings.openrouter_api_key.strip():
        raise SystemExit("OPENROUTER_API_KEY is required")

    async with httpx.AsyncClient(
        base_url=settings.openrouter_base_url.rstrip("/") + "/",
        timeout=settings.openrouter_timeout_seconds,
    ) as client:
        response = await client.get(
            "models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        )
        response.raise_for_status()

    models = response.json().get("data", [])
    rows = [model_row(model) for model in models if should_include(model, args.grep)]
    rows.sort(key=lambda row: row["prompt_price"])

    print("id | pricing prompt/completion | context_length")
    print("--- | --- | ---")
    for row in rows:
        print(
            f"{row['id']} | {row['prompt_price_raw']}/{row['completion_price_raw']} | "
            f"{row['context_length']}"
        )


def should_include(model: dict[str, Any], grep: str | None) -> bool:
    if grep is None:
        return True
    model_id = str(model.get("id", ""))
    return grep.lower() in model_id.lower()


def model_row(model: dict[str, Any]) -> dict[str, Any]:
    pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
    prompt_price = string_decimal(pricing.get("prompt"))
    completion_price = string_decimal(pricing.get("completion"))
    return {
        "id": model.get("id", ""),
        "prompt_price": prompt_price,
        "prompt_price_raw": pricing.get("prompt", ""),
        "completion_price_raw": pricing.get("completion", ""),
        "completion_price": completion_price,
        "context_length": model.get("context_length", ""),
    }


def string_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("Infinity")


if __name__ == "__main__":
    asyncio.run(main())

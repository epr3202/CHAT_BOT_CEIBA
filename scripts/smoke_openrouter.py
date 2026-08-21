from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.ai.client import OpenRouterIntentClient
from app.ai.errors import AIUnavailable
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings

EXAMPLES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("Hola", {}),
    ("¿Dónde quedan ubicados?", {}),
    (
        "Quiero cotizar una boda para 45 personas en diciembre, soy Laura Pérez",
        {"known_fields": {"phone_number": "+573001112233"}},
    ),
    (
        "sí",
        {
            "last_intent": "SCHEDULE_VISIT",
            "pending_action": "CONFIRM_APPOINTMENT_SLOT",
            "last_question_code": "ASK_CONFIRM_VISIT_SLOT",
            "known_fields": {"preferred_visit_date": "2026-08-15"},
            "failed_understanding_count": 0,
        },
    ),
    ("No sé, necesito ver bien qué hacen y cuánto sale", {}),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real OpenRouter intent smoke.")
    parser.add_argument("--model", required=True, help="OpenRouter model id.")
    parser.add_argument("--text", default=None, help="Extra message to classify.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    if not settings.openrouter_api_key.strip():
        raise SystemExit("OPENROUTER_API_KEY is required")

    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    sessionmaker = create_sessionmaker(engine)

    samples = list(EXAMPLES)
    if args.text:
        samples.append((args.text, {}))

    try:
        async with OpenRouterIntentClient(settings, sessionmaker, model=args.model) as client:
            for text, context in samples:
                started = time.monotonic()
                try:
                    classification = await client.classify_intent(
                        text,
                        context=context,
                        request_id=None,
                    )
                except AIUnavailable as error:
                    latency_ms = int((time.monotonic() - started) * 1000)
                    print(
                        json.dumps(
                            {
                                "text": text,
                                "ok": False,
                                "reason": error.reason.value,
                                "latency_ms": latency_ms,
                            },
                            ensure_ascii=False,
                        )
                    )
                    continue

                latency_ms = int((time.monotonic() - started) * 1000)
                print(
                    json.dumps(
                        {
                            "text": text,
                            "ok": True,
                            "latency_ms": latency_ms,
                            "classification": classification.model_dump(),
                        },
                        ensure_ascii=False,
                    )
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

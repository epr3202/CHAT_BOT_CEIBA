from __future__ import annotations

import argparse
import random
import uuid
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException


def create_app(fail_rate: float = 0.0) -> FastAPI:
    app = FastAPI(title="Fake Meta WhatsApp API")
    sent_messages: list[dict[str, Any]] = []

    @app.post("/{version}/{phone_number_id}/messages")
    async def receive_message(
        version: str,
        phone_number_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if random.random() < fail_rate:
            raise HTTPException(status_code=500, detail="fake_meta_server injected failure")

        validate_text_payload(payload)
        provider_message_id = f"wamid.fake.{uuid.uuid4()}"
        timestamp = datetime.now(UTC).isoformat()
        to = payload["to"]
        body = payload["text"]["body"]

        print(f"{timestamp} → [{to}] {body}", flush=True)
        sent_messages.append(
            {
                "timestamp": timestamp,
                "version": version,
                "phone_number_id": phone_number_id,
                "to": to,
                "body": body,
                "payload": payload,
                "provider_message_id": provider_message_id,
            }
        )
        return {
            "messaging_product": "whatsapp",
            "messages": [{"id": provider_message_id}],
        }

    @app.get("/sent")
    async def list_sent() -> list[dict[str, Any]]:
        return sent_messages

    return app


def validate_text_payload(payload: dict[str, Any]) -> None:
    if payload.get("to") is None:
        raise HTTPException(status_code=422, detail="Missing to")
    if payload.get("type") != "text":
        raise HTTPException(status_code=422, detail="Only text messages are supported")

    text = payload.get("text")
    if not isinstance(text, dict) or not isinstance(text.get("body"), str) or not text["body"]:
        raise HTTPException(status_code=422, detail="Missing text.body")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a fake Meta WhatsApp API server.")
    parser.add_argument("--port", type=int, default=8081, help="Port to listen on.")
    parser.add_argument(
        "--fail-rate",
        type=float,
        default=0.0,
        help="Proportion of message requests that respond with HTTP 500.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0 <= args.fail_rate <= 1:
        raise SystemExit("--fail-rate must be between 0 and 1")
    uvicorn.run(create_app(args.fail_rate), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()

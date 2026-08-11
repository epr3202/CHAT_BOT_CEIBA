from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import uuid
from typing import Any

import httpx


def build_payload(phone: str, text: str, message_id: str) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "local-waba-id",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "573001112233",
                                "phone_number_id": os.getenv(
                                    "META_PHONE_NUMBER_ID",
                                    "local-phone-number-id",
                                ),
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Cliente Local"},
                                    "wa_id": phone,
                                }
                            ],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "timestamp": "1723046400",
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def sign_body(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a signed WhatsApp webhook locally.")
    parser.add_argument("--phone", required=True, help="Sender phone number from WhatsApp payload.")
    parser.add_argument("--text", required=True, help="Inbound text message body.")
    parser.add_argument(
        "--message-id",
        default=f"wamid.local.{uuid.uuid4()}",
        help="External WhatsApp message id. Defaults to a random local id.",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/webhook",
        help="Local webhook URL.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app_secret = os.environ["META_APP_SECRET"]
    payload = build_payload(args.phone, args.text, args.message_id)
    body = json.dumps(payload, separators=(",", ":")).encode()

    with httpx.Client(timeout=10.0) as client:
        response = client.post(
            args.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sign_body(body, app_secret),
            },
        )

    print(f"{response.status_code} {response.text}")
    response.raise_for_status()


if __name__ == "__main__":
    main()


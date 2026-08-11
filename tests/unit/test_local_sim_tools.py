from __future__ import annotations

import json

from fastapi.testclient import TestClient

from scripts import chat_simulator
from scripts.fake_meta_server import create_app


def test_fake_meta_server_accepts_text_message_and_lists_sent() -> None:
    app = create_app(fail_rate=0.0)

    with TestClient(app) as client:
        response = client.post(
            "/v20.0/123456789/messages",
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": "+573001112233",
                "type": "text",
                "text": {"preview_url": False, "body": "Hola"},
            },
        )
        sent_response = client.get("/sent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messaging_product"] == "whatsapp"
    assert payload["messages"][0]["id"].startswith("wamid.fake.")

    assert sent_response.status_code == 200
    sent = sent_response.json()
    assert sent[0]["to"] == "+573001112233"
    assert sent[0]["body"] == "Hola"
    assert sent[0]["provider_message_id"] == payload["messages"][0]["id"]


def test_fake_meta_server_rejects_non_text_payload() -> None:
    app = create_app(fail_rate=0.0)

    with TestClient(app) as client:
        response = client.post(
            "/v20.0/123456789/messages",
            json={"to": "+573001112233", "type": "image", "image": {"id": "media-id"}},
        )

    assert response.status_code == 422


def test_chat_simulator_reuses_simulate_webhook_signature_helper(
    monkeypatch,
) -> None:
    calls: list[bytes] = []

    def fake_sign_body(body: bytes, app_secret: str) -> str:
        calls.append(body)
        assert app_secret == "secret"
        return "sha256=fake"

    monkeypatch.setattr(chat_simulator.webhook_helper, "sign_body", fake_sign_body)

    body, headers = chat_simulator.prepare_signed_webhook_request(
        "+573001112233",
        "Hola",
        "wamid.local.test",
        "secret",
    )

    assert calls == [body]
    assert headers["X-Hub-Signature-256"] == "sha256=fake"
    assert json.loads(body)["entry"][0]["changes"][0]["value"]["messages"][0]["id"] == (
        "wamid.local.test"
    )

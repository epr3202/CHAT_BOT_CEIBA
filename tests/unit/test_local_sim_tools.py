from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts import chat_simulator
from scripts.fake_meta_server import create_app

REQUIRED_ENV_KEYS = [
    "DATABASE_URL",
    "META_APP_SECRET",
    "META_ACCESS_TOKEN",
    "OPENROUTER_API_KEY",
]


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    chat_simulator.get_settings.cache_clear()
    yield
    chat_simulator.get_settings.cache_clear()


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


def test_fake_meta_server_fail_rate_can_force_500() -> None:
    app = create_app(fail_rate=1.0)

    with TestClient(app) as client:
        response = client.post(
            "/v20.0/123456789/messages",
            json={
                "to": "+573001112233",
                "type": "text",
                "text": {"body": "Hola"},
            },
        )

    assert response.status_code == 500


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


def test_chat_simulator_loads_settings_from_dotenv_when_secret_not_in_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    chat_simulator.get_settings.cache_clear()
    tmp_path.joinpath(".env").write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba",
                "META_APP_SECRET=dotenv-secret",
                "META_ACCESS_TOKEN=test-token",
                "OPENROUTER_API_KEY=test-openrouter-key",
            ]
        ),
        encoding="utf-8",
    )

    settings = chat_simulator.load_chat_simulator_settings()

    assert settings.meta_app_secret == "dotenv-secret"
    assert settings.database_url == "postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba"


def test_chat_simulator_fails_fast_without_env_or_dotenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key in REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    chat_simulator.get_settings.cache_clear()

    try:
        chat_simulator.load_chat_simulator_settings()
    except SystemExit as error:
        message = str(error)
    else:
        raise AssertionError("chat_simulator should fail before starting without required settings")

    assert "Missing required settings for chat_simulator" in message
    assert "DATABASE_URL" in message
    assert "META_APP_SECRET" in message

from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import Settings, get_settings


class WhatsAppSendError(RuntimeError):
    pass


class WhatsAppOutboundClient:
    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def __aenter__(self) -> WhatsAppOutboundClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()

    async def send_text(self, to: str, body: str) -> str:
        if self._http_client is None:
            raise RuntimeError("WhatsAppOutboundClient must be used as an async context manager")

        response = await self._http_client.post(
            self._messages_url(),
            headers={
                "Authorization": f"Bearer {self._settings.meta_access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": body,
                },
            },
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise WhatsAppSendError(str(error)) from error

        provider_message_id = extract_provider_message_id(response.json())
        if provider_message_id is None:
            raise WhatsAppSendError("Meta response did not include messages[0].id")
        return provider_message_id

    def _messages_url(self) -> str:
        return (
            f"{self._settings.whatsapp_api_base_url.rstrip('/')}/"
            f"{self._settings.meta_graph_api_version}/"
            f"{self._settings.meta_phone_number_id}/messages"
        )


def extract_provider_message_id(payload: dict[str, Any]) -> str | None:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    first_message = messages[0]
    if not isinstance(first_message, dict):
        return None
    message_id = first_message.get("id")
    if not isinstance(message_id, str) or not message_id:
        return None
    return message_id


async def send_text(to: str, body: str) -> str:
    settings = get_settings()
    async with WhatsAppOutboundClient(settings) as client:
        return await client.send_text(to, body)

from __future__ import annotations

from app.channel.outbound import WhatsAppOutboundClient
from app.config.settings import Settings


def test_whatsapp_outbound_uses_configured_api_base_url() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba",
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-meta-access-token",
        META_GRAPH_API_VERSION="v20.0",
        META_PHONE_NUMBER_ID="123456789",
        OPENROUTER_API_KEY="test-openrouter-key",
        WHATSAPP_API_BASE_URL="http://localhost:8081/",
        ENVIRONMENT="testing",
        _env_file=None,
    )

    client = WhatsAppOutboundClient(settings)

    assert client._messages_url() == "http://localhost:8081/v20.0/123456789/messages"

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_settings_loads_technical_defaults_for_testing() -> None:
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba",
        META_APP_SECRET="test-app-secret",
        META_ACCESS_TOKEN="test-meta-access-token",
        OPENROUTER_API_KEY="test-openrouter-key",
        ENVIRONMENT="testing",
        _env_file=None,
    )

    assert settings.log_level == "INFO"
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 5
    assert settings.meta_graph_api_version == "v20.0"
    assert settings.whatsapp_api_base_url == "https://graph.facebook.com"
    assert settings.webhook_max_body_bytes == 1_048_576
    assert settings.outbox_batch_size == 10
    assert settings.outbox_sending_timeout_seconds == 120
    assert settings.outbox_max_attempts == 5
    assert settings.outbox_max_backoff_seconds == 300
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert settings.openrouter_model_intent is None
    assert settings.openrouter_timeout_seconds == 15
    assert settings.openrouter_max_retries == 1
    assert settings.ai_prompt_version == "intent_v3"
    assert settings.ai_confidence_safe == 0.85


def test_production_rejects_blank_required_secrets() -> None:
    with pytest.raises(ValidationError, match="Missing required production settings"):
        Settings(
            DATABASE_URL="",
            META_APP_SECRET="",
            META_ACCESS_TOKEN="",
            OPENROUTER_API_KEY="",
            ENVIRONMENT="production",
            _env_file=None,
        )

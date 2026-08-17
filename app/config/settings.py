from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=5, alias="DB_MAX_OVERFLOW")

    environment: Literal["development", "testing", "production"] = Field(
        default="development",
        alias="ENVIRONMENT",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # TODO Slice 3: move human-hours and holiday rules to the Configuration table.
    human_hours_days: str = Field(default="1,2,3,4,5", alias="HUMAN_HOURS_DAYS")
    human_hours_start: str = Field(default="08:00", alias="HUMAN_HOURS_START")
    human_hours_end: str = Field(default="16:00", alias="HUMAN_HOURS_END")

    meta_app_secret: str = Field(alias="META_APP_SECRET")
    meta_verify_token: str = Field(default="", alias="META_VERIFY_TOKEN")
    meta_access_token: str = Field(alias="META_ACCESS_TOKEN")
    meta_phone_number_id: str = Field(default="", alias="META_PHONE_NUMBER_ID")
    # Verificar la versión vigente en el dashboard de Meta antes de desplegar;
    # las versiones de Graph API caducan (~2 años).
    meta_graph_api_version: str = Field(default="v20.0", alias="META_GRAPH_API_VERSION")
    whatsapp_api_base_url: str = Field(
        default="https://graph.facebook.com",
        alias="WHATSAPP_API_BASE_URL",
    )

    webhook_max_body_bytes: int = Field(default=1_048_576, alias="WEBHOOK_MAX_BODY_BYTES")

    outbox_poll_interval_seconds: float = Field(default=1.0, alias="OUTBOX_POLL_INTERVAL_SECONDS")
    outbox_batch_size: int = Field(default=10, alias="OUTBOX_BATCH_SIZE")
    outbox_sending_timeout_seconds: int = Field(default=120, alias="OUTBOX_SENDING_TIMEOUT_SECONDS")
    outbox_max_attempts: int = Field(default=5, alias="OUTBOX_MAX_ATTEMPTS")
    outbox_max_backoff_seconds: int = Field(default=300, alias="OUTBOX_MAX_BACKOFF_SECONDS")
    catalog_storage_dir: str = Field(default="catalogs", alias="CATALOG_STORAGE_DIR")
    catalog_media_ttl_days: int = Field(default=25, alias="CATALOG_MEDIA_TTL_DAYS")
    catalog_max_file_mb: int = Field(default=16, alias="CATALOG_MAX_FILE_MB")
    google_calendar_id: str = Field(default="", alias="GOOGLE_CALENDAR_ID")
    google_freebusy_calendar_ids: str = Field(default="", alias="GOOGLE_FREEBUSY_CALENDAR_IDS")
    calendar_adapter: Literal["fake", "google"] = Field(default="fake", alias="CALENDAR_ADAPTER")
    google_service_account_file: str = Field(default="", alias="GOOGLE_SERVICE_ACCOUNT_FILE")

    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_model_intent: str | None = Field(default=None, alias="OPENROUTER_MODEL_INTENT")
    openrouter_model_extraction: str | None = Field(
        default=None,
        alias="OPENROUTER_MODEL_EXTRACTION",
    )
    openrouter_model_drafting: str | None = Field(default=None, alias="OPENROUTER_MODEL_DRAFTING")
    openrouter_model_summary: str | None = Field(default=None, alias="OPENROUTER_MODEL_SUMMARY")
    openrouter_timeout_seconds: float = Field(default=15.0, alias="OPENROUTER_TIMEOUT_SECONDS")
    openrouter_max_retries: int = Field(default=1, alias="OPENROUTER_MAX_RETRIES")
    ai_prompt_version: Literal["intent_v1", "intent_v2", "intent_v3", "intent_v4"] = Field(
        default="intent_v4",
        alias="AI_PROMPT_VERSION",
    )
    ai_confidence_safe: float = Field(default=0.85, alias="AI_CONFIDENCE_SAFE")
    ai_confidence_probable: float = Field(default=0.70, alias="AI_CONFIDENCE_PROBABLE")
    ai_confidence_uncertain: float = Field(default=0.50, alias="AI_CONFIDENCE_UNCERTAIN")

    @model_validator(mode="after")
    def validate_production_required_secrets(self) -> Settings:
        if self.environment != "production":
            return self

        missing = [
            alias
            for alias, value in {
                "DATABASE_URL": self.database_url,
                "META_APP_SECRET": self.meta_app_secret,
                "META_ACCESS_TOKEN": self.meta_access_token,
                "OPENROUTER_API_KEY": self.openrouter_api_key,
            }.items()
            if not value.strip()
        ]
        if missing:
            raise ValueError("Missing required production settings: " + ", ".join(sorted(missing)))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

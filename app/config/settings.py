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
    admin_login_max_failures: int = Field(default=5, alias="ADMIN_LOGIN_MAX_FAILURES")
    admin_login_window_minutes: int = Field(default=15, alias="ADMIN_LOGIN_WINDOW_MINUTES")
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

    inbox_poll_interval_seconds: float = Field(
        default=1.0, alias="INBOX_POLL_INTERVAL_SECONDS", gt=0
    )
    inbox_batch_size: int = Field(default=10, alias="INBOX_BATCH_SIZE", ge=1, le=100)
    inbox_claim_timeout_seconds: int = Field(default=120, alias="INBOX_CLAIM_TIMEOUT_SECONDS", ge=1)
    inbox_max_attempts: int = Field(default=5, alias="INBOX_MAX_ATTEMPTS", ge=1, le=100)
    inbox_max_backoff_seconds: int = Field(default=300, alias="INBOX_MAX_BACKOFF_SECONDS", ge=0)

    outbox_poll_interval_seconds: float = Field(default=1.0, alias="OUTBOX_POLL_INTERVAL_SECONDS")
    outbox_batch_size: int = Field(default=10, alias="OUTBOX_BATCH_SIZE")
    outbox_sending_timeout_seconds: int = Field(default=120, alias="OUTBOX_SENDING_TIMEOUT_SECONDS")
    outbox_max_attempts: int = Field(default=5, alias="OUTBOX_MAX_ATTEMPTS")
    outbox_max_backoff_seconds: int = Field(default=300, alias="OUTBOX_MAX_BACKOFF_SECONDS")
    staff_notifications_enabled: bool = Field(default=False, alias="STAFF_NOTIFICATIONS_ENABLED")
    staff_template_evidence_name: str = Field(default="", alias="STAFF_TEMPLATE_EVIDENCE_NAME")
    staff_template_pending_name: str = Field(default="", alias="STAFF_TEMPLATE_PENDING_NAME")
    staff_template_language: str = Field(
        default="es", alias="STAFF_TEMPLATE_LANGUAGE", min_length=1
    )
    staff_window_safety_minutes: int = Field(
        default=30,
        alias="STAFF_WINDOW_SAFETY_MINUTES",
        ge=0,
        le=180,
    )
    staff_deferred_max_age_hours: int = Field(
        default=48, alias="STAFF_DEFERRED_MAX_AGE_HOURS", ge=1
    )
    staff_outbox_max_attempts: int = Field(default=5, alias="STAFF_OUTBOX_MAX_ATTEMPTS", ge=1)
    balance_reminders_enabled: bool = Field(default=False, alias="BALANCE_REMINDERS_ENABLED")
    booking_reminder_days_before: int = Field(default=3, alias="BOOKING_REMINDER_DAYS_BEFORE", ge=1)
    booking_reminder_time: str = Field(
        default="10:00", alias="BOOKING_REMINDER_TIME", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    customer_template_balance_reminder_name: str = Field(
        default="", alias="CUSTOMER_TEMPLATE_BALANCE_REMINDER_NAME"
    )
    staff_template_overdue_name: str = Field(default="", alias="STAFF_TEMPLATE_OVERDUE_NAME")
    catalog_storage_dir: str = Field(default="catalogs", alias="CATALOG_STORAGE_DIR")
    catalog_media_ttl_days: int = Field(default=25, alias="CATALOG_MEDIA_TTL_DAYS")
    catalog_max_file_mb: int = Field(default=16, alias="CATALOG_MAX_FILE_MB")
    inbound_media_max_mb: int = Field(default=16, alias="INBOUND_MEDIA_MAX_MB", ge=0)
    payment_evidence_dir: str = Field(
        default="/data/payment-evidence", alias="PAYMENT_EVIDENCE_DIR"
    )
    payment_evidence_retention_days: int = Field(
        default=365, alias="PAYMENT_EVIDENCE_RETENTION_DAYS", ge=1
    )
    payment_review_ai_enabled: bool = Field(default=False, alias="PAYMENT_REVIEW_AI_ENABLED")
    payment_review_confidence_ok: float = Field(
        default=0.80, alias="PAYMENT_REVIEW_CONFIDENCE_OK", ge=0, le=1
    )
    payment_review_confidence_min: float = Field(
        default=0.50, alias="PAYMENT_REVIEW_CONFIDENCE_MIN", ge=0, le=1
    )
    payment_review_max_attempts: int = Field(
        default=2, alias="PAYMENT_REVIEW_MAX_ATTEMPTS", ge=1, le=2
    )
    openrouter_model_vision: str = Field(
        default="google/gemini-2.5-flash-lite", alias="OPENROUTER_MODEL_VISION", min_length=1
    )
    google_calendar_id: str = Field(default="", alias="GOOGLE_CALENDAR_ID")
    google_freebusy_calendar_ids: str = Field(default="", alias="GOOGLE_FREEBUSY_CALENDAR_IDS")
    calendar_adapter: Literal["fake", "google"] = Field(default="fake", alias="CALENDAR_ADAPTER")
    google_service_account_file: str = Field(default="", alias="GOOGLE_SERVICE_ACCOUNT_FILE")

    # Opt-in booking conversation; approved templates and complete bank data are required.
    self_service_booking_enabled: bool = Field(default=False, alias="SELF_SERVICE_BOOKING_ENABLED")
    booking_bank_name: str = Field(default="", alias="BOOKING_BANK_NAME")
    booking_account_type: str = Field(default="", alias="BOOKING_ACCOUNT_TYPE")
    booking_account_number: str = Field(default="", alias="BOOKING_ACCOUNT_NUMBER")
    booking_account_holder: str = Field(default="", alias="BOOKING_ACCOUNT_HOLDER")
    bank_breb_key: str = Field(default="", alias="BANK_BREB_KEY")
    booking_exclusivity_keyword: str = Field(
        default="exclusividad", alias="BOOKING_EXCLUSIVITY_KEYWORD", min_length=1
    )
    booking_hours_start: str = Field(
        default="12:00", alias="BOOKING_HOURS_START", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    booking_hours_end: str = Field(
        default="24:00", alias="BOOKING_HOURS_END", pattern=r"^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$"
    )
    booking_latest_start: str = Field(
        default="21:00", alias="BOOKING_LATEST_START", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    booking_min_lead_days: int = Field(default=1, alias="BOOKING_MIN_LEAD_DAYS", ge=0)
    booking_deposit_percent: int = Field(default=50, alias="BOOKING_DEPOSIT_PERCENT", ge=1, le=100)

    @model_validator(mode="after")
    def validate_booking_settings(self) -> Settings:
        if self.payment_review_confidence_min > self.payment_review_confidence_ok:
            raise ValueError("PAYMENT_REVIEW_CONFIDENCE_MIN must not exceed CONFIDENCE_OK")
        if not self.booking_hours_start < self.booking_latest_start < self.booking_hours_end:
            raise ValueError(
                "BOOKING_HOURS_START < BOOKING_LATEST_START < BOOKING_HOURS_END required"
            )
        if not self.booking_exclusivity_keyword.strip():
            raise ValueError("BOOKING_EXCLUSIVITY_KEYWORD must not be blank")
        return self

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

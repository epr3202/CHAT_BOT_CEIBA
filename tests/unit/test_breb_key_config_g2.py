"""Bre-B configuration and startup contracts; staged for tests/unit after PR #42."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, sentinel

import pytest

from app.config import readiness
from app.config.settings import Settings
from app.conversation import knowledge
from app.conversation.models import KnowledgeEntry

PAYMENT_CODE = "RESP-BOOKING-PAYMENT-001"
SYNTHETIC_KEY = "CEIBA-BREB-SYNTHETIC-TEST"
KEY_ERROR = "BANK_BREB_KEY"
PaymentValidator = Callable[[Settings, Any], Awaitable[None]]


def payment_settings(*, environment: str = "production", key: str = "") -> Settings:
    return Settings(
        ENVIRONMENT=environment,
        DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/ceiba_test_breb_config",
        META_APP_SECRET="synthetic-app-secret",
        META_ACCESS_TOKEN="synthetic-access-token",
        OPENROUTER_API_KEY="synthetic-openrouter-key",
        BOOKING_BANK_NAME="Banco Sintético",
        BOOKING_ACCOUNT_TYPE="Ahorros",
        BOOKING_ACCOUNT_NUMBER="0000000000",
        BOOKING_ACCOUNT_HOLDER="Titular Sintético",
        BANK_BREB_KEY=key,
        _env_file=None,
    )


def payment_entry(
    *, status: str = "APPROVED", uses_key: bool = True, version: int = 3
) -> KnowledgeEntry:
    template = "Abono: {deposit_amount}. Datos bancarios aprobados."
    allowed_variables = ["deposit_amount"]
    if uses_key:
        template += "\nLlave Bre-B: {breb_key}"
        allowed_variables.append("breb_key")
    return KnowledgeEntry(
        code=PAYMENT_CODE,
        category="Reservas",
        question_summary="Instrucciones de pago de prueba",
        answer_template=template,
        allowed_variables=allowed_variables,
        version=version,
        status=status,
    )


def payment_validator() -> PaymentValidator:
    validator = getattr(readiness, "validate_payment_settings", None)
    assert callable(validator), "Falta validate_payment_settings para el arranque de Bre-B"
    return cast(PaymentValidator, validator)


def patch_payment_lookup(
    monkeypatch: pytest.MonkeyPatch,
    latest: KnowledgeEntry | None,
    *,
    older_approved: KnowledgeEntry | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    latest_lookup = AsyncMock(return_value=latest)
    approved_lookup = AsyncMock(return_value=older_approved)
    # Support either a module-level import or an import inside the startup helper.
    monkeypatch.setattr(knowledge, "get_latest_response", latest_lookup)
    monkeypatch.setattr(readiness, "get_latest_response", latest_lookup, raising=False)
    monkeypatch.setattr(knowledge, "get_approved_response", approved_lookup)
    monkeypatch.setattr(readiness, "get_approved_response", approved_lookup, raising=False)
    return latest_lookup, approved_lookup


def test_g2_breb_key_settings_uses_environment_alias() -> None:
    settings = payment_settings(environment="testing", key=SYNTHETIC_KEY)
    assert getattr(settings, "bank_breb_key", None) == SYNTHETIC_KEY


@pytest.mark.parametrize("key", ["", " \t\n "])
async def test_g2_breb_key_blank_production_setting_rejects_active_payment(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    lookup, approved_lookup = patch_payment_lookup(monkeypatch, payment_entry())
    settings = payment_settings(key=key)
    error: ValueError | None = None
    try:
        await payment_validator()(settings, sentinel.payment_sessionmaker)
    except ValueError as caught:
        error = caught
    assert error is not None, "Una PAYMENT aprobada con Bre-B requiere BANK_BREB_KEY"
    assert KEY_ERROR in str(error), "El fallo de arranque debe identificar BANK_BREB_KEY"
    lookup.assert_awaited_once_with(sentinel.payment_sessionmaker, PAYMENT_CODE)
    approved_lookup.assert_not_awaited()


async def test_g2_breb_key_valid_production_setting_allows_active_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup, approved_lookup = patch_payment_lookup(monkeypatch, payment_entry())
    await payment_validator()(
        payment_settings(key=SYNTHETIC_KEY), sentinel.payment_sessionmaker
    )
    lookup.assert_awaited_once_with(sentinel.payment_sessionmaker, PAYMENT_CODE)
    approved_lookup.assert_not_awaited()


async def test_g2_breb_key_old_approved_payment_does_not_require_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup, approved_lookup = patch_payment_lookup(
        monkeypatch, payment_entry(uses_key=False, version=2)
    )
    await payment_validator()(payment_settings(), sentinel.payment_sessionmaker)
    lookup.assert_awaited_once_with(sentinel.payment_sessionmaker, PAYMENT_CODE)
    approved_lookup.assert_not_awaited()


async def test_g2_breb_key_unused_allowed_variable_does_not_require_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    latest = payment_entry(uses_key=False)
    latest.allowed_variables.append("breb_key")
    lookup, _ = patch_payment_lookup(monkeypatch, latest)
    await payment_validator()(payment_settings(), sentinel.payment_sessionmaker)
    lookup.assert_awaited_once_with(sentinel.payment_sessionmaker, PAYMENT_CODE)


async def test_g2_breb_key_missing_payment_does_not_require_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup, approved_lookup = patch_payment_lookup(monkeypatch, None)
    await payment_validator()(payment_settings(), sentinel.payment_sessionmaker)
    lookup.assert_awaited_once_with(sentinel.payment_sessionmaker, PAYMENT_CODE)
    approved_lookup.assert_not_awaited()


@pytest.mark.parametrize("status", ["DRAFT", "INACTIVE"])
async def test_g2_breb_key_latest_unapproved_payment_ignores_older_approved_version(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    lookup, approved_lookup = patch_payment_lookup(
        monkeypatch,
        payment_entry(status=status, version=4),
        older_approved=payment_entry(version=3),
    )
    await payment_validator()(payment_settings(), sentinel.payment_sessionmaker)
    lookup.assert_awaited_once_with(sentinel.payment_sessionmaker, PAYMENT_CODE)
    approved_lookup.assert_not_awaited()


@pytest.mark.parametrize("environment", ["testing", "development"])
async def test_g2_breb_key_nonproduction_does_not_query_payment_template(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    lookup, approved_lookup = patch_payment_lookup(monkeypatch, payment_entry())
    await payment_validator()(
        payment_settings(environment=environment), sentinel.payment_sessionmaker
    )
    lookup.assert_not_awaited()
    approved_lookup.assert_not_awaited()


@dataclass
class StartupHarness:
    module: ModuleType
    settings: Settings
    sessionmaker: Any
    events: list[str]
    dispose: AsyncMock
    validator: AsyncMock
    loops: list[AsyncMock]


def startup_harness(
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
    *,
    failure: bool,
) -> StartupHarness:
    module = import_module("app.main" if entrypoint == "API" else "app.channel.worker")
    settings = payment_settings(key="" if failure else SYNTHETIC_KEY)
    events: list[str] = []
    sessionmaker = sentinel.startup_sessionmaker
    dispose = AsyncMock(side_effect=lambda: events.append("dispose"))
    engine = SimpleNamespace(dispose=dispose)

    def create_engine(database_url: str, **kwargs: Any) -> Any:
        assert database_url == settings.database_url
        events.append("engine")
        return engine

    def create_sessionmaker(given_engine: Any) -> Any:
        assert given_engine is engine
        events.append("sessionmaker")
        return sessionmaker

    async def validate(given_settings: Settings, given_sessionmaker: Any) -> None:
        assert given_settings is settings
        assert given_sessionmaker is sessionmaker
        events.append("validate")
        if failure:
            raise ValueError("BANK_BREB_KEY is required by the approved payment template")

    validator = AsyncMock(side_effect=validate)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "configure_logging", lambda environment, level: None)
    monkeypatch.setattr(module, "create_engine", create_engine)
    monkeypatch.setattr(module, "create_sessionmaker", create_sessionmaker)
    monkeypatch.setattr(readiness, "validate_payment_settings", validator, raising=False)
    monkeypatch.setattr(module, "validate_payment_settings", validator, raising=False)

    loops: list[AsyncMock] = []
    if entrypoint == "WORKER":
        class FakeMetaClient:
            def __init__(self, given_settings: Settings) -> None:
                assert given_settings is settings
                events.append("meta_construct")

            async def __aenter__(self) -> Any:
                events.append("meta_enter")
                return sentinel.meta_sender

            async def __aexit__(self, *args: Any) -> None:
                events.append("meta_exit")

        monkeypatch.setattr(module, "WhatsAppOutboundClient", FakeMetaClient)
        for name in (
            "_run_outbox_loop",
            "_run_staff_outbox_loop",
            "_run_inbox_loop",
            "_run_payment_evidence_loop",
            "_run_reservation_expiration_loop",
            "_run_balance_reminder_loop",
            "_run_customer_notification_loop",
        ):
            loop = AsyncMock(return_value=None)
            monkeypatch.setattr(module, name, loop)
            loops.append(loop)
    return StartupHarness(module, settings, sessionmaker, events, dispose, validator, loops)


async def run_startup(harness: StartupHarness, entrypoint: str) -> None:
    if entrypoint == "API":
        fake_app = SimpleNamespace(state=SimpleNamespace())
        async with harness.module.lifespan(fake_app):
            harness.events.append("api_yield")
    else:
        await harness.module.run_worker()


@pytest.mark.parametrize("entrypoint", ["API", "WORKER"])
async def test_g2_breb_key_startup_validates_before_api_yield_or_meta(
    monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    harness = startup_harness(monkeypatch, entrypoint, failure=False)
    await run_startup(harness, entrypoint)
    assert "validate" in harness.events, "El arranque debe validar la plantilla de pago"
    boundary = "api_yield" if entrypoint == "API" else "meta_construct"
    assert harness.events.index("validate") < harness.events.index(boundary)
    harness.validator.assert_awaited_once_with(harness.settings, harness.sessionmaker)
    harness.dispose.assert_awaited_once()
    for loop in harness.loops:
        loop.assert_awaited_once()


@pytest.mark.parametrize("entrypoint", ["API", "WORKER"])
async def test_g2_breb_key_invalid_startup_disposes_engine_without_starting_consumers(
    monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    harness = startup_harness(monkeypatch, entrypoint, failure=True)
    error: ValueError | None = None
    try:
        await run_startup(harness, entrypoint)
    except ValueError as caught:
        error = caught
    assert error is not None, "Un fallo de validación debe impedir el arranque"
    assert KEY_ERROR in str(error)
    harness.validator.assert_awaited_once_with(harness.settings, harness.sessionmaker)
    harness.dispose.assert_awaited_once()
    assert "api_yield" not in harness.events
    assert "meta_construct" not in harness.events
    assert harness.events == ["engine", "sessionmaker", "validate", "dispose"]
    for loop in harness.loops:
        loop.assert_not_awaited()

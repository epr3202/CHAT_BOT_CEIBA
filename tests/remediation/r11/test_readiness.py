"""R11 configuration and operational contracts; no external provider calls."""

import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config.readiness import check_database, check_worker, validate_revision
from app.config.release_scope import ReleaseScope
from app.config.settings import Settings


def protected(**overrides):
    values = dict(
        ENVIRONMENT="staging",
        DEPLOYED_RUNTIME=True,
        DATABASE_URL="postgresql+asyncpg://test:test@db/test",
        META_APP_SECRET="synthetic",
        META_VERIFY_TOKEN="synthetic",
        META_ACCESS_TOKEN="synthetic",
        META_PHONE_NUMBER_ID="123",
        OPENROUTER_API_KEY="synthetic",
        CALENDAR_ADAPTER="google",
        PAYMENT_EVIDENCE_AUTOMATION_ENABLED=False,
        CALENDAR_WRITES_ENABLED=False,
    )
    return Settings(_env_file=None, **(values | overrides))


def test_e01_missing_deployed_environment(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ValueError, match="explicit"):
        ReleaseScope(_env_file=None, DEPLOYED_RUNTIME=True)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_e02_e03_protected_environment(environment):
    assert protected(ENVIRONMENT=environment).environment == environment


@pytest.mark.parametrize(
    "override",
    [
        {"CALENDAR_ADAPTER": "fake"},
        {"PAYMENT_EVIDENCE_AUTOMATION_ENABLED": True},
        {"CALENDAR_WRITES_ENABLED": True},
        {"META_APP_SECRET": ""},
        {"META_VERIFY_TOKEN": ""},
        {"META_PHONE_NUMBER_ID": ""},
        {"ENVIRONMENT": "development"},
        {"ENVIRONMENT": "testing"},
        {"WHATSAPP_API_BASE_URL": "http://fake.invalid"},
        {"OPENROUTER_BASE_URL": "http://fake.invalid"},
    ],
)
def test_e04_to_e09_invalid_protected_config(override):
    with pytest.raises(ValueError):
        protected(**override)


@pytest.mark.parametrize("environment", ["development", "testing"])
def test_e10_local_environment(environment):
    assert ReleaseScope(_env_file=None, ENVIRONMENT=environment).environment == environment


def test_m01_m03_known_chain():
    validate_revision(["20260910_0027"])
    validate_revision(["20260908_0026"], allow_ancestor=True)


@pytest.mark.parametrize("revisions", [[], ["unknown"], ["20260910_0027", "unknown"]])
def test_m02_unknown_revision(revisions):
    with pytest.raises(ValueError):
        validate_revision(revisions, allow_ancestor=True)


@pytest.mark.asyncio
async def test_h01_database_unreachable():
    engine = AsyncMock()
    engine.connect.side_effect = OSError("unreachable")
    with pytest.raises(OSError):
        await check_database(engine)


def test_h02_wrong_revision():
    with pytest.raises(ValueError):
        validate_revision(["20260908_0026"])


def test_h03_worker_stale_dead_and_polling(tmp_path):
    from app.config.readiness import heartbeat

    with pytest.raises(ValueError):
        check_worker(tmp_path)
    heartbeat("inbox", tmp_path)
    heartbeat("outbox", tmp_path)
    check_worker(tmp_path)
    with pytest.raises(ValueError):
        check_worker(tmp_path, now=time.monotonic() + 1000)


@pytest.mark.asyncio
async def test_h04_liveness_does_not_call_providers():
    from app.main import live

    assert await live() == {"status": "alive"}


def test_storage_must_be_explicit_and_existing(tmp_path):
    from app.config.readiness import validate_storage

    with pytest.raises(ValueError):
        validate_storage(protected())
    validate_storage(
        protected(CATALOG_STORAGE_DIR=str(tmp_path), PAYMENT_EVIDENCE_DIR=str(tmp_path))
    )


def test_build_excludes_secret_patterns():
    rules = Path(".dockerignore").read_text().splitlines()
    for pattern in (
        ".env",
        ".env.*",
        ".git",
        "**/*.pem",
        "**/credentials*",
        "**/secrets",
        ".*-work",
    ):
        assert pattern in rules
    assert "COPY . ." not in Path("Dockerfile").read_text()


@pytest.mark.asyncio
async def test_staging_reset_requires_explicit_override(monkeypatch):
    from types import SimpleNamespace

    from scripts import reset_local_conversation as reset

    monkeypatch.setattr(
        reset,
        "parse_args",
        lambda: SimpleNamespace(phone="+573001112233", allow_production_phone=False),
    )
    monkeypatch.setattr(reset, "get_settings", lambda: SimpleNamespace(environment="staging"))
    with pytest.raises(SystemExit, match="--allow-production-phone"):
        await reset.async_main()

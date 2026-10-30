from collections.abc import Callable, Iterator
from datetime import datetime
from importlib import import_module
from zoneinfo import ZoneInfo

import pytest

from tests.clock import FrozenDateTime
from tests.http_doubles import unrecognized_event_type_mock


@pytest.fixture(autouse=True)
def uncached_startup_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let capture_logs observe real processors after production readiness tests.

    A production startup otherwise caches bound loggers against its processor
    list. Later testing startups replace that list, so capture_logs can miss
    real ERROR events. Keep startup rendering/levels intact; disable only the
    cache in this test process, without mocking log emission or assertions.
    """
    import structlog

    main = import_module("app.main")
    configure = main.configure_logging

    def configure_uncached(environment: str, log_level: str = "INFO") -> None:
        configure(environment, log_level)
        structlog.configure(cache_logger_on_first_use=False)

    monkeypatch.setattr(main, "configure_logging", configure_uncached)


@pytest.fixture
def freeze_app_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[datetime | type[FrozenDateTime]], type[FrozenDateTime]]:
    """Freeze every wall-clock source reached by booking, payment and delivery.

    Each test owns its clock. Passing an existing clock class preserves tests that
    advance its instant to exercise later receipts and handoff/session lifecycles.
    PostgreSQL defaults deliberately keep their real clock: queue tests must seed
    their due timestamps explicitly instead of relying on the database's now().
    """

    def freeze(value: datetime | type[FrozenDateTime]) -> type[FrozenDateTime]:
        from app.main import app

        # Resolve deferred FastAPI datetime annotations against the real type first.
        app.openapi()
        if isinstance(value, datetime):

            class Clock(FrozenDateTime):
                instant = value

            clock = Clock
        else:
            clock = value
        modules = (
            "app.admin.routes",
            "app.agent.auth",
            "app.appointment.service",
            "app.catalog.service",
            "app.handoff.service",
            "app.channel.delivery",
            "app.channel.inbound",
            "app.channel.inbox",
            "app.channel.worker",
            "app.conversation.service",
            "app.notifications.customer_worker",
            "app.notifications.service",
            "app.notifications.statuses",
            "app.notifications.worker",
            "app.orchestrator.booking_flow",
            "app.orchestrator.service",
            "app.payment.review",
            "app.payment.service",
            "app.payment.worker",
            "app.reservation.availability",
            "app.reservation.booking",
            "app.reservation.notifications",
            "app.reservation.settlement",
            "app.scheduling.availability",
        )
        for name in modules:
            module = import_module(name)
            if hasattr(module, "datetime"):
                monkeypatch.setattr(module, "datetime", clock)
        # auth imports datetime inside functions; freeze that binding too, without
        # replacing authentication or changing its session-expiration checks.
        monkeypatch.setattr(import_module("datetime"), "datetime", clock)
        monkeypatch.setattr(
            import_module("app.orchestrator.service"),
            "current_bogota_datetime",
            lambda: clock.now(ZoneInfo("America/Bogota")),
        )
        return clock

    return freeze


@pytest.fixture
def unrecognized_event_type_http() -> Iterator[None]:
    """Opt-in only: tests declaring usefixtures own this HTTP double."""
    with unrecognized_event_type_mock():
        yield

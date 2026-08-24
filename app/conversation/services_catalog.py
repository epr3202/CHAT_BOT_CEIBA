from __future__ import annotations

from collections.abc import Sequence


def service_catalog_codes() -> tuple[str, ...]:
    raise NotImplementedError


def service_aliases(service_code: str) -> tuple[str, ...]:
    raise NotImplementedError


def match_requested_services(message_text: str) -> list[str] | None:
    raise NotImplementedError


def compose_requested_services_summary(service_values: Sequence[str]) -> str:
    raise NotImplementedError

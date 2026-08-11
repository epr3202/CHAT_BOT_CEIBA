from __future__ import annotations

from enum import StrEnum


class AIErrorReason(StrEnum):
    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"


class AIUnavailable(Exception):
    def __init__(self, reason: AIErrorReason, detail: str | None = None) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(reason.value)

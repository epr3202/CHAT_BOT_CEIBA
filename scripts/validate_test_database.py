"""Validate the explicit database destination before destructive test operations."""

from __future__ import annotations

import os
import re

from sqlalchemy.engine import make_url


def validate_test_database_url(value: str | None) -> str:
    if not value:
        raise RuntimeError("TEST_DATABASE_URL must be explicitly supplied")
    url = make_url(value)
    if (
        url.drivername != "postgresql+asyncpg"
        or not re.search(r"(?:^|_)test(?:_|$)", url.database or "", flags=re.IGNORECASE)
        or url.query
    ):
        raise RuntimeError("Refusing to reset a non-test database")
    return value


if __name__ == "__main__":
    validate_test_database_url(os.environ.get("TEST_DATABASE_URL"))

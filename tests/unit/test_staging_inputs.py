"""A1 rejects missing or placeholder destination input without external calls."""

import pytest

from scripts.staging import clean_value


@pytest.mark.parametrize("value", ["", " ", "TODO", "changeme", "example.com", "<host>"])
def test_staging_rejects_placeholder(value: str) -> None:
    assert not clean_value(value)


def test_staging_accepts_observed_identity() -> None:
    assert clean_value("ceiba-staging")

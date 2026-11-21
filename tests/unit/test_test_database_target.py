import pytest

from tests.integration.helpers import assert_safe_test_database_url


@pytest.mark.parametrize("name", ["ceiba", "contest", "latest"])
def test_non_test_target_rejected(name: str) -> None:
    with pytest.raises(RuntimeError):
        assert_safe_test_database_url("postgresql+asyncpg://localhost/" + name)

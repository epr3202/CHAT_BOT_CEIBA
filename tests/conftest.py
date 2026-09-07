from collections.abc import Iterator

import pytest

from tests.http_doubles import unrecognized_event_type_mock


@pytest.fixture
def unrecognized_event_type_http() -> Iterator[None]:
    """Opt-in only: tests declaring usefixtures own this HTTP double."""
    with unrecognized_event_type_mock():
        yield

import pytest

from app.channel.inbound import normalize_phone_number


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        ("+573001112233", "+573001112233"),
        ("573001112233", "+573001112233"),
        ("3001112233", "+573001112233"),
        ("(300) 111-2233", "+573001112233"),
    ],
)
def test_normalize_phone_number(raw_phone: str, expected: str) -> None:
    assert normalize_phone_number(raw_phone) == expected


def test_normalize_phone_number_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="phone_number must contain at least one digit"):
        normalize_phone_number("")

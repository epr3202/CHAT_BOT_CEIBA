"""Shared phone normalization, independent of inbound channel adapters."""


def normalize_phone_number(phone_number: str) -> str:
    digits = "".join(character for character in phone_number if character.isdigit())
    if not digits:
        raise ValueError("phone_number must contain at least one digit")
    if phone_number.strip().startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+57{digits}"
    return f"+{digits}"

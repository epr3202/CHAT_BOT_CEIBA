"""Deterministic lodging vocabulary; eligibility belongs to the orchestrator."""

import re

from app.conversation.catalog_event_type import normalize_catalog_event_type_label

LODGING_ALIAS_REASON = "LODGING_ALIAS"
_PATTERN = re.compile(
    r"\b(?:hotel|hoteles|hospedaje|hospedar|hospedarme|hospedarnos|habitacion|habitaciones|"
    r"alojamiento|alojar|alojarnos|estadia|posada|motel|dormir|pasar la noche|"
    r"noche de pareja|amanecer juntos)\b"
)


def match_lodging_label(message_text: str) -> str | None:
    match = _PATTERN.search(normalize_catalog_event_type_label(message_text))
    return match.group() if match is not None else None


def is_lodging_inquiry(message_text: str) -> bool:
    return match_lodging_label(message_text) is not None

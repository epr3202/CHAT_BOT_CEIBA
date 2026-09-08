"""Conservative recognition of a present, personal request for human attention."""

from __future__ import annotations

import re
import unicodedata

EXPLICIT_HUMAN_REASON = "DETERMINISTIC_EXPLICIT_HUMAN_REQUEST"
_PERSON = r"(?:un asesor|una asesora|una persona(?: del equipo)?|alguien)"
_REQUEST = re.compile(
    rf"(?:(?:quiero|necesito) hablar con {_PERSON}"
    rf"|me puedes comunicar con {_PERSON}"
    rf"|pasame (?:con )?{_PERSON}"
    r"|quiero que me atienda una persona(?: del equipo)?"
    r"|necesito una persona)"
)


def is_explicit_human_request(message_text: str) -> bool:
    """False means unrecognized; quoted, mixed or ambiguous turns keep normal routing."""
    normalized = " ".join(
        "".join(
            char
            for char in unicodedata.normalize("NFD", message_text.casefold())
            if unicodedata.category(char) != "Mn"
        ).split()
    )
    clauses = [part.strip() for part in re.split(r"[.!?;¿¡]+", normalized) if part.strip()]
    # This exact local negation rejects information, not the following human request.
    if clauses and clauses[0] == "no quiero mas informacion":
        clauses = clauses[1:]
    if not clauses:
        return False
    for clause in clauses:
        clause = re.sub(r"^por favor(?:,\s*|\s+)", "", clause)
        clause = re.sub(r"(?:,\s*|\s+)por favor$", "", clause)
        if _REQUEST.fullmatch(clause) is None:
            return False
    return True

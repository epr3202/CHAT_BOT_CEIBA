from __future__ import annotations

import string
import unicodedata
from typing import Literal

ContextualConfirmationIntent = Literal["CONFIRM", "DENY"]

AFFIRMATIONS = {
    "si",
    "correcto",
    "exacto",
    "asi es",
    "dale",
    "confirmo",
    "de acuerdo",
    "ok",
    "listo",
    "perfecto",
    "claro",
    "sip",
    "👍",
}
DENIALS = {
    "no",
    "incorrecto",
    "cambiar",
    "corregir",
    "esta mal",
    "modificar",
}


def resolve_contextual_confirmation(
    message_text: str,
    pending_action: str | None,
    last_question_code: str | None,
) -> ContextualConfirmationIntent | None:
    if not pending_action or not pending_action.startswith("CONFIRM_") or not last_question_code:
        return None
    normalized = normalize_confirmation_text(message_text)
    if normalized in AFFIRMATIONS:
        return "CONFIRM"
    if normalized in DENIALS:
        return "DENY"
    return None


def normalize_confirmation_text(message_text: str) -> str:
    stripped = message_text.strip().casefold()
    if stripped == "👍":
        return stripped
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFD", stripped)
        if unicodedata.category(char) != "Mn"
    )
    punctuation = string.punctuation + "¿¡"
    translation = str.maketrans("", "", punctuation)
    return " ".join(without_accents.translate(translation).split())

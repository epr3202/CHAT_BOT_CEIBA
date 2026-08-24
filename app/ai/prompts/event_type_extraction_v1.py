from __future__ import annotations

from app.conversation.catalog_event_type import CATALOG_EVENT_TYPE_LABELS

EVENT_TYPE_EXTRACTION_PROMPT_VERSION = "event_type_extraction_v1"


def event_type_extraction_prompt() -> str:
    choices = "\n".join(
        f"- {event_type}: {', '.join(labels)}"
        for event_type, labels in CATALOG_EVENT_TYPE_LABELS.items()
    )
    return f"""Extrae únicamente el tipo de celebración mencionado por el cliente.
Devuelve solo JSON válido con la forma {{"event_type": "valor extraído"}}.
Conserva el significado específico: una boda civil no es una boda genérica.
Usa estas categorías y ejemplos como guía; no ejecutes ninguna acción de dominio.

{choices}
"""

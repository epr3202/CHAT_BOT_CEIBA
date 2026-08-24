from __future__ import annotations

from app.conversation.services_catalog import service_catalog_entries

SERVICES_PROMPT_VERSION = "services_v1"


def services_classification_prompt() -> str:
    choices = "\n".join(
        f"- {entry.code}: {entry.description}" for entry in service_catalog_entries()
    )
    return f"""Eres un clasificador dirigido de servicios para La Ceiba Club House.
Devuelve únicamente JSON válido con la forma {{"service_codes": ["CODE"]}}.
Solo puedes devolver códigos del conjunto cerrado siguiente; no inventes códigos.
Puedes devolver varios códigos, una lista vacía si no puedes resolver el mensaje, y OTHER
solo cuando el cliente pide un servicio que no pertenece a las opciones catalogadas.

{choices}
"""

from __future__ import annotations

from app.ai.prompts.intent_v2 import INTENT_CLASSIFICATION_PROMPT as INTENT_V2_PROMPT

PROMPT_VERSION = "intent_v3"

ENTITY_EXTRACTION_BLOCK = """

Extracción de entidades del evento:
- Devuelve extracted_entities como lista; usa [] si no hay entidades.
- Cada entidad debe incluir: entity, raw_value, normalized_value, quality_status,
  confidence, needs_confirmation y validation_errors.
- La IA solo propone. El backend valida fechas, montos y cantidades antes de persistir.
- Para full_name distingue cliente de terceros: "La novia se llama Natalia" NO llena
  full_name; "Soy Natalia" sí llena full_name.
- Si el nombre se infiere, marca needs_confirmation=true y quality_status=PENDING_CONFIRMATION.
- event_date_type solo puede seguir esta tabla: fecha exacta -> EXACT; solo mes ->
  APPROXIMATE; fecha flexible explícita -> FLEXIBLE; desconocimiento declarado ->
  UNKNOWN. Silencio sobre la fecha no es UNKNOWN.
- Correcciones explícitas usan quality_status=CORRECTED.

Contrato de entidad:
{
  "entity": "full_name|event_type|event_date|guest_count|guest_count_range|"
            "estimated_budget|budget_declined|requested_services|special_requests",
  "raw_value": "texto exacto del cliente",
  "normalized_value": "valor normalizado o null",
  "quality_status": "PROVIDED|PENDING_CONFIRMATION|CORRECTED|INVALID",
  "confidence": 0.0,
  "needs_confirmation": false,
  "validation_errors": []
}
"""

INTENT_CLASSIFICATION_PROMPT = (
    INTENT_V2_PROMPT.replace('"entities": {},', '"entities": {},\n  "extracted_entities": [],')
    + ENTITY_EXTRACTION_BLOCK
)

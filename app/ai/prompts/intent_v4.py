from __future__ import annotations

from app.ai.prompts.intent_v3 import INTENT_CLASSIFICATION_PROMPT as INTENT_V3_PROMPT

PROMPT_VERSION = "intent_v4"

CONTEXTUAL_CONFIRMATION_BLOCK = """

Confirmaciones contextuales:
- CONFIRM y DENY son intenciones contextuales; no deben usarse sin pending_action.
- Si pending_action empieza por CONFIRM_ y last_question_code existe, interpreta respuestas
  breves como "correcto", "sí", "de acuerdo" u "ok" como CONFIRM.
- Si pending_action empieza por CONFIRM_ y el cliente niega con contenido correctivo
  ("no, son 40 personas"), usa MODIFY_EVENT_DATA y extrae la corrección.
- Si pending_action es null o last_question_code es null, respuestas como "sí" o
  "correcto" deben ser UNKNOWN con baja confianza.
"""

INTENT_CLASSIFICATION_PROMPT = INTENT_V3_PROMPT + CONTEXTUAL_CONFIRMATION_BLOCK

from __future__ import annotations

import re
from typing import Any

from app.conversation.catalog_event_type import resolve_catalog_event_type_label
from app.event.models import EVENT_TYPES


def normalize_event_type(value: Any | None) -> str | None:
    """Return a canonical event type or ``None`` for an unknown entity value."""
    if value is None:
        return None
    original_value = str(value)
    normalized = re.sub(r"[-\s]+", "_", original_value.strip().upper())
    if normalized in EVENT_TYPES:
        return normalized
    return resolve_catalog_event_type_label(original_value)

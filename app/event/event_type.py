from __future__ import annotations

import re
from typing import Any

from app.event.models import EVENT_TYPES


def normalize_event_type(value: Any | None) -> str | None:
    """Return a canonical event type or ``None`` for an unknown entity value."""
    if value is None:
        return None
    normalized = re.sub(r"[-\s]+", "_", str(value).strip().upper())
    return normalized if normalized in EVENT_TYPES else None

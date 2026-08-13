from __future__ import annotations

import app.models_registry  # noqa: F401
from app.config.database import Base


def test_models_registry_loads_complete_metadata_table_set() -> None:
    expected_tables = {
        "ai_execution",
        "agent",
        "agent_session",
        "audit_event",
        "catalog_asset",
        "catalog_event_type_map",
        "catalog_send",
        "conversation",
        "customer",
        "event",
        "event_service_request",
        "handoff",
        "knowledge_entry",
        "lead",
        "message",
        "message_provider_status",
        "outbox",
        "quote_request",
        "webhook_event",
    }

    assert set(Base.metadata.tables) == expected_tables

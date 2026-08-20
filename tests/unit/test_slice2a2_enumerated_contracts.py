from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from app.catalog.models import CatalogEventTypeMap
from app.event.models import EVENT_TYPES, Event
from app.handoff.service import HANDOFF_REASONS

EVENT_TYPES_BEFORE = (
    "WEDDING",
    "CIVIL_WEDDING",
    "PROPOSAL",
    "BIRTHDAY",
    "GRADUATION",
    "ANNIVERSARY",
    "ROMANTIC_DINNER",
    "CORPORATE_EVENT",
    "FAMILY_EVENT",
    "BAPTISM",
    "FIRST_COMMUNION",
    "BABY_SHOWER",
    "WORKSHOP",
    "POOL_DAY",
    "PRIVATE_DINNER",
    "OTHER",
)
EVENT_TYPES_AFTER = (*EVENT_TYPES_BEFORE[:-1], "GENDER_REVEAL", "OTHER")
HANDOFF_REASONS_BEFORE = (
    "CUSTOMER_REQUEST",
    "QUOTE_PREPARATION",
    "PRICE_NEGOTIATION",
    "DISCOUNT_REQUEST",
    "PAYMENT_REVIEW",
    "RESERVATION_CONFIRMATION",
    "CANCELLATION",
    "COMPLAINT",
    "LOW_CONFIDENCE",
    "UNSUPPORTED_REQUEST",
    "CAPACITY_REVIEW",
    "SPECIAL_EVENT",
    "SUPPLIER_CONFIRMATION",
    "URGENT_EVENT",
    "SYSTEM_ERROR",
    "REPEATED_NO_SHOW",
    "MANUAL_TAKEOVER",
    "OTHER",
)
HANDOFF_REASONS_AFTER = (
    *HANDOFF_REASONS_BEFORE[:-1],
    "TEMPLATE_UNAVAILABLE",
    "CATALOG_NOT_AVAILABLE",
    "OTHER",
)
EVENT_MIGRATION = Path("alembic/versions/20260819_0020_gender_reveal_event_type.py")
HANDOFF_MIGRATION = Path("alembic/versions/20260819_0021_catalog_handoff_reasons.py")


class MigrationOpsRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def execute(self, statement: object) -> None:
        self.calls.append(("execute", (str(statement),), {}))

    def drop_constraint(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("drop_constraint", args, kwargs))

    def create_check_constraint(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("create_check_constraint", args, kwargs))


def load_migration(path: Path, name: str) -> ModuleType:
    assert path.exists(), f"Missing required migration: {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def constraint_sql(model: type[object], name: str) -> str:
    constraint = next(item for item in model.__table__.constraints if item.name == name)
    return str(constraint.sqltext)


def created_constraint_values(
    recorder: MigrationOpsRecorder, constraint_name: str
) -> tuple[str, ...]:
    call = next(
        item
        for item in recorder.calls
        if item[0] == "create_check_constraint" and item[1][0] == constraint_name
    )
    condition = str(call[1][2])
    return tuple(re.findall(r"'([^']+)'", condition))


def test_gender_reveal_is_accepted_by_event_and_catalog_mapping_metadata() -> None:
    assert EVENT_TYPES == EVENT_TYPES_AFTER
    assert "GENDER_REVEAL" in constraint_sql(Event, "ck_event_type")
    assert "GENDER_REVEAL" in constraint_sql(
        CatalogEventTypeMap, "ck_catalog_event_type_map_event_type"
    )
    assert Event(lead_id=uuid4(), event_type="GENDER_REVEAL").event_type == "GENDER_REVEAL"
    mapping = CatalogEventTypeMap(
        catalog_asset_id=uuid4(), event_type="GENDER_REVEAL", send_mode="ON_REQUEST"
    )
    assert mapping.event_type == "GENDER_REVEAL"


def test_handoff_reason_python_and_metadata_catalogs_are_exact() -> None:
    from app.handoff.models import Handoff

    assert HANDOFF_REASONS == HANDOFF_REASONS_AFTER
    sql = constraint_sql(Handoff, "ck_handoff_reason")
    assert all(f"'{reason}'" in sql for reason in HANDOFF_REASONS_AFTER)
    assert sql.count("'") == len(HANDOFF_REASONS_AFTER) * 2


def test_event_type_migration_declares_exact_upgrade_and_downgrade_catalogs() -> None:
    migration = load_migration(EVENT_MIGRATION, "gender_reveal_event_type_0020")

    assert migration.down_revision == "20260819_0019"
    assert migration.EVENT_TYPES_BEFORE == EVENT_TYPES_BEFORE
    assert migration.EVENT_TYPES_AFTER == EVENT_TYPES_AFTER
    upgrade = MigrationOpsRecorder()
    migration.op = upgrade
    migration.upgrade()
    assert created_constraint_values(upgrade, "ck_event_type") == EVENT_TYPES_AFTER
    assert (
        created_constraint_values(upgrade, "ck_catalog_event_type_map_event_type")
        == EVENT_TYPES_AFTER
    )

    downgrade = MigrationOpsRecorder()
    migration.op = downgrade
    migration.downgrade()
    assert created_constraint_values(downgrade, "ck_event_type") == EVENT_TYPES_BEFORE
    assert (
        created_constraint_values(downgrade, "ck_catalog_event_type_map_event_type")
        == EVENT_TYPES_BEFORE
    )
    cleanup_sql = "\n".join(
        call[1][0] for call in downgrade.calls if call[0] == "execute"
    )
    assert "GENDER_REVEAL" in cleanup_sql
    assert "event" in cleanup_sql
    assert "catalog_event_type_map" in cleanup_sql
    assert next(call[0] for call in downgrade.calls) == "execute"


def test_handoff_reason_migration_uses_verified_exact_before_and_after_catalogs() -> None:
    migration = load_migration(HANDOFF_MIGRATION, "catalog_handoff_reasons_0021")

    assert migration.down_revision == "20260819_0020"
    assert migration.HANDOFF_REASONS_BEFORE == HANDOFF_REASONS_BEFORE
    assert migration.HANDOFF_REASONS_AFTER == HANDOFF_REASONS_AFTER
    upgrade = MigrationOpsRecorder()
    migration.op = upgrade
    migration.upgrade()
    assert created_constraint_values(upgrade, "ck_handoff_reason") == HANDOFF_REASONS_AFTER

    downgrade = MigrationOpsRecorder()
    migration.op = downgrade
    migration.downgrade()
    assert created_constraint_values(downgrade, "ck_handoff_reason") == HANDOFF_REASONS_BEFORE
    cleanup_sql = "\n".join(
        call[1][0] for call in downgrade.calls if call[0] == "execute"
    )
    assert "TEMPLATE_UNAVAILABLE" in cleanup_sql
    assert "CATALOG_NOT_AVAILABLE" in cleanup_sql
    assert "SET reason = 'OTHER'" in cleanup_sql
    assert next(call[0] for call in downgrade.calls) == "execute"

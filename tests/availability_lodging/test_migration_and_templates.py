import asyncio
import re
from datetime import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from data.knowledge_seed import CONDITIONAL_DRAFT_CODES, iter_seed_entries
from tests.availability_lodging.helpers import CONFIRM_AVAILABILITY, NEW_TEMPLATES
from tests.integration.helpers import configure_test_database, ensure_test_database_exists


@pytest.mark.parametrize("code,variables", list(NEW_TEMPLATES.items()))
# Cambio de contrato autorizado por Emerson: adenda de Leandro del 2026-10-29.
def test_R_new_sensitive_templates_seed_as_approved_v1(
    code: str, variables: tuple[str, ...]
) -> None:
    assert code not in CONDITIONAL_DRAFT_CODES
    entries = [entry for entry in iter_seed_entries() if entry.code == code]
    assert len(entries) == 1
    assert entries[0].status == "APPROVED"
    assert entries[0].version == 1
    assert set(entries[0].allowed_variables) == set(variables)
    assert "DRAFT" not in entries[0].answer_template


@pytest.mark.parametrize("checkin,checkout", [("15:00", "11:00"), ("16:30", "10:30")])
async def test_R_0037_backfill_and_clean_migrate_cycle(
    monkeypatch: pytest.MonkeyPatch, checkin: str, checkout: str
) -> None:
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    revision = next(
        (revision for revision in scripts.walk_revisions() if revision.revision == "20261028_0037"),
        None,
    )
    assert revision is not None, "Falta la única migración 20261028_0037_plan_overnight"
    assert revision.down_revision == "20261007_0036"
    assert "plan_overnight" in Path(revision.path).stem
    assert scripts.get_heads() == ["20261028_0037"]
    monkeypatch.setenv("LODGING_CHECKIN_FROM", checkin)
    monkeypatch.setenv("LODGING_CHECKOUT_TIME", checkout)
    url = configure_test_database(monkeypatch)
    await ensure_test_database_exists(url)
    engine = create_async_engine(url)

    async def snapshot() -> dict[str, Any]:
        async with engine.connect() as connection:

            def read(sync: Any) -> dict[str, Any]:
                inspector = inspect(sync)
                return {
                    name: {
                        "columns": [
                            (c["name"], str(c["type"]), c["nullable"])
                            for c in inspector.get_columns(name)
                        ],
                        "checks": inspector.get_check_constraints(name),
                        "fks": inspector.get_foreign_keys(name),
                        "indexes": inspector.get_indexes(name),
                    }
                    for name in inspector.get_table_names()
                }

            return await connection.run_sync(read)

    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await asyncio.to_thread(command.upgrade, config, "20261007_0036")
        async with engine.begin() as connection:
            for code in ("REFUGIO_DOS", "RITUAL_CORAZON"):
                await connection.execute(
                    text(
                        "INSERT INTO plan (plan_id, code, name, event_type, price_cop, "
                        "duration_minutes, exclusive, weekend_only, active, sort_order) "
                        "VALUES (:id, :code, :code, 'ROMANTIC_DINNER', "
                        "250000, 180, false, false, true, 1)"
                    ),
                    {"id": uuid4(), "code": code},
                )
        before = await snapshot()
        await asyncio.to_thread(command.upgrade, config, "20261028_0037")
        after = await snapshot()
        # The catalog is also enforced by PostgreSQL; the same single 0037
        # migration must extend its CHECK on already-migrated production DBs.
        assert {k: v for k, v in before.items() if k not in {"plan", "conversation"}} == {
            k: v for k, v in after.items() if k not in {"plan", "conversation"}
        }
        assert {k: v for k, v in before["conversation"].items() if k != "checks"} == {
            k: v for k, v in after["conversation"].items() if k != "checks"
        }
        before_checks = {
            check["name"]: check["sqltext"] for check in before["conversation"]["checks"]
        }
        after_checks = {
            check["name"]: check["sqltext"] for check in after["conversation"]["checks"]
        }
        before_pending = before_checks.pop("ck_conversation_pending_action")
        after_pending = after_checks.pop("ck_conversation_pending_action")
        assert before_checks == after_checks
        assert set(re.findall(r"'([^']+)'", after_pending)) == {
            *re.findall(r"'([^']+)'", before_pending),
            CONFIRM_AVAILABILITY,
        }
        assert set(after["plan"]["columns"]) - set(before["plan"]["columns"]) == {
            ("overnight", "BOOLEAN", False),
            ("checkin_from", "TIME", True),
            ("checkout_time", "TIME", True),
        }
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT code, overnight, checkin_from, checkout_time, duration_minutes "
                        "FROM plan ORDER BY code"
                    )
                )
            ).all()
        assert rows == [
            ("REFUGIO_DOS", True, time.fromisoformat(checkin), time.fromisoformat(checkout), 180),
            ("RITUAL_CORAZON", False, None, None, 180),
        ]
        await asyncio.to_thread(command.downgrade, config, "20261007_0036")
        assert await snapshot() == before
        await asyncio.to_thread(command.upgrade, config, "20261028_0037")
        assert await snapshot() == after
    finally:
        await engine.dispose()

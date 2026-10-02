"""R1/R2/R5: explicit D1-D3 contracts; business guards belong to B1b/B2 callers."""

from itertools import product
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, String
from sqlalchemy.ext.asyncio import AsyncSession

import app.models_registry  # noqa: F401
from app.audit.models import AuditEvent
from app.config.database import Base
from app.payment.models import PaymentEvidence
from tests.b1a_contracts import STATUSES, VALID_TRANSITIONS, require_module, require_symbol


@pytest.mark.parametrize("old,new", list(product(STATUSES, repeat=2)))
async def test_r1_all_25_reservation_transitions(old: str, new: str) -> None:
    service = require_module("app.reservation.service")
    transition = require_symbol("app.reservation.service", "transition_reservation")
    error_type = getattr(service, "InvalidReservationTransition", None)
    assert isinstance(error_type, type) and issubclass(error_type, ValueError)
    assert error_type is not ValueError, "La transición inválida requiere ValueError tipada"
    model = require_symbol("app.reservation.models", "Reservation")
    reservation = model(reservation_id=uuid4(), status=old)
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    request_id = str(uuid4())
    kwargs = {"actor": "Admin B1a", "reason": "Revisión humana", "request_id": request_id}

    # B2: a rejected or partial payment returns the request to payment pending.
    allowed = VALID_TRANSITIONS | {("PAYMENT_REVIEW", "PAYMENT_PENDING")}
    if (old, new) not in allowed:
        with pytest.raises(error_type):
            await transition(session, reservation, new, **kwargs)
        assert reservation.status == old
        session.add.assert_not_called()
        session.add_all.assert_not_called()
    else:
        # Deliberately no payment/calendar data: D2 validates only the matrix here.
        await transition(session, reservation, new, **kwargs)
        assert reservation.status == new
        audits = [
            call.args[0]
            for call in session.add.call_args_list
            if isinstance(call.args[0], AuditEvent)
        ]
        assert len(audits) == 1
        audit = audits[0]
        assert audit.action == "RESERVATION_STATUS_CHANGED"
        assert audit.entity == "reservation"
        assert audit.actor == kwargs["actor"]
        assert audit.reason == kwargs["reason"]
        assert audit.request_id == request_id
        assert audit.old_value["status"] == old
        assert audit.new_value["status"] == new
        assert audit.new_value["reservation_id"] == str(reservation.reservation_id)
    session.commit.assert_not_called()


@pytest.mark.parametrize("field", ["actor", "reason"])
@pytest.mark.parametrize("empty", ["", " ", "\t\n"])
async def test_r1_empty_actor_or_reason_has_no_effect(field: str, empty: str) -> None:
    transition = require_symbol("app.reservation.service", "transition_reservation")
    model = require_symbol("app.reservation.models", "Reservation")
    reservation = model(reservation_id=uuid4(), status="PAYMENT_PENDING")
    session = Mock(spec=AsyncSession)
    arguments = {"actor": "Admin", "reason": "Solicitado por cliente", "request_id": str(uuid4())}
    arguments[field] = empty
    with pytest.raises(ValueError):
        await transition(session, reservation, "CANCELLED", **arguments)
    assert reservation.status == "PAYMENT_PENDING"
    session.add.assert_not_called()
    session.add_all.assert_not_called()


@pytest.mark.parametrize("event_type", ["ROMANTIC_DINNER", "PROPOSAL", "WEDDING", "UNKNOWN", ""])
def test_r2_plan_event_type_orm_contract(event_type: str) -> None:
    module = require_module("app.plan.models")
    assert module.PLAN_EVENT_TYPES == ("ROMANTIC_DINNER", "PROPOSAL")
    model = require_symbol("app.plan.models", "Plan")
    if event_type in ("ROMANTIC_DINNER", "PROPOSAL"):
        assert model(event_type=event_type).event_type == event_type
    else:
        with pytest.raises(ValueError):
            model(event_type=event_type)
        plan = model(event_type="PROPOSAL")
        with pytest.raises(ValueError):
            plan.event_type = event_type


def test_r2_plan_registered_as_text_with_database_check() -> None:
    assert "plan" in Base.metadata.tables, "B1a: Plan no está registrado"
    table = Base.metadata.tables["plan"]
    assert isinstance(table.c.event_type.type, String)
    assert not getattr(table.c.event_type.type, "native_enum", False)
    checks = [str(item.sqltext) for item in table.constraints if isinstance(item, CheckConstraint)]
    assert any(
        "event_type" in sql and "ROMANTIC_DINNER" in sql and "PROPOSAL" in sql for sql in checks
    )


def test_r5_payment_evidence_nullable_reservation_foreign_key() -> None:
    columns = PaymentEvidence.__table__.c
    assert "reservation_id" in columns, "B1a: falta payment_evidence.reservation_id"
    column = columns.reservation_id
    assert column.nullable
    assert {fk.target_fullname for fk in column.foreign_keys} == {"reservation.reservation_id"}
    assert column.type.python_type is type(uuid4())


def test_r3_one_migration_directly_after_0027() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = scripts.get_heads()
    assert len(heads) == 1
    # Keep the B1a lineage contract valid when later slices add successors.
    lineage = {revision.revision: revision for revision in scripts.walk_revisions()}
    assert "20260930_0028" in lineage, "B1a: falta la migración de planes y reservas"
    assert lineage["20260930_0028"].down_revision == "20260910_0027"


def test_r3_deploy_seeds_plans_after_knowledge_before_start() -> None:
    script = Path("deploy.sh").read_text()
    assert "python scripts/load_plans.py" in script, "B1a: falta el seed en deploy.sh"
    assert (
        script.index("alembic upgrade head")
        < script.index("python scripts/load_knowledge.py")
        < script.index("python scripts/load_plans.py")
        < script.index("docker compose up -d --no-deps app worker")
    )


def test_r3_cinema_duration_has_explicit_seed_todo() -> None:
    path = Path("scripts/load_plans.py")
    assert path.is_file(), "B1a: falta scripts/load_plans.py"
    source = path.read_text()
    assert "TODO" in source and "Cinema" in source and "180" in source

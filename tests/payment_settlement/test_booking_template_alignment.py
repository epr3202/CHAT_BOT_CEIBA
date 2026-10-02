import pytest
from sqlalchemy import select

from app.conversation.models import KnowledgeEntry
from app.main import app
from data.knowledge_seed import CONDITIONAL_DRAFT_CODES, NON_RENDERABLE_CODES, iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries

APPROVED_CODES = [
    "RESP-BOOKING-PLAN-001",
    "RESP-BOOKING-DATETIME-001",
    "RESP-BOOKING-TIME-001",
    "RESP-BOOKING-UNAVAILABLE-001",
    "RESP-BOOKING-CONFIRM-001",
    "RESP-BOOKING-PAYMENT-001",
    "RESP-BOOKING-EVIDENCE-001",
    "RESP-BOOKING-CONFIRMED-001",
    "RESP-BOOKING-PARTIAL-001",
    "RESP-BOOKING-REJECTED-001",
    "RESP-PAYMENT-004",
    "RESP-PAYMENT-005",
    "RESP-FILE-002",
    "RESP-EVENTS-ROMANTIC-001",
    "RESP-EVENTS-PROPOSAL-001",
    "RESP-BOOKING-BALANCE-PAID-001",
    "RESP-BOOKING-BALANCE-PARTIAL-001",
]


@pytest.mark.parametrize("code", APPROVED_CODES)
def test_seed_matches_approved_production_codes(code):
    entries = {entry.code: entry for entry in iter_seed_entries()}
    assert code in entries, f"Falta plantilla aprobada {code}"
    assert entries[code].status == "APPROVED", f"{code} debe sembrarse APPROVED"
    assert code not in CONDITIONAL_DRAFT_CODES and code not in NON_RENDERABLE_CODES
    assert not entries[code].answer_template.startswith("[REVISAR]")


def test_file_receipt_has_payment_receipt_literal():
    entries = {entry.code: entry for entry in iter_seed_entries()}
    assert entries["RESP-FILE-002"].answer_template == entries["RESP-PAYMENT-002"].answer_template


async def test_seed_preserves_existing_rows_for_approved_codes(client):
    codes = set(APPROVED_CODES) - {
        "RESP-BOOKING-BALANCE-PAID-001",
        "RESP-BOOKING-BALANCE-PARTIAL-001",
    }
    async with app.state.db_sessionmaker.begin() as session:
        for entry in await session.scalars(
            select(KnowledgeEntry).where(KnowledgeEntry.code.in_(codes))
        ):
            entry.answer_template = "Texto aprobado y editado previamente"
            entry.status = "APPROVED"
        session.add(
            KnowledgeEntry(
                code="RESP-BOOKING-CONFIRMED-001",
                version=2,
                category="Reserva",
                question_summary="Producción",
                answer_template="Texto v2 conservado",
                allowed_variables=[],
                status="APPROVED",
            )
        )
    async with app.state.db_sessionmaker() as session:
        before = [
            (r.id, r.code, r.version, r.answer_template, r.status, r.updated_at_version)
            for r in await session.scalars(
                select(KnowledgeEntry)
                .where(KnowledgeEntry.code.in_(codes))
                .order_by(KnowledgeEntry.id)
            )
        ]
    await load_knowledge_entries(app.state.db_sessionmaker, list(iter_seed_entries()))
    async with app.state.db_sessionmaker() as session:
        after = [
            (r.id, r.code, r.version, r.answer_template, r.status, r.updated_at_version)
            for r in await session.scalars(
                select(KnowledgeEntry)
                .where(KnowledgeEntry.code.in_(codes))
                .order_by(KnowledgeEntry.id)
            )
        ]
    assert after == before, (
        "El seed debe conservar cada fila previa incluso con versiones productivas"
    )

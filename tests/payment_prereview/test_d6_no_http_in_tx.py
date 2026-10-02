"""D6 adversarial contracts: provider I/O releases evidence locks and DB transactions."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.models import AIExecution
from app.ai.receipt import ReceiptExtraction
from app.audit.models import AuditEvent
from app.config.settings import Settings, get_settings
from app.main import app
from app.payment import review as payment_review
from app.payment.models import PaymentEvidence, PaymentEvidenceReview
from app.payment.worker import process_payment_prereview_once
from tests.integration.helpers import login_headers
from tests.integration.test_b1a_plan_reservation_admin import seed_evidence

NOW = datetime(2026, 10, 2, 15, tzinfo=UTC)


def configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    monkeypatch.setenv("PAYMENT_REVIEW_AI_ENABLED", "true")
    monkeypatch.setenv("PAYMENT_EVIDENCE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTBOX_SENDING_TIMEOUT_SECONDS", "120")
    get_settings.cache_clear()
    return get_settings()


def extraction() -> ReceiptExtraction:
    result = ReceiptExtraction.model_validate_json(
        json.dumps(
            dict(
                amount_cop=100000,
                currency="COP",
                transaction_date="2026-10-02",
                transaction_time="10:00",
                reference="D6-RECEIPT",
                bank="Banco de prueba",
                destination_account_last4="8762",
                sender_name="Cliente Prueba",
                confidence=0.95,
                notes=None,
            )
        )
    )
    result._telemetry = {"latency_ms": 1, "prompt_tokens": 10, "completion_tokens": 10}
    return result


async def downloaded(tmp_path: Path) -> PaymentEvidence:
    evidence = await seed_evidence()
    path = tmp_path / f"{evidence.id}.jpg"
    path.write_bytes(b"synthetic D6 receipt")
    async with app.state.db_sessionmaker.begin() as session:
        row = await session.get(PaymentEvidence, evidence.id)
        assert row is not None
        row.download_status = "DOWNLOADED"
        row.storage_path = str(path)
    return evidence


def require_lease_columns() -> None:
    for name in ("prereview_claim_token", "prereview_claimed_at"):
        assert getattr(PaymentEvidence, name, None) is not None, (
            f"D6: falta payment_evidence.{name}"
        )


def track_sessions(monkeypatch: pytest.MonkeyPatch) -> list[AsyncSession]:
    sessions: list[AsyncSession] = []

    class ObservedSession(AsyncSession):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            sessions.append(self)

    sm = async_sessionmaker(app.state.db_engine, class_=ObservedSession, expire_on_commit=False)
    monkeypatch.setattr(app.state, "db_sessionmaker", sm)
    return sessions


async def invoke(
    path: str,
    client: AsyncClient,
    evidence_id: int,
    settings: Settings,
    headers: dict[str, str],
) -> None:
    if path == "worker":
        assert (
            await process_payment_prereview_once(
                app.state.db_sessionmaker, settings=settings, now=NOW
            )
            == 1
        )
    else:
        response = await client.post(
            f"/admin/payment-evidence/{evidence_id}/prereview", headers=headers
        )
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("path", ["worker", "endpoint"])
async def test_p1_extraction_has_no_transaction_and_evidence_lock_is_free(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
) -> None:
    settings = configure(monkeypatch, tmp_path)
    evidence = await downloaded(tmp_path)
    headers = await login_headers(client, "90000000")
    sessions = track_sessions(monkeypatch)
    calls = 0

    async def unlocked_extract(content: bytes, mime: str, config: Settings) -> ReceiptExtraction:
        nonlocal calls
        calls += 1
        assert content == b"synthetic D6 receipt" and mime == "image/jpeg"
        assert not any(session.in_transaction() for session in sessions), (
            "D6: extract_receipt fue llamado con una transacción abierta"
        )
        try:
            async with app.state.db_sessionmaker.begin() as other:
                locked = await other.scalar(
                    select(PaymentEvidence)
                    .where(PaymentEvidence.id == evidence.id)
                    .with_for_update(nowait=True)
                )
                assert locked is not None
        except DBAPIError as error:
            raise AssertionError(
                "D6: la evidencia sigue bloqueada durante la extracción"
            ) from error
        return extraction()

    monkeypatch.setattr(payment_review, "extract_receipt", unlocked_extract)
    await invoke(path, client, evidence.id, settings, headers)
    assert calls == 1
    async with app.state.db_sessionmaker() as session:
        reviews = list(
            await session.scalars(
                select(PaymentEvidenceReview).where(
                    PaymentEvidenceReview.evidence_id == evidence.id
                )
            )
        )
        assert len(reviews) == 1 and reviews[0].status == "COMPLETED"


@pytest.mark.parametrize("path", ["worker", "endpoint"])
async def test_p2_human_accepts_during_extraction_and_ai_result_is_discarded(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
) -> None:
    settings = configure(monkeypatch, tmp_path)
    evidence = await downloaded(tmp_path)
    headers = await login_headers(client, "90000000")
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_extract(content: bytes, mime: str, config: Settings) -> ReceiptExtraction:
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return extraction()

    monkeypatch.setattr(payment_review, "extract_receipt", slow_extract)
    task = asyncio.create_task(invoke(path, client, evidence.id, settings, headers))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        try:
            response = await asyncio.wait_for(
                client.post(
                    f"/admin/payment-evidence/{evidence.id}/accept",
                    headers=headers,
                    json={"amount_cop": 100000, "note": "Verificado por el asesor"},
                ),
                2,
            )
        except TimeoutError as error:
            raise AssertionError("D6: la extracción bloqueó la aceptación humana") from error
        assert response.status_code == 200, response.text
    finally:
        release.set()
        await task
    async with app.state.db_sessionmaker() as session:
        row = await session.get(PaymentEvidence, evidence.id)
        assert row is not None and row.review_status == "ACCEPTED" and row.amount_cop == 100000
        assert (
            await session.scalar(
                select(PaymentEvidenceReview).where(
                    PaymentEvidenceReview.evidence_id == evidence.id
                )
            )
            is None
        ), "D6: una propuesta obsoleta no se inserta en payment_evidence_review"
        assert (
            await session.scalar(
                select(AIExecution).where(AIExecution.task == "RECEIPT_EXTRACTION")
            )
            is None
        ), "D6: la propuesta descartada no persiste una ejecución huérfana"
        audits = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.action == "PAYMENT_PREREVIEW_DISCARDED")
            )
        )
        assert len(audits) == 1 and audits[0].new_value["evidence_id"] == evidence.id


async def test_p3_expired_prereview_lease_is_reclaimed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    require_lease_columns()
    settings = configure(monkeypatch, tmp_path)
    evidence = await downloaded(tmp_path)
    stale_token = uuid4()
    async with app.state.db_sessionmaker.begin() as session:
        row = await session.get(PaymentEvidence, evidence.id)
        assert row is not None
        row.prereview_claim_token = stale_token
        row.prereview_claimed_at = NOW - timedelta(
            seconds=settings.outbox_sending_timeout_seconds + 1
        )

    async def claimed_extract(content: bytes, mime: str, config: Settings) -> ReceiptExtraction:
        async with app.state.db_sessionmaker() as session:
            row = await session.get(PaymentEvidence, evidence.id)
            assert row is not None
            assert (
                row.prereview_claim_token is not None and row.prereview_claim_token != stale_token
            )
            assert row.prereview_claimed_at == NOW
        return extraction()

    monkeypatch.setattr(payment_review, "extract_receipt", claimed_extract)
    assert (
        await process_payment_prereview_once(app.state.db_sessionmaker, settings=settings, now=NOW)
        == 1
    )
    async with app.state.db_sessionmaker() as session:
        row = await session.get(PaymentEvidence, evidence.id)
        assert row is not None
        assert row.prereview_claim_token is None and row.prereview_claimed_at is None
        assert (
            await session.scalar(
                select(PaymentEvidenceReview).where(
                    PaymentEvidenceReview.evidence_id == evidence.id
                )
            )
        ).status == "COMPLETED"


async def test_p4_worker_live_lease_makes_admin_retry_conflict(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    require_lease_columns()
    settings = configure(monkeypatch, tmp_path)
    evidence = await downloaded(tmp_path)
    headers = await login_headers(client, "90000000")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def slow_extract(content: bytes, mime: str, config: Settings) -> ReceiptExtraction:
        nonlocal calls
        calls += 1
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return extraction()

    monkeypatch.setattr(payment_review, "extract_receipt", slow_extract)
    # Endpoint uses wall time, so its live lease must use the same clock.
    task = asyncio.create_task(
        process_payment_prereview_once(
            app.state.db_sessionmaker, settings=settings, now=datetime.now(UTC)
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (
            await process_payment_prereview_once(
                app.state.db_sessionmaker, settings=settings, now=datetime.now(UTC)
            )
            == 0
        ), "D6: otro worker no reclama un lease vigente"
        try:
            response = await asyncio.wait_for(
                client.post(f"/admin/payment-evidence/{evidence.id}/prereview", headers=headers),
                2,
            )
        except TimeoutError as error:
            raise AssertionError("D6: la re-revisión esperó el bloqueo del worker") from error
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "La pre-revisión está en curso"
    finally:
        release.set()
        assert await task == 1
    assert calls == 1


@pytest.mark.parametrize("kind", ["permanent", "non_image"])
async def test_skipped_evidence_never_calls_extractor(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    settings = configure(monkeypatch, tmp_path)
    evidence = await seed_evidence(
        download_status="FAILED_PERMANENT" if kind == "permanent" else "DOWNLOADED"
    )
    if kind == "non_image":
        async with app.state.db_sessionmaker.begin() as session:
            row = await session.get(PaymentEvidence, evidence.id)
            assert row is not None
            row.mime_type = "application/pdf"

    async def forbidden_extract(content: bytes, mime: str, config: Settings) -> ReceiptExtraction:
        raise AssertionError("D6: SKIPPED no puede llamar al proveedor")

    monkeypatch.setattr(payment_review, "extract_receipt", forbidden_extract)
    assert (
        await process_payment_prereview_once(app.state.db_sessionmaker, settings=settings, now=NOW)
        == 1
    )
    async with app.state.db_sessionmaker() as session:
        result = await session.scalar(
            select(PaymentEvidenceReview).where(PaymentEvidenceReview.evidence_id == evidence.id)
        )
        assert result is not None and result.status == "SKIPPED" and result.ai_execution_id is None

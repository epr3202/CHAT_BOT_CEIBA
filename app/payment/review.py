"""AI extracts; deterministic checks suggest; only a human can settle a payment."""

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIExecution
from app.ai.prompts.receipt_v1 import RECEIPT_PROMPT_VERSION
from app.ai.receipt import ReceiptExtraction, ReceiptModelError, extract_receipt  # noqa: F401
from app.audit.models import AuditEvent
from app.config.settings import Settings
from app.payment.models import PaymentEvidence, PaymentEvidenceReview
from app.reservation.models import Reservation

logger = structlog.get_logger(__name__)
BOGOTA = ZoneInfo("America/Bogota")
IMAGE_SUFFIXES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
Suggestion = Literal["ACCEPT", "REVIEW", "REJECT"]


class ReceiptCheck(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    code: Literal["AMOUNT", "CURRENCY", "ACCOUNT", "DATE", "REFERENCE", "CONFIDENCE"]
    result: Literal["OK", "WARN", "FAIL", "UNKNOWN"]
    detail: str


def normalize_reference(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def evaluate_receipt(
    extraction: ReceiptExtraction,
    *,
    reservation: Reservation | None,
    settings: Settings,
    previous_references: set[str],
    now: datetime,
) -> tuple[list[ReceiptCheck], Suggestion, int | None]:
    """Pure: all settings, reference history and time are supplied by the caller."""
    if now.utcoffset() is None or (
        reservation is not None and reservation.created_at.utcoffset() is None
    ):
        raise ValueError("Receipt evaluation requires timezone-aware timestamps")
    checks: list[ReceiptCheck] = []

    def add(code: str, result: str, detail: str) -> None:
        checks.append(ReceiptCheck(code=code, result=result, detail=detail))

    amount = extraction.amount_cop if extraction.amount_cop and extraction.amount_cop > 0 else None
    if reservation is None:
        add("AMOUNT", "UNKNOWN", "Sin reserva vinculada para comparar el monto.")
    elif extraction.amount_cop is None:
        add("AMOUNT", "UNKNOWN", "No se pudo leer el monto.")
    elif amount is None:
        add("AMOUNT", "FAIL", "El monto debe ser mayor que cero.")
    else:
        # Match booking's integer ceiling to thousands, using explicit settings only.
        deposit = (
            (reservation.price_cop * settings.booking_deposit_percent + 99999) // 100000
        ) * 1000
        is_balance = reservation.status == "RESERVED"
        target = reservation.price_cop if is_balance else deposit
        missing = max(0, target - reservation.amount_paid_cop)
        sufficient_detail = (
            "Saldo suficiente para completar el pago."
            if is_balance
            else "Monto suficiente para el anticipo."
        )
        add(
            "AMOUNT",
            "OK" if amount >= missing else "WARN",
            sufficient_detail if amount >= missing else "Abono parcial.",
        )
    currency_ok = extraction.currency is None or extraction.currency.strip().upper() == "COP"
    add(
        "CURRENCY",
        "OK" if currency_ok else "FAIL",
        "Moneda compatible con pesos colombianos." if currency_ok else "Moneda distinta de COP.",
    )
    account = re.sub(r"\D", "", settings.booking_account_number)
    last4 = extraction.destination_account_last4
    if last4 is None or len(account) < 4:
        add("ACCOUNT", "UNKNOWN", "No se pudo comparar la cuenta destino.")
    else:
        matches = last4 == account[-4:]
        add(
            "ACCOUNT",
            "OK" if matches else "FAIL",
            "Cuenta destino coincide." if matches else "Cuenta destino no coincide",
        )
    today = now.astimezone(BOGOTA).date()
    transaction_date = extraction.transaction_date
    if transaction_date is None:
        add("DATE", "UNKNOWN", "No se pudo leer la fecha.")
    elif transaction_date > today + timedelta(days=1):
        add("DATE", "FAIL", "Fecha futura superior a un día.")
    elif reservation is None:
        add("DATE", "UNKNOWN", "Sin reserva para comparar la fecha.")
    else:
        earliest = reservation.created_at.astimezone(BOGOTA).date() - timedelta(days=2)
        in_range = transaction_date >= earliest
        add(
            "DATE",
            "OK" if in_range else "WARN",
            "Fecha dentro del intervalo esperado." if in_range else "Fecha anterior al intervalo.",
        )
    reference = normalize_reference(extraction.reference or "")
    if not reference:
        add("REFERENCE", "UNKNOWN", "No se pudo leer la referencia.")
    else:
        duplicate = reference in {normalize_reference(r) for r in previous_references}
        add(
            "REFERENCE",
            "FAIL" if duplicate else "OK",
            "Referencia ya usada" if duplicate else "Referencia sin aceptación previa.",
        )
    confidence = extraction.confidence
    level = (
        "OK"
        if confidence >= settings.payment_review_confidence_ok
        else "WARN"
        if confidence >= settings.payment_review_confidence_min
        else "FAIL"
    )
    add(
        "CONFIDENCE",
        level,
        {
            "OK": "Lectura con confianza alta.",
            "WARN": "Lectura con confianza media.",
            "FAIL": "Lectura con confianza baja.",
        }[level],
    )
    if any(c.code in {"ACCOUNT", "REFERENCE"} and c.result == "FAIL" for c in checks):
        suggestion: Suggestion = "REJECT"
    elif all(
        c.result == "OK" or c.result == "UNKNOWN" and c.code in {"DATE", "REFERENCE"}
        for c in checks
    ):
        suggestion = "ACCEPT"
    else:
        suggestion = "REVIEW"
    return checks, suggestion, amount


async def latest_review(session: AsyncSession, evidence_id: int) -> PaymentEvidenceReview | None:
    return await session.scalar(
        select(PaymentEvidenceReview)
        .where(PaymentEvidenceReview.evidence_id == evidence_id)
        .order_by(PaymentEvidenceReview.attempt_number.desc())
        .limit(1)
    )


def review_payload(review: PaymentEvidenceReview | None) -> dict | None:
    if review is None:
        return None
    extracted = dict(review.extracted) if review.extracted else None
    if extracted and extracted.get("sender_name"):
        extracted["sender_name"] = " ".join(
            f"{part[0].upper()}." for part in extracted["sender_name"].split()
        )
    return dict(
        review_id=str(review.review_id),
        created_at=review.created_at,
        status=review.status,
        extracted=extracted,
        checks=review.checks,
        suggestion=review.suggestion,
        suggested_amount_cop=review.suggested_amount_cop,
        attempt_number=review.attempt_number,
    )


@dataclass(frozen=True)
class PrereviewClaim:
    evidence_id: int
    token: UUID
    conversation_id: int
    storage_path: str | None
    mime_type: str
    download_status: str


class PrereviewConflict(ValueError):
    """The evidence is unavailable for an administrative prereview."""


class PrereviewEvidenceNotFound(LookupError):
    """The requested evidence does not exist."""


async def claim_prereview_evidence(
    session: AsyncSession,
    *,
    settings: Settings,
    now: datetime,
    evidence_id: int | None = None,
) -> PrereviewClaim | None:
    """TX1 commits a lease; only scalar snapshot values leave the transaction."""
    if not settings.payment_review_ai_enabled:
        return None
    if session.in_transaction():
        raise ValueError("Pre-revisión requiere una sesión sin transacción abierta")
    expired_before = now - timedelta(seconds=settings.outbox_sending_timeout_seconds)
    lease_available = or_(
        PaymentEvidence.prereview_claim_token.is_(None),
        PaymentEvidence.prereview_claimed_at.is_(None),
        PaymentEvidence.prereview_claimed_at < expired_before,
    )
    async with session.begin():
        statement = select(PaymentEvidence)
        if evidence_id is None:
            attempts = (
                select(func.count())
                .select_from(PaymentEvidenceReview)
                .where(PaymentEvidenceReview.evidence_id == PaymentEvidence.id)
                .correlate(PaymentEvidence)
                .scalar_subquery()
            )
            terminal = exists().where(
                PaymentEvidenceReview.evidence_id == PaymentEvidence.id,
                PaymentEvidenceReview.status.in_(("COMPLETED", "SKIPPED")),
            )
            statement = statement.where(
                PaymentEvidence.download_status.in_(("DOWNLOADED", "FAILED_PERMANENT")),
                PaymentEvidence.review_status == "PENDING_REVIEW",
                ~terminal,
                attempts < settings.payment_review_max_attempts,
                lease_available,
            )
        else:
            statement = statement.where(PaymentEvidence.id == evidence_id)
        evidence = await session.scalar(
            statement.order_by(PaymentEvidence.created_at, PaymentEvidence.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if evidence is None:
            if evidence_id is None:
                return None
            if await session.get(PaymentEvidence, evidence_id) is None:
                raise PrereviewEvidenceNotFound("El comprobante no existe.")
            raise PrereviewConflict("La pre-revisión está en curso")
        if evidence_id is not None:
            if evidence.review_status != "PENDING_REVIEW":
                raise PrereviewConflict("El comprobante ya fue revisado por un asesor.")
            if evidence.download_status not in {"DOWNLOADED", "FAILED_PERMANENT"}:
                raise PrereviewConflict("El comprobante aún no está disponible.")
            if (
                evidence.prereview_claim_token is not None
                and evidence.prereview_claimed_at is not None
                and evidence.prereview_claimed_at >= expired_before
            ):
                raise PrereviewConflict("La pre-revisión está en curso")
        token = uuid4()
        evidence.prereview_claim_token = token
        evidence.prereview_claimed_at = now
        claim = PrereviewClaim(
            evidence.id,
            token,
            evidence.conversation_id,
            evidence.storage_path,
            evidence.mime_type,
            evidence.download_status,
        )
    return claim


async def prereview_evidence(
    session: AsyncSession,
    claim: PrereviewClaim,
    *,
    settings: Settings,
    now: datetime,
    request_id: str | UUID | None = None,
) -> PaymentEvidenceReview | None:
    """Extract without a DB transaction, then settle the owned lease in TX2."""
    if session.in_transaction():
        raise ValueError("Pre-revisión requiere una sesión sin transacción abierta")
    rid = str(request_id or uuid4())
    telemetry = {"latency_ms": 0, "prompt_tokens": 0, "completion_tokens": 0}
    extracted: ReceiptExtraction | None = None
    provider_called = False
    error_code: str | None = None
    status = "SKIPPED"
    if claim.download_status == "FAILED_PERMANENT":
        error_code = "DOWNLOAD_FAILED_PERMANENT"
    elif claim.mime_type not in IMAGE_SUFFIXES:
        error_code = "UNSUPPORTED_IMAGE_MIME"
    else:
        status = "FAILED"
        try:
            path = Path(claim.storage_path or "").resolve()
            root = Path(settings.payment_evidence_dir).resolve()
            if (
                not path.is_relative_to(root)
                or path.stem != str(claim.evidence_id)
                or path.suffix.lower() != IMAGE_SUFFIXES[claim.mime_type]
                or not path.is_file()
                or path.stat().st_size > settings.inbound_media_max_mb * 1024 * 1024
            ):
                raise OSError("unavailable")
            content = await asyncio.to_thread(path.read_bytes)
            provider_called = True
            extracted = await extract_receipt(content, claim.mime_type, settings)
            telemetry = extracted._telemetry
            status = "COMPLETED"
        except ReceiptModelError as error:
            error_code, telemetry = str(error), error.telemetry
        except OSError:
            error_code = "FILE_UNAVAILABLE"

    async with session.begin():
        evidence = await session.get(
            PaymentEvidence, claim.evidence_id, with_for_update=True, populate_existing=True
        )
        if (
            evidence is None
            or evidence.review_status != "PENDING_REVIEW"
            or evidence.prereview_claim_token != claim.token
        ):
            if evidence is not None and evidence.prereview_claim_token == claim.token:
                evidence.prereview_claim_token = None
                evidence.prereview_claimed_at = None
            session.add(
                AuditEvent(
                    actor="SYSTEM",
                    action="PAYMENT_PREREVIEW_DISCARDED",
                    entity="payment_evidence",
                    old_value={"evidence_id": claim.evidence_id, "claim_token": str(claim.token)},
                    new_value={
                        "evidence_id": claim.evidence_id,
                        "review_status": evidence.review_status if evidence else None,
                    },
                    reason="La evidencia cambió durante la pre-revisión",
                    request_id=rid,
                    created_at=now,
                )
            )
            logger.info(
                "payment_receipt_prereview_discarded",
                evidence_id=claim.evidence_id,
                conversation_id=claim.conversation_id,
                request_id=rid,
            )
            return None
        previous = await latest_review(session, evidence.id)
        review = PaymentEvidenceReview(
            review_id=uuid4(),
            evidence_id=evidence.id,
            created_at=now,
            model=settings.openrouter_model_vision,
            prompt_version=RECEIPT_PROMPT_VERSION,
            status=status,
            extracted=None,
            checks=[],
            suggestion="REVIEW",
            suggested_amount_cop=None,
            error=error_code,
            attempt_number=previous.attempt_number + 1 if previous else 1,
        )
        if extracted is not None:
            reservation = (
                await session.get(Reservation, evidence.reservation_id)
                if evidence.reservation_id
                else None
            )
            # Latest completed extraction for each human-accepted evidence, globally.
            accepted = list(
                await session.scalars(
                    select(PaymentEvidenceReview)
                    .join(PaymentEvidence, PaymentEvidence.id == PaymentEvidenceReview.evidence_id)
                    .where(
                        PaymentEvidence.review_status == "ACCEPTED",
                        PaymentEvidenceReview.status == "COMPLETED",
                    )
                    .distinct(PaymentEvidenceReview.evidence_id)
                    .order_by(
                        PaymentEvidenceReview.evidence_id,
                        PaymentEvidenceReview.attempt_number.desc(),
                    )
                )
            )
            references = {
                r.extracted["reference"]
                for r in accepted
                if r.extracted and r.extracted.get("reference")
            }
            checks, suggestion, amount = evaluate_receipt(
                extracted,
                reservation=reservation,
                settings=settings,
                previous_references=references,
                now=now,
            )
            review.extracted = extracted.model_dump(mode="json")
            review.checks = [c.model_dump() for c in checks]
            review.suggestion = suggestion
            review.suggested_amount_cop = amount
        if provider_called:
            try:
                execution_request_id = UUID(rid)
            except ValueError:
                execution_request_id = uuid5(NAMESPACE_URL, rid)
            execution = AIExecution(
                task="RECEIPT_EXTRACTION",
                model=review.model,
                prompt_version=review.prompt_version,
                latency_ms=telemetry["latency_ms"],
                success=review.status == "COMPLETED",
                error_reason=review.error,
                conversation_id=evidence.conversation_id,
                request_id=execution_request_id,
                input_character_count=0,
                input_payload={
                    "evidence_id": evidence.id,
                    "mime": claim.mime_type,
                    "tokens": {k: v for k, v in telemetry.items() if k.endswith("tokens")},
                },
                raw_output=None,
                parsed_output=None,
                validation_status="VALID"
                if review.status == "COMPLETED"
                else "INVALID_SCHEMA"
                if review.error == "INVALID_SCHEMA"
                else "HTTP_ERROR",
                error=review.error,
            )
            session.add(execution)
            await session.flush()
            review.ai_execution_id = execution.id
        session.add(review)
        session.add(
            AuditEvent(
                actor="SYSTEM",
                action="PAYMENT_EVIDENCE_PREREVIEWED",
                entity="payment_evidence",
                old_value=None,
                new_value={
                    "evidence_id": evidence.id,
                    "review_id": str(review.review_id),
                    "suggestion": review.suggestion,
                    "status": review.status,
                    "checks": [{"code": c["code"], "result": c["result"]} for c in review.checks],
                    "attempt_number": review.attempt_number,
                },
                reason="Pre-revisión asistida; requiere confirmación humana",
                request_id=rid,
                created_at=now,
            )
        )
        evidence.prereview_claim_token = None
        evidence.prereview_claimed_at = None
        logger.info(
            "payment_receipt_prereview",
            evidence_id=evidence.id,
            conversation_id=evidence.conversation_id,
            request_id=rid,
            model=review.model,
            latency_ms=telemetry["latency_ms"],
            tokens=telemetry["prompt_tokens"] + telemetry["completion_tokens"],
            result=review.status,
        )
        await session.flush()
        # The endpoint renders after TX2, including expire_on_commit=True sessions.
        session.expunge(review)
    return review

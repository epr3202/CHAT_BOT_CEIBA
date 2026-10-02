"""B1b-3: failed predecessor text retires dependent PDFs without provider calls."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.attributes import flag_modified

from app.channel.models import Outbox
from app.channel.worker import claim_due_outbox_batch, process_outbox_once
from tests.booking_conversation.helpers import send_catalog_information
from tests.test_fix2a_catalog_capture_adversarial import seed_catalog
from tests.visit_booking_guard.helpers import Harness


class ForbiddenSender:
    async def send_text(self, *args: object) -> str:
        raise AssertionError("Terminal text must not be sent again")

    async def send_document(self, *args: object) -> str:
        raise AssertionError("PDF cannot be sent after terminal predecessor failure")

    async def upload_media(self, *args: object) -> str:
        raise AssertionError("PDF cannot be uploaded after terminal predecessor failure")


async def ordered_outbox(harness: Harness, tmp_path: Path) -> tuple[Outbox, Outbox]:
    await harness.seed()
    await seed_catalog(harness.db, tmp_path, send_mode="PROACTIVE")
    await send_catalog_information(harness)
    rows = sorted(await harness.rows(Outbox), key=lambda row: row.id)
    assert [row.message_kind for row in rows] == ["TEXT", "DOCUMENT"]
    return rows[0], rows[1]


@pytest.mark.parametrize(
    "text_status,text_reason,pdf_status,pdf_reason",
    [
        ("SUPPRESSED", "AUTOMATION_PAUSED", "SUPPRESSED", "AUTOMATION_PAUSED"),
        ("SUPPRESSED", None, "SUPPRESSED", "PRECEDING_TEXT_SUPPRESSED"),
        ("FAILED", None, "SUPPRESSED", "PRECEDING_TEXT_FAILED"),
        ("REVIEW", "EXTERNAL_RESULT_UNCERTAIN", "REVIEW", "PRECEDING_TEXT_REVIEW"),
        ("DISCARDED", None, "REVIEW", "PRECEDING_TEXT_REVIEW"),
    ],
)
async def test_terminal_text_retires_pdf_without_http(
    harness: Harness,
    tmp_path: Path,
    text_status: str,
    text_reason: str | None,
    pdf_status: str,
    pdf_reason: str,
) -> None:
    preceding, dependent = await ordered_outbox(harness, tmp_path)
    async with harness.db.begin() as session:
        row = await session.get(Outbox, preceding.id)
        row.status, row.delivery_reason = text_status, text_reason
    assert await process_outbox_once(harness.db, ForbiddenSender()) == 0
    saved = next(row for row in await harness.rows(Outbox) if row.id == dependent.id)
    assert saved.status == pdf_status, "Dependent PDF remains pending after terminal text"
    assert saved.delivery_reason == pdf_reason
    assert saved.delivery_decided_at is not None
    assert saved.claim_token is None and saved.claimed_at is None
    assert saved.next_attempt_at is None
    assert saved.attempts == 0
    assert await process_outbox_once(harness.db, ForbiddenSender()) == 0


@pytest.mark.parametrize(
    "text_status,retrying", [("PENDING", False), ("SENDING", False), ("PENDING", True)]
)
async def test_unfinished_text_continues_to_block_pdf(
    harness: Harness,
    tmp_path: Path,
    text_status: str,
    retrying: bool,
) -> None:
    preceding, dependent = await ordered_outbox(harness, tmp_path)
    now = datetime.now(UTC)
    async with harness.db.begin() as session:
        row = await session.get(Outbox, preceding.id)
        row.status = text_status
        if retrying:
            row.next_attempt_at = now + timedelta(hours=1)
    claims = await claim_due_outbox_batch(harness.db, now, 10)
    assert dependent.id not in [claim.id for claim in claims]
    assert [claim.id for claim in claims] == (
        [preceding.id] if text_status == "PENDING" and not retrying else []
    )
    saved = next(row for row in await harness.rows(Outbox) if row.id == dependent.id)
    assert saved.status == "PENDING" and saved.delivery_reason is None


async def test_terminal_dependency_preserves_prior_external_uncertainty(
    harness: Harness,
    tmp_path: Path,
) -> None:
    preceding, dependent = await ordered_outbox(harness, tmp_path)
    async with harness.db.begin() as session:
        text = await session.get(Outbox, preceding.id)
        text.status = "FAILED"
        pdf = await session.get(Outbox, dependent.id)
        pdf.send_admission = {"phase": "UNKNOWN", "id": str(uuid4())}
    assert await process_outbox_once(harness.db, ForbiddenSender()) == 0
    saved = next(row for row in await harness.rows(Outbox) if row.id == dependent.id)
    assert saved.status == "REVIEW", "An uncertain prior PDF call must not become unsent"
    assert saved.delivery_reason == "EXTERNAL_RESULT_UNCERTAIN_PRECEDING_TEXT_FAILED"
    assert saved.send_admission["phase"] == "UNKNOWN"


@pytest.mark.parametrize("dependency", ["invalid", True, 0, None, 99999999])
async def test_invalid_dependency_does_not_poison_claim_batch_or_send_pdf(
    harness: Harness,
    tmp_path: Path,
    dependency: object,
) -> None:
    preceding, dependent = await ordered_outbox(harness, tmp_path)
    async with harness.db.begin() as session:
        text = await session.get(Outbox, preceding.id)
        text.status = "SENT"
        pdf = await session.get(Outbox, dependent.id)
        pdf.delivery_context = {**pdf.delivery_context, "after_outbox_id": dependency}
        # JSON equality considers True == 1; force persistence of this malformed test value.
        flag_modified(pdf, "delivery_context")
    error = None
    try:
        processed = await process_outbox_once(harness.db, ForbiddenSender())
    except DBAPIError as exception:
        error = exception
    assert error is None, "Malformed JSON dependency poisoned the whole outbox batch"
    assert processed == 0
    saved = next(row for row in await harness.rows(Outbox) if row.id == dependent.id)
    assert saved.status == "REVIEW", "Invalid dependency must retire without blocking others"
    assert saved.delivery_reason == "PRECEDING_TEXT_UNPROVEN"


async def test_terminal_dependency_finalization_is_safe_for_concurrent_claims(
    harness: Harness,
    tmp_path: Path,
) -> None:
    preceding, dependent = await ordered_outbox(harness, tmp_path)
    async with harness.db.begin() as session:
        text = await session.get(Outbox, preceding.id)
        text.status = "FAILED"
    results = await asyncio.gather(
        *(claim_due_outbox_batch(harness.db, datetime.now(UTC), 10) for _ in range(2))
    )
    assert results == [[], []]
    saved = next(row for row in await harness.rows(Outbox) if row.id == dependent.id)
    assert saved.status == "SUPPRESSED" and saved.delivery_reason == "PRECEDING_TEXT_FAILED"


async def test_terminal_dependency_cancels_pdf_backoff_immediately(
    harness: Harness,
    tmp_path: Path,
) -> None:
    preceding, dependent = await ordered_outbox(harness, tmp_path)
    async with harness.db.begin() as session:
        text = await session.get(Outbox, preceding.id)
        text.status = "FAILED"
        pdf = await session.get(Outbox, dependent.id)
        pdf.next_attempt_at = datetime.now(UTC) + timedelta(days=1)
    assert await process_outbox_once(harness.db, ForbiddenSender()) == 0
    saved = next(row for row in await harness.rows(Outbox) if row.id == dependent.id)
    assert saved.status == "SUPPRESSED" and saved.next_attempt_at is None


async def test_legacy_document_without_dependency_keeps_existing_claim_behavior(
    harness: Harness,
    tmp_path: Path,
) -> None:
    preceding, dependent = await ordered_outbox(harness, tmp_path)
    async with harness.db.begin() as session:
        text = await session.get(Outbox, preceding.id)
        text.status = "SENT"
        pdf = await session.get(Outbox, dependent.id)
        pdf.delivery_context = {
            key: value for key, value in pdf.delivery_context.items() if key != "after_outbox_id"
        }
    claims = await claim_due_outbox_batch(harness.db, datetime.now(UTC), 10)
    assert [claim.id for claim in claims] == [dependent.id]

"""Evaluate local anonymized receipts; no images or extracted PII in the report."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import app.models_registry  # noqa: F401
from app.ai.receipt import ReceiptModelError
from app.config.settings import Settings, get_settings
from app.payment.review import ReceiptExtraction, evaluate_receipt, extract_receipt
from app.reservation.models import Reservation

FIELDS = ("amount_cop", "transaction_date", "reference", "destination_account_last4", "bank")
MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


async def evaluate_dataset(
    folder: Path,
    *,
    settings: Settings,
    reservation: Reservation | None,
    previous_references: set[str],
    now: datetime,
) -> dict[str, Any]:
    correct: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    matrix = {
        expected: dict.fromkeys(("ACCEPT", "REVIEW", "REJECT", "FAILED"), 0)
        for expected in ("ACCEPT", "REVIEW", "REJECT")
    }
    cases = 0
    failed = 0
    for line in folder.joinpath("labels.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        label = json.loads(line)
        filename = label["evidence"]
        path = folder.joinpath(filename).resolve()
        if not path.is_relative_to(folder.resolve()) or path.suffix.lower() not in MIMES:
            raise ValueError("Each evidence must be a local image inside the dataset folder")
        expected_fields = {key: label.get(key) for key in ReceiptExtraction.model_fields}
        expected_fields.update(
            currency=label.get("currency", "COP"), confidence=label.get("confidence", 1.0)
        )
        expected = ReceiptExtraction.model_validate_json(json.dumps(expected_fields))
        _, expected_suggestion, _ = evaluate_receipt(
            expected,
            reservation=reservation,
            settings=settings,
            previous_references=previous_references,
            now=now,
        )
        cases += 1
        try:
            actual = await extract_receipt(path.read_bytes(), MIMES[path.suffix.lower()], settings)
        except ReceiptModelError:
            failed += 1
            matrix[expected_suggestion]["FAILED"] += 1
            for field in FIELDS:
                if field in label:
                    totals[field] += 1
            continue
        extracted = actual.model_dump(mode="json")
        for field in FIELDS:
            if field in label:
                totals[field] += 1
                correct[field] += extracted[field] == label[field]
        _, suggestion, _ = evaluate_receipt(
            actual,
            reservation=reservation,
            settings=settings,
            previous_references=previous_references,
            now=now,
        )
        matrix[expected_suggestion][suggestion] += 1
    return {
        "model": settings.openrouter_model_vision,
        "prompt_version": "receipt_v1",
        "cases": cases,
        "failed": failed,
        "accuracy": {
            field: {
                "correct": correct[field],
                "total": totals[field],
                "accuracy": correct[field] / totals[field] if totals[field] else None,
            }
            for field in FIELDS
        },
        "suggestions_matrix": matrix,
        "matrix_basis": "deterministic checks of labels versus extracted fields",
        "reservation_supplied": reservation is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Local folder with images and labels.jsonl")
    parser.add_argument(
        "--reservation-json",
        type=Path,
        help="price_cop, amount_paid_cop, created_at (ISO with timezone)",
    )
    parser.add_argument(
        "--previous-references", type=Path, help="JSON array of accepted references"
    )
    parser.add_argument("--now", help="ISO timestamp with timezone for reproducible checks")
    args = parser.parse_args()
    reservation = None
    if args.reservation_json:
        data = json.loads(args.reservation_json.read_text())
        reservation = Reservation(
            price_cop=data["price_cop"],
            amount_paid_cop=data["amount_paid_cop"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )
        if reservation.created_at.utcoffset() is None:
            parser.error("reservation created_at requires a timezone")
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    if now.utcoffset() is None:
        parser.error("--now requires a timezone")
    previous = (
        set(json.loads(args.previous_references.read_text())) if args.previous_references else set()
    )
    result = asyncio.run(
        evaluate_dataset(
            args.folder,
            settings=get_settings(),
            reservation=reservation,
            previous_references=previous,
            now=now,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

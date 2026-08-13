from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

APPROVED_RESPONSES_PATH = (
    Path(__file__).resolve().parents[1] / "docs/conversation/approved-responses.md"
)

NON_RENDERABLE_CODES = {
    "RESP-GEN-001",
    "RESP-GEN-002",
    "RESP-GEN-003",
    "RESP-GEN-004",
    "RESP-GEN-005",
    "RESP-GEN-006",
    "RESP-GEN-007",
    "RESP-GEN-008",
    "RESP-PRICE-006",
    "RESP-COMPLAINT-006",
    "RESP-AI-ERROR-004",
    "RESP-DELIVERY-ERROR-001",
    "RESP-FILE-002",
    "RESP-FOLLOWUP-005",
    "RESP-CATALOG-001",
    "RESP-CATALOG-002",
    "RESP-CATALOG-003",
}

CONDITIONAL_DRAFT_CODES = {
    "RESP-PRICE-005",
    "RESP-SERVICES-004",
    "RESP-SERVICES-005",
    "RESP-PAYMENT-004",
    "RESP-PAYMENT-005",
    "RESP-RESERVATION-006",
}


@dataclass(frozen=True)
class KnowledgeSeedEntry:
    code: str
    category: str
    question_summary: str
    answer_template: str
    allowed_variables: list[str]
    version: int = 1
    status: str = "APPROVED"


def iter_seed_entries() -> list[KnowledgeSeedEntry]:
    return extract_seed_entries(APPROVED_RESPONSES_PATH.read_text(encoding="utf-8"))


def extract_seed_entries(content: str) -> list[KnowledgeSeedEntry]:
    entries: list[KnowledgeSeedEntry] = []
    category = ""
    matches = list(re.finditer(r"^## (RESP-[A-Z0-9-]+) — (.+)$", content, flags=re.MULTILINE))

    for index, match in enumerate(matches):
        category = find_category(content[: match.start()]) or category
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        block = content[match.end() : block_end]
        code = match.group(1)
        summary = match.group(2).strip()
        template = extract_first_customer_text(block)
        status = status_for_entry(code, template)
        if template is None:
            template = f"[REVISAR] Entrada sin texto aprobado enviable: {summary}."
        elif status == "DRAFT":
            template = f"[REVISAR] {template}"

        entries.append(
            KnowledgeSeedEntry(
                code=code,
                category=category,
                question_summary=summary,
                answer_template=template,
                allowed_variables=sorted(set(re.findall(r"{([a-zA-Z_][a-zA-Z0-9_]*)}", template))),
                status=status,
            )
        )

    return entries


def find_category(previous_content: str) -> str | None:
    headings = re.findall(r"^# \d+\. (.+)$", previous_content, flags=re.MULTILINE)
    if not headings:
        return None
    return headings[-1].strip()


def extract_first_customer_text(block: str) -> str | None:
    quoted_lines = [
        line.removeprefix("> ").strip() for line in block.splitlines() if line.startswith("> ")
    ]
    if not quoted_lines:
        return None
    return "\n".join(quoted_lines).strip()


def status_for_entry(code: str, template: str | None) -> str:
    if template is None or code in NON_RENDERABLE_CODES or code in CONDITIONAL_DRAFT_CODES:
        return "DRAFT"
    return "APPROVED"

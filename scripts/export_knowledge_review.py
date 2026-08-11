from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry

OUTPUT_PATH = Path("docs/review/knowledge-review.md")
GAP_CONFIRMATION_TEMPLATE = (
    "GAP: falta plantilla para confirmar intención tentativa (detectado en F4)"
)


class ReviewEntry(Protocol):
    code: str
    category: str
    question_summary: str
    answer_template: str
    allowed_variables: list[str]
    version: int
    status: str


async def fetch_latest_entries(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[KnowledgeEntry]:
    async with sessionmaker() as session:
        entries = (
            await session.scalars(
                select(KnowledgeEntry).order_by(
                    KnowledgeEntry.code.asc(),
                    KnowledgeEntry.version.desc(),
                )
            )
        ).all()

    latest_by_code: dict[str, KnowledgeEntry] = {}
    for entry in entries:
        latest_by_code.setdefault(entry.code, entry)
    return sorted(latest_by_code.values(), key=lambda entry: (entry.category, entry.code))


def render_review_markdown(entries: list[ReviewEntry]) -> str:
    draft_entries = sorted(
        (entry for entry in entries if entry.status == "DRAFT"),
        key=lambda entry: (entry.category, entry.code),
    )
    decided_entries = sorted(
        (entry for entry in entries if entry.status != "DRAFT"),
        key=lambda entry: (entry.category, entry.code),
    )

    lines = [
        "# Revisión de base de conocimiento",
        "",
        "Este documento lista la versión más reciente de cada respuesta aprobada o pendiente.",
        "",
        "## REQUIEREN DECISIÓN",
        "",
    ]

    if draft_entries:
        for entry in draft_entries:
            lines.extend(render_entry(entry, include_category=True))
    else:
        lines.append("No hay entradas DRAFT en la base de conocimiento.")
        lines.append("")

    lines.extend(
        [
            "### GAP",
            "",
            f"- **Entrada:** {GAP_CONFIRMATION_TEMPLATE}",
            "- **Status:** DRAFT",
            "- **Decisión requerida:** crear una plantilla aprobada para pedir confirmación "
            "cuando la clasificación queda en banda tentativa.",
            "",
        ]
    )

    current_category: str | None = None
    for entry in decided_entries:
        if entry.category != current_category:
            current_category = entry.category
            lines.extend([f"## {current_category}", ""])
        lines.extend(render_entry(entry, include_category=False))

    return "\n".join(lines).rstrip() + "\n"


def render_entry(entry: ReviewEntry, *, include_category: bool) -> list[str]:
    variables = ", ".join(entry.allowed_variables) if entry.allowed_variables else "Ninguna"
    lines = [
        f"### {entry.code}",
        "",
        f"- **Status:** {entry.status}",
    ]
    if include_category:
        lines.append(f"- **Categoría:** {entry.category}")
    lines.extend(
        [
            f"- **Pregunta/resumen:** {entry.question_summary}",
            f"- **Variables requeridas:** {variables}",
            "- **Respuesta aprobada:**",
            "",
            entry.answer_template,
            "",
        ]
    )
    return lines


async def export_knowledge_review(output_path: Path = OUTPUT_PATH) -> Path:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    try:
        sessionmaker = create_sessionmaker(engine)
        entries = await fetch_latest_entries(sessionmaker)
    finally:
        await engine.dispose()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_review_markdown(entries), encoding="utf-8")
    return output_path


async def main() -> None:
    output_path = await export_knowledge_review()
    print(f"knowledge review exported: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())

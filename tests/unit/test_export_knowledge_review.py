from __future__ import annotations

from dataclasses import dataclass

from scripts.export_knowledge_review import (
    GAP_CONFIRMATION_TEMPLATE,
    render_review_markdown,
)


@dataclass
class Entry:
    code: str
    category: str
    question_summary: str
    answer_template: str
    allowed_variables: list[str]
    version: int
    status: str


def test_render_review_places_drafts_first_with_gap() -> None:
    markdown = render_review_markdown(
        [
            Entry(
                code="RESP-APP-001",
                category="Ubicación",
                question_summary="Dónde están ubicados",
                answer_template="Estamos en {location}.",
                allowed_variables=["location"],
                version=1,
                status="APPROVED",
            ),
            Entry(
                code="RESP-DRAFT-001",
                category="Pagos",
                question_summary="Texto pendiente",
                answer_template="[REVISAR] Texto pendiente.",
                allowed_variables=[],
                version=1,
                status="DRAFT",
            ),
        ]
    )

    draft_position = markdown.index("### RESP-DRAFT-001")
    approved_position = markdown.index("### RESP-APP-001")
    gap_position = markdown.index(GAP_CONFIRMATION_TEMPLATE)

    assert "## REQUIEREN DECISIÓN" in markdown
    assert draft_position < gap_position < approved_position
    assert "- **Variables requeridas:** location" in markdown
    assert "- **Variables requeridas:** Ninguna" in markdown
    assert "Estamos en {location}." in markdown

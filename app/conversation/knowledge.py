from __future__ import annotations

import string
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.conversation.models import KnowledgeEntry
from app.conversation.presentation import VariablePresentationError, present_variables


class KnowledgeRenderErrorReason(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    NOT_APPROVED = "NOT_APPROVED"
    MISSING_VARIABLE = "MISSING_VARIABLE"
    UNKNOWN_VARIABLE = "UNKNOWN_VARIABLE"
    PRESENTATION_ERROR = "PRESENTATION_ERROR"


class KnowledgeRenderError(Exception):
    def __init__(
        self,
        reason: KnowledgeRenderErrorReason,
        code: str,
        variable: str | None = None,
    ) -> None:
        self.reason = reason
        self.code = code
        self.variable = variable
        super().__init__(reason.value)


async def get_approved_response(
    sessionmaker: async_sessionmaker[AsyncSession],
    code: str,
) -> KnowledgeEntry | None:
    async with sessionmaker() as session:
        return await session.scalar(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.code == code, KnowledgeEntry.status == "APPROVED")
            .order_by(KnowledgeEntry.version.desc())
            .limit(1)
        )


async def render_response(
    sessionmaker: async_sessionmaker[AsyncSession],
    code: str,
    variables: dict[str, Any],
) -> str:
    entry = await get_latest_response(sessionmaker, code)
    if entry is None:
        raise KnowledgeRenderError(KnowledgeRenderErrorReason.NOT_FOUND, code)
    if entry.status != "APPROVED":
        raise KnowledgeRenderError(KnowledgeRenderErrorReason.NOT_APPROVED, code)

    required_variables = variables_in_template(entry.answer_template)
    allowed_variables = set(entry.allowed_variables)

    for variable in required_variables:
        value = variables.get(variable)
        if value is None or str(value).strip() == "":
            raise KnowledgeRenderError(
                KnowledgeRenderErrorReason.MISSING_VARIABLE,
                code,
                variable,
            )

    for variable in variables:
        if variable not in allowed_variables:
            raise KnowledgeRenderError(
                KnowledgeRenderErrorReason.UNKNOWN_VARIABLE,
                code,
                variable,
            )

    try:
        presented_variables = present_variables(variables)
    except VariablePresentationError as error:
        raise KnowledgeRenderError(
            KnowledgeRenderErrorReason.PRESENTATION_ERROR,
            code,
            error.variable,
        ) from error

    return entry.answer_template.format(**presented_variables)


async def get_latest_response(
    sessionmaker: async_sessionmaker[AsyncSession],
    code: str,
) -> KnowledgeEntry | None:
    async with sessionmaker() as session:
        return await session.scalar(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.code == code)
            .order_by(KnowledgeEntry.version.desc())
            .limit(1)
        )


def variables_in_template(template: str) -> set[str]:
    formatter = string.Formatter()
    return {
        field_name
        for _, field_name, _, _ in formatter.parse(template)
        if field_name is not None and field_name != ""
    }

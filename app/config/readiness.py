import asyncio

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.conversation.knowledge import get_latest_response, variables_in_template


async def check_database(engine: AsyncEngine) -> None:
    async with asyncio.timeout(10):
        async with engine.connect() as connection:
            revisions = (
                (await connection.execute(text("SELECT version_num FROM alembic_version")))
                .scalars()
                .all()
            )
        if len(revisions) != 1 or ScriptDirectory.from_config(
            Config("alembic.ini")
        ).get_heads() != [revisions[0]]:
            raise ValueError("Database revision does not match the migration head")


async def validate_payment_settings(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    if settings.environment != "production":
        return
    code = "RESP-BOOKING-PAYMENT-001"
    entry = await get_latest_response(sessionmaker, code)
    if (
        entry is not None
        and entry.status == "APPROVED"
        and "breb_key" in variables_in_template(entry.answer_template)
        and not settings.bank_breb_key.strip()
    ):
        raise ValueError(f"BANK_BREB_KEY is required by the approved {code} template")

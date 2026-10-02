import asyncio

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


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

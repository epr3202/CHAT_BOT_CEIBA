from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import app.models_registry  # noqa: F401
from app.admin.routes import router as admin_router
from app.channel.webhook import router as whatsapp_webhook_router
from app.config.database import create_engine, create_sessionmaker
from app.config.logging import configure_logging
from app.config.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.environment, settings.log_level)
    app.state.settings = settings
    app.state.db_engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    app.state.db_sessionmaker = create_sessionmaker(app.state.db_engine)
    yield
    await app.state.db_engine.dispose()


app = FastAPI(title="La Ceiba Club House API", lifespan=lifespan)
app.include_router(admin_router)
app.include_router(whatsapp_webhook_router)
logger = structlog.get_logger(__name__)


@app.get("/health")
async def health() -> dict[str, Any]:
    settings: Settings = app.state.settings
    engine: AsyncEngine = app.state.db_engine

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    logger.info("healthcheck_ok", environment=settings.environment)
    return {"status": "ok", "database": "ok", "environment": settings.environment}

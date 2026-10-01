#!/usr/bin/env python3
"""Expire unpaid fixed-price requests; run with the deployment environment."""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings
from app.reservation.settlement import expire_pending_reservations


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        count = await expire_pending_reservations(create_sessionmaker(engine), datetime.now(UTC))
        print(f"Solicitudes vencidas: {count}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

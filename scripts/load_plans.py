from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings
from app.plan.models import Plan

# code, name, event_type, price_cop, duration_minutes, exclusive, weekend_only
# TODO: confirmar con producto la duración de Cinema y Amor; B1a usa 180 minutos.
PLAN_SEED: tuple[tuple[str, str, str, int, int, bool, bool], ...] = (
    ("RITUAL_CORAZON", "Ritual del Corazón", "ROMANTIC_DINNER", 250000, 180, False, False),
    ("ROMANCE_COPAS", "Romance entre Copas", "ROMANTIC_DINNER", 400000, 180, False, False),
    ("MANANAS_ENCANTO", "Mañanas de Encanto", "ROMANTIC_DINNER", 450000, 180, False, True),
    ("CINEMA_AMOR", "Cinema y Amor", "ROMANTIC_DINNER", 700000, 180, False, False),
    ("REFUGIO_DOS", "Refugio para Dos", "ROMANTIC_DINNER", 1000000, 180, False, False),
    ("PETALOS_ESTRELLAS", "Entre Pétalos y Estrellas", "PROPOSAL", 450000, 180, False, False),
    ("CONFESION_LUNA", "Confesión bajo la Luna", "PROPOSAL", 900000, 180, False, False),
    ("NOCHE_INOLVIDABLE", "Noche Inolvidable", "PROPOSAL", 2500000, 180, True, False),
)


async def load_plans(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """Insert missing codes; preserve every existing value and timestamp.

    ON CONFLICT also makes concurrent deploys safe without overwriting admin edits.
    """
    inserted = 0
    async with sessionmaker.begin() as session:
        for order, (code, name, event_type, price, duration, exclusive, weekend) in enumerate(
            PLAN_SEED, start=1
        ):
            result = await session.scalar(
                insert(Plan)
                .values(
                    code=code,
                    name=name,
                    event_type=event_type,
                    price_cop=price,
                    duration_minutes=duration,
                    exclusive=exclusive,
                    weekend_only=weekend,
                    active=True,
                    sort_order=order,
                )
                .on_conflict_do_nothing(index_elements=[Plan.code])
                .returning(Plan.plan_id)
            )
            inserted += int(result is not None)
    return inserted


async def main() -> None:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    try:
        inserted = await load_plans(create_sessionmaker(engine))
        print(f"plans inserted: {inserted}; plans in seed: {len(PLAN_SEED)}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

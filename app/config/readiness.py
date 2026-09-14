"""Read-only operational checks; no provider access or schema mutations."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config.settings import Settings, get_settings

HEAD = "20260910_0027"
HEARTBEAT_DIR = Path("/tmp/ceiba-worker")


def validate_revision(revisions: list[str], *, allow_ancestor: bool = False) -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    if script.get_heads() != [HEAD]:
        raise ValueError("Unexpected source migration head")
    allowed = {r.revision for r in script.walk_revisions()} if allow_ancestor else {HEAD}
    if len(revisions) != 1 or revisions[0] not in allowed:
        raise ValueError("Unknown or incompatible database revision")


async def check_database(engine: AsyncEngine, *, allow_ancestor: bool = False) -> None:
    async with asyncio.timeout(10):
        async with engine.connect() as connection:
            revisions = list(
                (
                    await connection.execute(text("SELECT version_num FROM alembic_version"))
                ).scalars()
            )
    validate_revision(revisions, allow_ancestor=allow_ancestor)


def validate_storage(settings: Settings, *, worker: bool = False) -> None:
    if settings.environment not in {"staging", "production"}:
        return
    for field in ("catalog_storage_dir", "payment_evidence_dir"):
        path = Path(getattr(settings, field))
        if field not in settings.model_fields_set or not path.is_absolute() or not path.is_dir():
            raise ValueError("Explicit existing storage directory required: " + field)
        mode = os.R_OK | os.X_OK
        if not worker and field == "catalog_storage_dir":
            mode |= os.W_OK
        if not os.access(path, mode):
            raise ValueError("Storage permissions invalid: " + field)


def heartbeat(loop: str, directory: Path = HEARTBEAT_DIR) -> None:
    directory.mkdir(exist_ok=True)
    path = directory / loop
    temporary = directory / (loop + ".tmp")
    temporary.write_text(json.dumps({"pid": os.getpid(), "polled": time.monotonic()}))
    temporary.replace(path)


def check_worker(directory: Path = HEARTBEAT_DIR, *, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    for loop in ("inbox", "outbox"):
        try:
            state = json.loads((directory / loop).read_text())
            os.kill(state["pid"], 0)
            if not 0 <= now - state["polled"] < 300:
                raise ValueError("Worker polling stale")
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Worker absent or heartbeat invalid") from exc


async def preflight(*, allow_ancestor: bool = False) -> None:
    from app.config.database import create_engine

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        await check_database(engine, allow_ancestor=allow_ancestor)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        command = sys.argv[1]
        if command == "worker":
            check_worker()
        elif command in {"database", "migration-preflight"}:
            asyncio.run(preflight(allow_ancestor=command == "migration-preflight"))
        elif command == "storage":
            validate_storage(get_settings(), worker=os.environ.get("RUNTIME_ROLE") == "worker")
        else:
            raise ValueError("Unknown readiness command")
    except Exception:
        # Settings exceptions can contain input values: never serialize them in deployed logs.
        raise SystemExit(
            "Operational preflight failed; inspect configuration by NAME only"
        ) from None


if __name__ == "__main__":
    main()

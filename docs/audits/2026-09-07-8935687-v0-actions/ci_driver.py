"""Runs only inside the uniquely labelled container created by run_isolated.py."""
from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import traceback
from collections import Counter

NONCE = os.environ.get("AUDIT_NONCE", "")
if not re.fullmatch(r"[0-9a-f]{32}", NONCE) or not os.environ.get("AUDIT_DB_CONTAINER"):
    raise SystemExit("Missing isolated-container provenance")
if sys.version_info[:2] != (3, 12) or Path("/source/.env").exists():
    raise SystemExit("Wrong Python or unsafe source copy")
os.chdir("/source")
sys.path.insert(0, "/source")
OUT = Path("/audit-output")
OUT.mkdir(exist_ok=True)
ROLE = "audit_" + NONCE
PASSWORD = "synthetic_" + NONCE
DB_IP = socket.gethostbyname("audit-postgres")
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
original_dns = socket.getaddrinfo


def allow(address):
    if isinstance(address, tuple) and address[0] not in {DB_IP, "audit-postgres", "127.0.0.1", "::1"}:
        raise RuntimeError("AUDIT_EXTERNAL_NETWORK_BLOCKED")


def connect(sock, address):
    allow(address)
    return original_connect(sock, address)


def connect_ex(sock, address):
    allow(address)
    return original_connect_ex(sock, address)


def dns(host, *args, **kwargs):
    if host not in {None, DB_IP, "audit-postgres", "127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("AUDIT_EXTERNAL_DNS_BLOCKED")
    return original_dns(host, *args, **kwargs)


socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.getaddrinfo = dns


def url(name):
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise RuntimeError("Unsafe database identifier")
    return f"postgresql+asyncpg://{ROLE}:{PASSWORD}@{DB_IP}:5432/{name}"


def environment(name):
    os.environ.update(DATABASE_URL=url(name), TEST_DATABASE_URL=url(name), ENVIRONMENT="testing",
        META_APP_SECRET="synthetic-phase2", META_ACCESS_TOKEN="synthetic-phase2",
        OPENROUTER_API_KEY="synthetic-phase2", CALENDAR_ADAPTER="fake",
        CATALOG_STORAGE_DIR="/tmp/audit-catalogs", PAYMENT_EVIDENCE_DIR="/tmp/audit-evidence",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", OPENROUTER_MAX_RETRIES="0")


import asyncpg
original_pg_connect = asyncpg.connect


async def guarded_pg_connect(*args, **kwargs):
    connection = await original_pg_connect(*args, **kwargs)
    row = await connection.fetchrow("SELECT current_user AS role, current_database() AS db, "
        "current_setting('server_version_num')::int AS version, "
        "pg_get_userbyid(datdba) AS owner FROM pg_database WHERE datname=current_database()")
    if row["role"] != ROLE or row["owner"] != ROLE or not 160000 <= row["version"] < 170000:
        await connection.close()
        raise RuntimeError("Database instance/role/version ownership mismatch")
    with (OUT / "verified_connections.jsonl").open("a", encoding="utf8") as f:
        f.write(json.dumps({**dict(row), "container": os.environ["AUDIT_DB_CONTAINER"], "nonce": NONCE}) + "\n")
    return connection


asyncpg.connect = guarded_pg_connect


async def create_database(name):
    url(name)
    connection = await asyncpg.connect(host=DB_IP, user=ROLE, password=PASSWORD, database="postgres")
    try:
        if await connection.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
            raise RuntimeError("Database already exists; refusing reuse")
        await connection.execute('CREATE DATABASE "' + name + '" OWNER "' + ROLE + '"')
    finally:
        await connection.close()


def migrate(name):
    command = [sys.executable, "-m", "alembic", "upgrade", "head"]
    migration_env = dict(os.environ, DATABASE_URL=url(name), TEST_DATABASE_URL=url(name))
    result = subprocess.run(command, env=migration_env, capture_output=True, text=True, timeout=120)
    with (OUT / "migration_commands.jsonl").open("a") as handle:
        handle.write(json.dumps(dict(command=command, database=name, exit_code=result.returncode)) + "\n")
    (OUT / (name + "_migration.log")).write_text(result.stdout + result.stderr, encoding="utf8")
    if result.returncode:
        raise RuntimeError("Existing migrations failed: " + name)


async def schema(name, metadata=False):
    import app.models_registry  # noqa: F401
    from app.config.database import Base
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import inspect
    engine = create_async_engine(url(name))
    def reflect(connection):
        inspector = inspect(connection)
        result = {}
        for table in sorted(inspector.get_table_names()):
            if table == "alembic_version":
                continue
            result[table] = {"columns": [{**{k: str(v) if k == "type" else v for k, v in c.items()}, "timezone": getattr(c["type"], "timezone", None)}
                                          for c in inspector.get_columns(table)],
                "checks": inspector.get_check_constraints(table), "indexes": inspector.get_indexes(table),
                "unique": inspector.get_unique_constraints(table), "foreign_keys": inspector.get_foreign_keys(table),
                "primary_key": inspector.get_pk_constraint(table)}
        return result
    try:
        async with engine.begin() as connection:
            if metadata:
                await connection.run_sync(Base.metadata.create_all)
            return await connection.run_sync(reflect)
    finally:
        await engine.dispose()


class ResultPlugin:
    def __init__(self):
        self.rows = []
        self.collection = []

    def pytest_collectreport(self, report):
        self.collection.append(dict(nodeid=report.nodeid, outcome=report.outcome,
                                    detail=str(report.longrepr) if report.failed else None))

    def pytest_runtest_logreport(self, report):
        category = report.outcome
        if hasattr(report, "wasxfail"):
            category = "XPASS" if report.passed else "XFAIL"
        elif report.failed and report.when != "call":
            category = "ERROR"
        self.rows.append(dict(test_id=report.nodeid, phase=report.when, outcome=report.outcome,
                              category=category, duration=report.duration,
                              wasxfail=getattr(report, "wasxfail", None),
                              detail=str(report.longrepr) if not report.passed else None))

    def pytest_sessionfinish(self, session, exitstatus):
        (OUT / "original_suite.json").write_text(json.dumps(dict(exit_code=int(exitstatus),
            collected=session.testscollected, schema="ORIGINAL FIXTURES: METADATA; parity test uses separate DBs",
            results=self.rows, collection=self.collection,
            phase_counts=dict(Counter(r["phase"] for r in self.rows)),
            outcomes=dict(Counter(r["category"] for r in self.rows if r["phase"] == "call" or r["category"] == "ERROR"))), indent=2), encoding="utf8")


async def new_probe_session(name):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    name = "audit_" + name + "_test_" + NONCE[:12]
    await create_database(name)
    migrate(name)
    engine = create_async_engine(url(name))
    return async_sessionmaker(engine, expire_on_commit=False), engine, name


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--migrate":
        environment(sys.argv[2])
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("alembic.ini"), "head")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--suite":
        environment(sys.argv[2])
        import pytest
        raise SystemExit(pytest.main(["tests", "-q", "-p", "pytest_asyncio.plugin", "-p", "respx.plugin",
            "-p", "no:cacheprovider", "--tb=short", "--junitxml=/audit-output/original_suite.xml"], plugins=[ResultPlugin()]))
    return run_stage()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, default=str), encoding="utf8")


def semantic_schema(raw):
    def default(value):
        if value is None:
            return None
        value = str(value)
        return "SERIAL_SEQUENCE" if value.startswith("nextval(") else value.replace("::character varying", "::text")
    result = {}
    for table, data in raw.items():
        result[table] = dict(
            columns={c["name"]: dict(type=c["type"], timezone=c.get("timezone"), nullable=c["nullable"], default=default(c.get("default"))) for c in data["columns"]},
            checks=sorted(c["sqltext"] for c in data["checks"]),
            unique=sorted({tuple(sorted(c["column_names"])) for c in data["unique"]} | {tuple(sorted(i["column_names"])) for i in data["indexes"] if i["unique"] and not i.get("dialect_options", {}).get("postgresql_where")}),
            primary_key=data["primary_key"]["constrained_columns"],
            foreign_keys=sorted((dict(columns=f["constrained_columns"], table=f["referred_table"],
                                     referred=f["referred_columns"], options=f.get("options", {})) for f in data["foreign_keys"]), key=str),
            indexes=sorted((dict(columns=i["column_names"], unique=i["unique"], options=i.get("dialect_options", {}))
                            for i in data["indexes"] if not i.get("duplicates_constraint") and (not i["unique"] or i.get("dialect_options", {}).get("postgresql_where")) and not any(sorted(i["column_names"]) == sorted(u["column_names"]) for u in data["unique"])), key=str))
    return result


def run_stage():
    stage = os.environ["AUDIT_STAGE"]
    names = {key: "audit_" + key + "_test_" + NONCE[:12] for key in ("suite", "migrated", "metadata")}
    environment(names["suite"])
    versions = {p: importlib.metadata.version(p) for p in ("pytest", "pytest-asyncio", "SQLAlchemy", "asyncpg", "alembic", "httpx", "pydantic", "fastapi", "respx", "ruff", "bcrypt")}
    write("environment.json", dict(python=sys.version, packages=versions, databases=names, nonce=NONCE,
          base_sha=os.environ["BASE_SHA"], audit_sha=os.environ["AUDIT_SHA"], providers="SIMULATED; external network blocked"))
    (OUT / "dependency-install.json").write_bytes(Path("/dependency-install.json").read_bytes())
    exit_code = 1
    summary = dict(stage=stage, base_sha=os.environ["BASE_SHA"], audit_sha=os.environ["AUDIT_SHA"])
    try:
        if stage == "suite":
            asyncio.run(create_database(names["suite"]))
            result = subprocess.run([sys.executable, __file__, "--suite", names["suite"]], capture_output=True, text=True, timeout=1800)
            (OUT / "original_suite.log").write_text(result.stdout + result.stderr, encoding="utf8")
            suite = json.loads((OUT / "original_suite.json").read_text())
            lint = subprocess.run([sys.executable, "-m", "ruff", "check", "."], capture_output=True, text=True)
            (OUT / "ruff.log").write_text(lint.stdout + lint.stderr)
            exit_code = int(bool(result.returncode or lint.returncode or not suite["collected"]))
            summary.update(suite_exit_code=result.returncode, ruff_exit_code=lint.returncode, collected=suite["collected"], outcomes=suite["outcomes"])
        elif stage == "schema":
            for key in ("migrated", "metadata"):
                asyncio.run(create_database(names[key]))
            migrate(names["migrated"])
            before = asyncio.run(schema(names["migrated"]))
            metadata = asyncio.run(schema(names["metadata"], metadata=True))
            after = asyncio.run(schema(names["migrated"]))
            left, right = semantic_schema(before), semantic_schema(metadata)
            differences = {t: dict(migrated=left.get(t), metadata=right.get(t)) for t in sorted(set(left) | set(right)) if left.get(t) != right.get(t)}
            write("schema_comparison.json", dict(migrated=before, metadata=metadata, semantic_differences=differences,
                  migrated_preserved=before == after, limitations="Expression equivalence requires review; names/order/serial sequence names normalized"))
            exit_code = int(bool(differences or before != after))
            summary.update(differing_tables=list(differences), migrated_preserved=before == after)
        else:
            import audit_db_probes
            import integrated_flows
            rows = asyncio.run(audit_db_probes.run(new_probe_session))
            write("database_probes.json", rows)
            integrated = asyncio.run(integrated_flows.run(new_probe_session))
            write("integrated_flows.json", integrated)
            bad = {"FAIL_REQUIREMENT", "HARNESS_ERROR", "ERROR_PRODUCT"}
            exit_code = int(len(rows) != 36 or not integrated or any(r["status"] in bad for r in rows + integrated))
            summary.update(database_probe_count=len(rows), integrated_count=len(integrated),
                           results=dict(Counter(r["status"] for r in rows + integrated)))
    except Exception as error:
        summary["preparation_or_harness_error"] = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
    summary["exit_code"] = exit_code
    write("stage_summary.json", summary)
    print(json.dumps(summary))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        (OUT / "driver_error.json").write_text(json.dumps(dict(error_type=type(error).__name__, error=str(error))), encoding="utf8")
        raise

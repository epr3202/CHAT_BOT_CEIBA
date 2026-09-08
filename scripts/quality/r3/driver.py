"""R2 candidate tests with retained R1 nodes and independent Alembic regressions."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from scripts.quality.r0.isolation import OUT, Isolation


def write(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, default=str))


class Results:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.collection: list[dict[str, Any]] = []
        self.nodes: list[str] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.nodes = [item.nodeid for item in session.items]

    def pytest_collectreport(self, report: Any) -> None:
        self.collection.append(
            dict(
                nodeid=report.nodeid,
                outcome=report.outcome,
                detail=str(report.longrepr) if report.failed else None,
            )
        )

    def pytest_runtest_logreport(self, report: Any) -> None:
        self.rows.append(
            dict(
                nodeid=report.nodeid,
                phase=report.when,
                outcome=report.outcome,
                duration=report.duration,
                wasxfail=getattr(report, "wasxfail", None),
                detail=str(report.longrepr) if not report.passed else None,
            )
        )

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        write(
            "results.json",
            dict(
                collected=session.testscollected,
                exit_code=int(exitstatus),
                nodes=self.nodes,
                phases=dict(Counter(r["phase"] for r in self.rows)),
                outcomes=dict(Counter(r["outcome"] for r in self.rows if r["phase"] == "call")),
                results=self.rows,
                collection=self.collection,
                schema="Alembic; no metadata reset"
                if os.environ["QUALITY_STAGE"] == "regressions"
                else "Original suite metadata fixtures",
            ),
        )


def main() -> None:
    if sys.version_info[:2] != (3, 12) or Path("/source/.env").exists():
        raise SystemExit("Wrong runtime or unsafe source")
    os.chdir("/source")
    sys.path.insert(0, "/source")
    OUT.mkdir(exist_ok=True)
    import httpx

    names = (
        "ConnectError",
        "ReadError",
        "WriteError",
        "CloseError",
        "RemoteProtocolError",
        "ProxyError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "HTTPStatusError",
        "LocalProtocolError",
        "UnsupportedProtocol",
        "InvalidURL",
    )
    write(
        "httpx_hierarchy.json",
        {
            "version": importlib.metadata.version("httpx"),
            "classes": {name: [c.__name__ for c in getattr(httpx, name).__mro__] for name in names},
            "cancelled_error": [c.__name__ for c in asyncio.CancelledError.__mro__],
        },
    )
    summary: dict[str, Any] = dict(
        base_sha=os.environ["BASE_SHA"],
        candidate_sha=os.environ["CANDIDATE_SHA"],
        stage=os.environ["QUALITY_STAGE"],
    )
    exit_code = 1
    try:
        isolation = Isolation()
        isolation.install()
        asyncio.run(isolation.create_database())
        os.environ.update(
            DATABASE_URL=isolation.url(),
            TEST_DATABASE_URL=isolation.url(),
            ENVIRONMENT="testing",
            META_APP_SECRET="synthetic-r1",
            META_ACCESS_TOKEN="synthetic-r1",
            OPENROUTER_API_KEY="synthetic-r1",
            CALENDAR_ADAPTER="fake",
            CATALOG_STORAGE_DIR="/tmp/r0-catalogs",
            PAYMENT_EVIDENCE_DIR="/tmp/r0-evidence",
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        )
        names = (
            "pytest",
            "pytest-asyncio",
            "SQLAlchemy",
            "asyncpg",
            "alembic",
            "httpx",
            "respx",
            "pydantic",
            "fastapi",
            "ruff",
            "bcrypt",
        )
        write(
            "environment.json",
            dict(
                python=sys.version,
                packages={n: importlib.metadata.version(n) for n in names},
                database=isolation.database,
                role=isolation.role,
                instance=isolation.system_identifier,
                container=isolation.container,
                network="internal Docker network and socket/DB attestation guard",
                providers="SIMULATED",
                **summary,
            ),
        )
        (OUT / "dependency-install.json").write_bytes(Path("/dependency-install.json").read_bytes())
        # Probe the guard itself before tests, without contacting another destination.
        for mutation in (
            {"host": "unowned.invalid"},
            {"database": "another_test"},
            {"user": "unowned"},
        ):
            fields = dict(
                host=isolation.ip,
                user=isolation.role,
                password=isolation.password,
                database=isolation.database,
            )
            fields.update(mutation)
            try:
                isolation.check_destination((), fields)
            except RuntimeError:
                continue
            raise RuntimeError("Database guard accepted an unauthorized destination")
        try:
            import socket

            socket.getaddrinfo("unowned.invalid", 443)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Network guard failed its negative control")
        isolation.blocked.clear()
        write(
            "isolation_controls.json",
            dict(
                wrong_host="REJECTED",
                wrong_database="REJECTED",
                wrong_role="REJECTED",
                external_dns="REJECTED",
                database_resource_created_by_job=True,
            ),
        )
        lint_command = [sys.executable, "-m", "ruff", "check", "."]
        lint = subprocess.run(lint_command, capture_output=True, text=True, timeout=120)
        (OUT / "ruff.log").write_text(lint.stdout + lint.stderr)
        summary.update(ruff_command=lint_command, ruff_exit_code=lint.returncode)
        if summary["stage"] == "regressions":
            from alembic.config import Config

            from alembic import command

            command.upgrade(Config("alembic.ini"), "head")
            summary["migration_commands"] = ["alembic upgrade head (in-process, guarded)"]
        nodes = ["tests/remediation"] if summary["stage"] == "regressions" else ["tests"]
        args = [
            *nodes,
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "-p",
            "respx.plugin",
            "-p",
            "no:cacheprovider",
            "--tb=short",
            "--junitxml=/quality-output/results.xml",
        ]
        summary["pytest_args"] = args
        with (OUT / "pytest.log").open("w") as log:
            from contextlib import redirect_stderr, redirect_stdout

            with redirect_stdout(log), redirect_stderr(log):
                code = pytest.main(args, plugins=[Results()])
        summary["pytest_exit_code"] = int(code)
        summary["unexpected_network_attempts"] = isolation.blocked
        import app

        source_root = Path(app.__file__).resolve().parent
        if source_root != Path("/source/app"):
            raise RuntimeError("Imported product outside candidate source")
        imported = {}
        for name, module in list(sys.modules.items()):
            if name.startswith(("app.", "tests.")) and getattr(module, "__file__", None):
                path = Path(module.__file__).resolve()
                if not path.is_relative_to(Path("/source") / name.split(".")[0]):
                    raise RuntimeError("Imported application/test module outside candidate")
                imported[name] = {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
        write(
            "import_provenance.json",
            dict(
                candidate_sha=summary["candidate_sha"],
                app_path=str(source_root),
                runner_path=__file__,
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                test_root="/source/tests",
                diagnostic_plugin_loaded=False,
                imported_modules=imported,
            ),
        )
        result = json.loads((OUT / "results.json").read_text())
        summary.update(
            collected=result["collected"], outcomes=result["outcomes"], phases=result["phases"]
        )
        required = set(json.loads(Path("scripts/quality/r3/r2_nodes.json").read_text()))
        missing = sorted(required - set(result["nodes"])) if summary["stage"] == "suite" else []
        summary["missing_r2_suite_nodes"] = missing
        incomplete = [
            node
            for node in result["nodes"]
            if {r["phase"] for r in result["results"] if r["nodeid"] == node}
            != {"setup", "call", "teardown"}
        ]
        bad_phase = any(r["outcome"] != "passed" or r["wasxfail"] for r in result["results"])
        summary["incomplete_nodes"] = incomplete
        new_nodes = [n for n in result["nodes"] if n.startswith("tests/remediation/test_r1_")]
        summary["r1_nodes"] = new_nodes
        missing_r1 = len(new_nodes) != 37 or not (set(new_nodes) <= required)
        r2_nodes = [n for n in result["nodes"] if n.startswith("tests/remediation/r2/")]
        summary["r2_nodes"] = r2_nodes
        missing_r2 = len(r2_nodes) != 34
        summary["expected_r2_count"] = 34
        summary["expected_r1_count"] = 37
        required_r3 = set(json.loads(Path("scripts/quality/r3/new_nodes.json").read_text()))
        r3_nodes = {n for n in result["nodes"] if n.startswith("tests/remediation/r3/")}
        summary["r3_nodes"] = sorted(r3_nodes)
        summary["missing_r3_nodes"] = sorted(required_r3 - r3_nodes)
        missing_r3 = required_r3 != r3_nodes
        exit_code = int(
            bool(
                code
                or lint.returncode
                or isolation.blocked
                or not result["collected"]
                or missing
                or incomplete
                or bad_phase
                or missing_r1
                or missing_r2
                or missing_r3
            )
        )
    except Exception as error:
        summary["harness_error"] = dict(
            type=type(error).__name__, message=str(error), traceback=traceback.format_exc()
        )
    summary["exit_code"] = exit_code
    write("stage_summary.json", summary)
    print(json.dumps(summary))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

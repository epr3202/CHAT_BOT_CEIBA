"""Disposable A1 infrastructure verification on a GitHub-hosted runner only."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

from scripts import staging


def main() -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise RuntimeError("Disposable GitHub-hosted runner required")
    with tempfile.TemporaryDirectory(prefix="a1-tls-") as directory:
        root = Path(directory)
        cert, key = root / "cert.pem", root / "key.pem"
        staging.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=staging-ci.localhost",
                "-addext",
                "subjectAltName=DNS:staging-ci.localhost",
            ]
        )
        key.chmod(0o600)
        os.environ.update(
            ENVIRONMENT="staging",
            POSTGRES_USER="ceiba_staging_ci",
            POSTGRES_DB="ceiba_staging_ci",
            POSTGRES_PASSWORD=secrets.token_hex(32),
            STAGING_TLS_NAME="staging-ci.localhost",
            STAGING_TLS_CERT=str(cert),
            STAGING_TLS_KEY=str(key),
        )
        staging.validate_inputs()
        staging.config()
        try:
            staging.run([*staging.COMPOSE, "up", "-d", "--wait", "--wait-timeout", "120"])
            before = staging.verify()
            # Synthetic persistence probe solely in this job-owned empty database.
            marker = secrets.token_hex(16)
            staging.sql("CREATE TABLE a1_persistence_probe (value text NOT NULL)")
            staging.sql(f"INSERT INTO a1_persistence_probe VALUES ('{marker}')")
            staging.run([*staging.COMPOSE, "up", "-d", "--force-recreate", "--wait", "db"])
            after = staging.verify()
            assert before == after
            assert staging.sql("SELECT value FROM a1_persistence_probe") == marker
            target = root / "target.staging.json"
            target.write_text(json.dumps(after), encoding="utf-8")
            assert json.loads(target.read_text()) == after
            for path in (".env", ".env.staging", "target.staging.json", "private.key", "cert.pem"):
                staging.run(["git", "check-ignore", path])
            tracked = staging.run(["git", "ls-files"]).splitlines()
            assert not any(
                p.endswith((".key", ".pem")) or p in {".env", ".env.staging"} for p in tracked
            )
            for path in tracked:
                content = Path(path).read_bytes()
                assert b"-----BEGIN " + b"PRIVATE KEY-----" not in content
            print(
                "A1 CI PASS: Compose, PG16, health, persistence, "
                "private networking, TLS, target, secrets"
            )
            print(json.dumps(after, sort_keys=True))
        finally:
            # Only this disposable hosted runner; never an operator/staging cleanup command.
            subprocess.run(
                [*staging.COMPOSE, "down", "--volumes"],
                check=True,
                timeout=120,
                stdout=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()

"""Explicit artifact deployment. No automatic checkout, build, or DB downgrade."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

BASE = "4c767e029709354864c36767dfb25cbe1c95931d"
HEAD = "20260910_0027"


def validate_sha(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("An exact full Git SHA is required")


def run(args: list[str]) -> str:
    # Never echo environment or subprocess error output, which may contain secrets.
    result = subprocess.run(args, capture_output=True, text=True, timeout=1800)
    if result.returncode:
        raise RuntimeError("Release command failed: " + args[0])
    return result.stdout.strip()


def verify_checkout(sha: str, runner: Callable = run) -> str:
    validate_sha(sha)
    if runner(["git", "rev-parse", "HEAD"]) != sha:
        raise ValueError("Checkout must already be detached at the requested exact SHA")
    runner(["git", "cat-file", "-e", sha + "^{commit}"])
    runner(["git", "merge-base", "--is-ancestor", BASE, sha])
    if runner(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("Tracked release files must be clean")
    return runner(["git", "rev-parse", "HEAD^{tree}"])


def validate_manifest(value: dict, sha: str) -> dict:
    validate_sha(sha)
    if value.get("sha") != sha or value.get("migration_head") != HEAD:
        raise ValueError("Artifact release/schema identity mismatch")
    validate_sha(value.get("tree", ""))
    for key in ("api_image", "frontend_image"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value.get(key, "")):
            raise ValueError("Immutable local Docker image ID required")
    return value


def deploy_steps(*, rollback: bool) -> list[str]:
    return [
        "close",
        "stop",
        "uncertain",
        "backup",
        "preflight",
        *([] if rollback else ["migrate"]),
        "verify",
        "api",
        "worker",
        "frontend",
        "health",
        "smoke",
        "reopen",
    ]


def execute_steps(steps: list[str], action: Callable[[str], None]) -> None:
    for step in steps:
        print(json.dumps({"release_step": step}), flush=True)
        action(step)


def encrypted_backup(compose: list[str], directory: Path, recipient: str) -> None:
    if not directory.is_absolute() or not directory.is_dir() or not recipient:
        raise ValueError("Existing protected backup directory and GPG recipient required")
    from datetime import UTC, datetime

    path = directory / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".dump.gpg")
    dump = subprocess.Popen(
        [
            *compose,
            "exec",
            "-T",
            "db",
            "sh",
            "-ec",
            'exec pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        encrypted = subprocess.run(
            ["gpg", "--batch", "--encrypt", "--recipient", recipient, "--output", str(path)],
            stdin=dump.stdout,
            capture_output=True,
            timeout=1800,
        )
        dump.stdout.close()
        if dump.wait(timeout=60) or encrypted.returncode or not path.stat().st_size:
            raise RuntimeError("Encrypted backup failed")
    finally:
        if dump.poll() is None:
            dump.kill()
            dump.wait()
    # Validate actual decrypted archive; absence of the restore key blocks deployment.
    decrypt = subprocess.Popen(
        ["gpg", "--batch", "--decrypt", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        verify = subprocess.run(
            [*compose, "exec", "-T", "db", "pg_restore", "--list"],
            stdin=decrypt.stdout,
            capture_output=True,
            timeout=1800,
        )
        decrypt.stdout.close()
        if decrypt.wait(timeout=60) or verify.returncode or not verify.stdout:
            raise RuntimeError("Backup restore-list verification failed")
    finally:
        if decrypt.poll() is None:
            decrypt.kill()
            decrypt.wait()
    path.with_suffix(path.suffix + ".sha256").write_text(
        hashlib.file_digest(path.open("rb"), "sha256").hexdigest() + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    tree = verify_checkout(args.sha)
    artifact = validate_manifest(json.loads(args.manifest.read_text()), args.sha)
    if tree != artifact["tree"]:
        raise ValueError("Artifact tree mismatch")
    target = json.loads(args.target.read_text())
    if target["environment"] not in {"staging", "production"}:
        raise ValueError("Protected target required")
    if Path.cwd().resolve() != Path(target["checkout_path"]).resolve():
        raise ValueError("Target checkout path mismatch")
    if os.uname().nodename != target["hostname"]:
        raise ValueError("Target host mismatch")
    if os.environ.get("ENVIRONMENT") != target["environment"]:
        raise ValueError("Environment mismatch")
    for key in ("api_image", "frontend_image"):
        info = json.loads(run(["docker", "image", "inspect", artifact[key]]))[0]
        labels = info["Config"]["Labels"]
        if (
            info["Id"] != artifact[key]
            or labels.get("org.opencontainers.image.revision") != args.sha
            or labels.get("ceiba.tree") != tree
            or labels.get("ceiba.migration") != HEAD
        ):
            raise ValueError("Image identity/labels mismatch")
    from urllib.parse import unquote, urlsplit

    db = urlsplit(os.environ.get("DATABASE_URL", ""))
    if (
        db.scheme != "postgresql+asyncpg"
        or db.hostname != "db"
        or db.port not in {None, 5432}
        or unquote(db.path.lstrip("/")) != os.environ.get("POSTGRES_DB")
        or unquote(db.username or "") != os.environ.get("POSTGRES_USER")
        or unquote(db.password or "") != os.environ.get("POSTGRES_PASSWORD")
        or db.query
        or db.fragment
    ):
        raise ValueError("Runtime DB must match the backed-up Compose target")
    os.environ.update(API_IMAGE=artifact["api_image"], FRONTEND_IMAGE=artifact["frontend_image"])
    compose = [
        "docker",
        "compose",
        "--project-name",
        target["project"],
        "-f",
        "compose.protected.yml",
    ]
    # Resolve required variables without printing the expanded secrets.
    run([*compose, "config", "--quiet"])
    identity = run(
        [
            *compose,
            "exec",
            "-T",
            "db",
            "sh",
            "-ec",
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc '
            "'SELECT system_identifier FROM pg_control_system()'",
        ]
    )
    if identity != target["database_system_identifier"]:
        raise ValueError("Database target identity mismatch")
    for name in ("close", "smoke", "reopen"):
        hook = Path(target[name + "_hook"])
        if not hook.is_absolute() or not hook.is_file():
            raise ValueError("Reviewed absolute target hook required: " + name)
    print(
        json.dumps(
            {
                "sha": args.sha,
                "tree": tree,
                "migration_head": HEAD,
                "steps": deploy_steps(rollback=args.rollback),
                "execute": args.execute,
            }
        )
    )
    if not args.execute:
        return

    def oneshot(*command: str) -> None:
        run([*compose, "run", "--rm", "--no-deps", "app", *command])

    def action(step: str) -> None:
        if step in {"close", "smoke", "reopen"}:
            run([target[step + "_hook"]])
        elif step == "stop":
            run([*compose, "stop", "--timeout", "180", "frontend", "app", "worker"])
            running = run([*compose, "ps", "--status", "running", "--services"])
            if {"app", "worker", "frontend"} & set(running.splitlines()):
                raise RuntimeError("Old consumers still running")
        elif step == "uncertain":
            count = run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "db",
                    "sh",
                    "-ec",
                    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc '
                    "\"SELECT count(*) FROM outbox WHERE status = 'SENDING' "
                    "OR to_jsonb(outbox)->'send_admission'->>'phase' IN ('UNKNOWN','ADMITTED')\"",
                ]
            )
            if count != "0":
                raise RuntimeError("Uncertain external operations require human reconciliation")
        elif step == "backup":
            encrypted_backup(compose, Path(target["backup_dir"]), target["backup_gpg_recipient"])
        elif step in {"preflight", "verify"}:
            oneshot(
                "python",
                "-m",
                "app.config.readiness",
                "migration-preflight" if step == "preflight" else "database",
            )
        elif step == "migrate":
            oneshot("alembic", "upgrade", HEAD)
        elif step in {"api", "worker", "frontend"}:
            run(
                [
                    *compose,
                    "up",
                    "-d",
                    "--no-build",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "360",
                    "app" if step == "api" else step,
                ]
            )
        elif step == "health":
            oneshot("python", "-m", "app.config.readiness", "database")
            run(
                [*compose, "exec", "-T", "worker", "python", "-m", "app.config.readiness", "worker"]
            )

    execute_steps(deploy_steps(rollback=args.rollback), action)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Release aborted; traffic must remain closed. Inspect gate by NAME."
        ) from None

"""R0 launcher derived from diagnostic run_ci.py at 97bd4de; candidate extraction."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

BASE = "89356876a04bc836ea9b2c223ff8aba2b424ffde"
R0_BASE = "97bd4de96a9fdd59fb8f0f92865d3c7c16f48caa"


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get(
        "GITHUB_REF", ""
    ).startswith("refs/heads/quality/r0-"):
        raise SystemExit("Only the authorized GitHub Actions quality branch may run this launcher")
    stage = sys.argv[1]
    if stage not in {"focused", "suite"}:
        raise SystemExit("Unknown stage")
    repo = Path.cwd()
    audit = Path(__file__).resolve().parent
    output = repo / "quality-output" / stage
    output.mkdir(parents=True, exist_ok=False)
    nonce = uuid.uuid4().hex
    manifest = dict(
        base_sha=BASE,
        candidate_sha=os.environ["GITHUB_SHA"],
        run_id=os.environ["GITHUB_RUN_ID"],
        run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
        stage=stage,
        nonce=nonce,
        commands=[],
        preparation="STARTED",
    )

    def run(
        *args: str, check: bool = True, timeout: int = 1200
    ) -> subprocess.CompletedProcess[bytes]:
        # Only synthetic per-run credentials occur in these commands.
        manifest["commands"].append(list(args))
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        if (
            args[:2] in {("docker", "build"), ("docker", "pull"), ("docker", "start")}
            or result.returncode
        ):
            with (output / "launcher.log").open("ab") as handle:
                handle.write(result.stdout + result.stderr)
        if check and result.returncode:
            raise RuntimeError(f"Command failed: {args[:2]}, code={result.returncode}")
        return result

    network, database, runner = [f"ceiba-r0-{name}-{nonce}" for name in ("net", "db", "run")]
    resources = []
    label = "ceiba.quality.r0=" + nonce
    exit_code = 1

    def owned(kind: str, name: str) -> dict[str, Any]:
        value = json.loads(run("docker", kind, "inspect", name).stdout)[0]
        labels = (
            value.get("Labels", {})
            if kind == "network"
            else value.get("Config", {}).get("Labels", {})
        )
        if labels.get("ceiba.quality.r0") != nonce:
            raise RuntimeError("Refusing mutation of a resource not owned by this run")
        return value

    try:
        actual = run("git", "rev-parse", "HEAD").stdout.decode().strip()
        if actual != manifest["candidate_sha"]:
            raise RuntimeError("Checkout SHA mismatch")
        if os.environ.get("CANDIDATE_SHA") != actual:
            raise RuntimeError("Event candidate SHA mismatch")
        changed = run("git", "diff", "--name-only", R0_BASE, actual).stdout.decode().splitlines()
        allowed = set(json.loads((audit / "allowed_paths.json").read_text()))
        if not changed or set(changed) - allowed:
            raise RuntimeError("Candidate changes paths outside the explicit allowlist")
        manifest["authorized_changed_paths"] = changed
        baseline = json.loads((audit / "baseline_manifest.json").read_text())
        if baseline["r0_base_sha"] != R0_BASE:
            raise RuntimeError("Wrong R0 baseline")
        protected = {}
        for rel, item in baseline["files"].items():
            if rel not in allowed:
                actual_blob = run("git", "rev-parse", actual + ":" + rel).stdout.decode().strip()
                if actual_blob != item["git_blob"]:
                    raise RuntimeError("Protected blob changed: " + rel)
                protected[rel] = actual_blob
        manifest["protected_blobs"] = protected
        manifest["r0_base_sha"] = R0_BASE
        root = Path(tempfile.mkdtemp(prefix="ceiba-r0-"))
        source = root / "source"
        source.mkdir()
        expected = json.loads((audit / "source_manifest.json").read_text())
        if expected["base_sha"] != BASE:
            raise RuntimeError("Wrong baseline manifest")
        copied = {}
        source_entries = dict(expected["files"])
        for rel in allowed:
            if rel.startswith(("tests/", "scripts/quality/r0/")):
                source_entries.setdefault(rel, {"mode": "100644"})
        for rel, item in source_entries.items():
            path = Path(rel)
            if (
                path.is_absolute()
                or ".." in path.parts
                or any(p.startswith(".env") for p in path.parts)
                or item["mode"] not in {"100644", "100755"}
            ):
                raise RuntimeError("Unsafe manifest path")
            data = run("git", "cat-file", "blob", actual + ":" + rel).stdout
            digest = hashlib.sha256(data).hexdigest()
            git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if rel not in allowed and (digest != item["sha256"] or git_blob != item["git_blob"]):
                raise RuntimeError("Git blob mismatch: " + rel)
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            copied[rel] = digest
        manifest["source_hashes"] = copied
        manifest["source_commit"] = actual
        manifest["tests_commit"] = actual
        manifest["runner_commit"] = actual
        manifest["images"] = {}
        for image in ("python:3.12-slim", "postgres:16"):
            run("docker", "pull", image)
            info = json.loads(run("docker", "image", "inspect", image).stdout)[0]
            manifest["images"][image] = dict(id=info["Id"], repo_digests=info["RepoDigests"])
        (root / "Dockerfile").write_text(
            "FROM python:3.12-slim\nWORKDIR /source\nCOPY source/ /source/\n"
            "RUN pip install --no-cache-dir --report /dependency-install.json '.[dev]'\n"
            "ENV PYTHONDONTWRITEBYTECODE=1\n"
            'ENTRYPOINT ["python", "/source/scripts/quality/r0/driver.py"]\n'
        )
        image = "ceiba-quality-r0:" + nonce
        run("docker", "build", "--pull=false", "--label", label, "-t", image, str(root))
        run("docker", "network", "create", "--internal", "--label", label, network)
        resources.append(("network", network))
        run(
            "docker",
            "run",
            "-d",
            "--pull=never",
            "--name",
            database,
            "--label",
            label,
            "--network",
            network,
            "--network-alias",
            "audit-postgres",
            "--tmpfs",
            "/var/lib/postgresql/data",
            "-e",
            "POSTGRES_USER=audit_" + nonce,
            "-e",
            "POSTGRES_PASSWORD=synthetic_" + nonce,
            "-e",
            "POSTGRES_DB=postgres",
            "postgres:16",
        )
        resources.append(("container", database))
        deadline = time.monotonic() + 60
        while run(
            "docker", "exec", database, "pg_isready", "-U", "audit_" + nonce, check=False
        ).returncode:
            if time.monotonic() > deadline:
                raise RuntimeError("Database readiness timeout")
            time.sleep(0.2)
        db_info = owned("container", database)
        identity = run(
            "docker",
            "exec",
            database,
            "psql",
            "-U",
            "audit_" + nonce,
            "-d",
            "postgres",
            "-Atc",
            "SELECT system_identifier FROM pg_control_system()",
        )
        env = {
            "QUALITY_SYSTEM_IDENTIFIER": identity.stdout.decode().strip(),
            "AUDIT_NONCE": nonce,
            "AUDIT_DB_CONTAINER": db_info["Id"],
            "QUALITY_STAGE": stage,
            "BASE_SHA": BASE,
            "CANDIDATE_SHA": actual,
        }
        env_args = [value for key, value in env.items() for value in ("-e", key + "=" + value)]
        run(
            "docker",
            "create",
            "--pull=never",
            "--name",
            runner,
            "--label",
            label,
            "--network",
            network,
            *env_args,
            image,
        )
        resources.append(("container", runner))
        manifest.update(
            preparation="READY",
            network_internal=True,
            published_ports=[],
            providers="SIMULATED",
            test_environment_keys=sorted(env),
            database_container=db_info["Id"],
            database_image=db_info["Image"],
        )
        run("docker", "start", "-a", runner, check=False, timeout=2400)
        info = owned("container", runner)
        exit_code = info["State"]["ExitCode"]
        manifest.update(runner_exit_code=exit_code, runner_image=info["Image"])
        run("docker", "cp", runner + ":/quality-output/.", str(output))
        if not (output / "stage_summary.json").exists():
            raise RuntimeError("Required stage summary is missing")
    except Exception as error:
        exit_code = 1
        manifest["launcher_error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        for kind, name in reversed(resources):
            try:
                owned(kind, name)
                run("docker", kind, "rm", *(["-f"] if kind == "container" else []), name)
            except Exception as error:
                manifest.setdefault("cleanup_errors", []).append(str(error))
                exit_code = 1
        manifest["exit_code"] = exit_code
        (output / "host_manifest.json").write_text(json.dumps(manifest, indent=2))
        hashes = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.iterdir()
            if p.is_file()
        }
        (output / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2))
        print(
            json.dumps(
                {
                    k: manifest.get(k)
                    for k in (
                        "stage",
                        "base_sha",
                        "candidate_sha",
                        "run_id",
                        "preparation",
                        "exit_code",
                        "launcher_error",
                    )
                }
            )
        )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

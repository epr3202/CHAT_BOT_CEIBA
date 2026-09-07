"""Ephemeral GitHub-hosted audit runtime. Never accepts an existing database."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

BASE = "89356876a04bc836ea9b2c223ff8aba2b424ffde"
PREFIX = "docs/audits/2026-09-07-8935687-v0-diagnostico/"
AUDIT_FILES = ("run_ci.py", "ci_driver.py", "audit_db_probes.py", "diagnostic_driver.py", "diagnostic_plugin.py", "claim_probe.py", "case_manifest.json", "product_manifest.json", "provenance.json", "README.md")


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("GITHUB_REF", "").startswith("refs/heads/audit/v0-ci-"):
        raise SystemExit("Only the authorized GitHub Actions audit branch may run this launcher")
    stage = sys.argv[1]
    if stage not in {"original-suite", "original-isolated", "diagnostic"}:
        raise SystemExit("Unknown stage")
    repo = Path.cwd()
    audit = Path(__file__).resolve().parent
    output = repo / "audit-output" / stage
    output.mkdir(parents=True, exist_ok=False)
    nonce = uuid.uuid4().hex
    manifest = dict(base_sha=BASE, audit_sha=os.environ["GITHUB_SHA"], run_id=os.environ["GITHUB_RUN_ID"],
                    run_attempt=os.environ["GITHUB_RUN_ATTEMPT"], stage=stage, nonce=nonce, commands=[], preparation="STARTED")

    def run(*args, check=True, timeout=1200):
        # Only synthetic per-run credentials occur in these commands.
        manifest["commands"].append(list(args))
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        if args[:2] in {("docker", "build"), ("docker", "pull"), ("docker", "start")} or result.returncode:
            with (output / "launcher.log").open("ab") as handle:
                handle.write(result.stdout + result.stderr)
        if check and result.returncode:
            raise RuntimeError(f"Command failed: {args[:2]}, code={result.returncode}")
        return result

    network, database, runner = [f"ceiba-v0-{name}-{nonce}" for name in ("net", "db", "run")]
    resources = []
    label = "ceiba.audit.v0=" + nonce
    exit_code = 1

    def owned(kind, name):
        value = json.loads(run("docker", kind, "inspect", name).stdout)[0]
        labels = value.get("Labels", {}) if kind == "network" else value.get("Config", {}).get("Labels", {})
        if labels.get("ceiba.audit.v0") != nonce:
            raise RuntimeError("Refusing mutation of a resource not owned by this run")
        return value

    try:
        actual = run("git", "rev-parse", "HEAD").stdout.decode().strip()
        if actual != manifest["audit_sha"]:
            raise RuntimeError("Checkout SHA mismatch")
        changed = run("git", "diff", "--name-only", BASE, actual).stdout.decode().splitlines()
        allowed = {PREFIX + f for f in AUDIT_FILES} | {".github/workflows/audit-v0.yml"} | {"docs/audits/2026-09-07-8935687-v0-actions/" + f for f in ("run_ci.py", "ci_driver.py", "audit_db_probes.py", "integrated_flows.py", "product_manifest.json", "provenance.json", "README.md")}
        if not changed or set(changed) - allowed:
            raise RuntimeError("Audit commit changes paths outside the publication allowlist")
        manifest["audit_changed_paths"] = changed
        root = Path(tempfile.mkdtemp(prefix="ceiba-v0-"))
        source = root / "source"
        source.mkdir()
        expected = json.loads((audit / "product_manifest.json").read_text())
        if expected["base_sha"] != BASE:
            raise RuntimeError("Wrong baseline manifest")
        copied = {}
        for rel, item in expected["files"].items():
            path = Path(rel)
            if path.is_absolute() or ".." in path.parts or any(p.startswith(".env") for p in path.parts) or item["mode"] not in {"100644", "100755"}:
                raise RuntimeError("Unsafe manifest path")
            data = run("git", "cat-file", "blob", BASE + ":" + rel).stdout
            digest = hashlib.sha256(data).hexdigest()
            git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if digest != item["sha256"] or git_blob != item["git_blob"]:
                raise RuntimeError("Git blob mismatch: " + rel)
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            copied[rel] = digest
        manifest["source_hashes"] = copied
        (root / "audit").mkdir()
        for name in AUDIT_FILES:
            shutil.copyfile(audit / name, root / "audit" / name)
        manifest["audit_hashes"] = {name: hashlib.sha256((audit / name).read_bytes()).hexdigest() for name in AUDIT_FILES}
        manifest["images"] = {}
        for image in ("python:3.12-slim", "postgres:16"):
            run("docker", "pull", image)
            info = json.loads(run("docker", "image", "inspect", image).stdout)[0]
            manifest["images"][image] = dict(id=info["Id"], repo_digests=info["RepoDigests"])
        (root / "Dockerfile").write_text(
            "FROM python:3.12-slim\nWORKDIR /source\nCOPY source/ /source/\n"
            "RUN pip install --no-cache-dir --report /dependency-install.json '.[dev]'\n"
            "COPY audit/ /audit/\nENV PYTHONDONTWRITEBYTECODE=1\n"
            'ENTRYPOINT ["python", "/audit/diagnostic_driver.py"]\n')
        image = "ceiba-audit-v0:" + nonce
        run("docker", "build", "--pull=false", "--label", label, "-t", image, str(root))
        run("docker", "network", "create", "--internal", "--label", label, network)
        resources.append(("network", network))
        run("docker", "run", "-d", "--pull=never", "--name", database, "--label", label,
            "--network", network, "--network-alias", "audit-postgres", "--tmpfs", "/var/lib/postgresql/data",
            "-e", "POSTGRES_USER=audit_" + nonce, "-e", "POSTGRES_PASSWORD=synthetic_" + nonce,
            "-e", "POSTGRES_DB=postgres", "postgres:16")
        resources.append(("container", database))
        deadline = time.monotonic() + 60
        while run("docker", "exec", database, "pg_isready", "-U", "audit_" + nonce, check=False).returncode:
            if time.monotonic() > deadline:
                raise RuntimeError("Database readiness timeout")
            time.sleep(0.2)
        db_info = owned("container", database)
        env = {"AUDIT_NONCE": nonce, "AUDIT_DB_CONTAINER": db_info["Id"], "AUDIT_STAGE": stage,
               "BASE_SHA": BASE, "AUDIT_SHA": actual}
        env_args = [value for key, value in env.items() for value in ("-e", key + "=" + value)]
        run("docker", "create", "--pull=never", "--name", runner, "--label", label, "--network", network, *env_args, image)
        resources.append(("container", runner))
        manifest.update(preparation="READY", network_internal=True, published_ports=[], providers="SIMULATED",
                        test_environment_keys=sorted(env), database_container=db_info["Id"], database_image=db_info["Image"])
        run("docker", "start", "-a", runner, check=False, timeout=2400)
        info = owned("container", runner)
        exit_code = info["State"]["ExitCode"]
        manifest.update(runner_exit_code=exit_code, runner_image=info["Image"])
        run("docker", "cp", runner + ":/audit-output/.", str(output))
        if not (output / "stage_summary.json").exists():
            raise RuntimeError("Required stage summary is missing")
    except Exception as error:
        exit_code = 1
        manifest["launcher_error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        for kind, name in reversed(resources):
            try:
                owned(kind, name)
                run("docker", kind, "rm", *( ["-f"] if kind == "container" else []), name)
            except Exception as error:
                manifest.setdefault("cleanup_errors", []).append(str(error))
                exit_code = 1
        manifest["exit_code"] = exit_code
        (output / "host_manifest.json").write_text(json.dumps(manifest, indent=2))
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}
        (output / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2))
        print(json.dumps({k: manifest.get(k) for k in ("stage", "base_sha", "audit_sha", "run_id", "preparation", "exit_code", "launcher_error")}))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

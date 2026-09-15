"""A1 infrastructure operations; run on the staging Docker host with exported variables."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
from pathlib import Path

PROJECT = "ceiba-staging"
COMPOSE = ["docker", "compose", "--project-name", PROJECT, "-f", "compose.staging.yml"]


def run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError("Infrastructure command failed: " + args[0])
    return result.stdout.strip()


def clean_value(value: str) -> bool:
    return bool(value.strip()) and not re.search(r"todo|changeme|example\.com|<[^>]+>", value, re.I)


def validate_inputs() -> None:
    if os.environ.get("ENVIRONMENT") != "staging":
        raise ValueError("Explicit ENVIRONMENT=staging required")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise ValueError("Use the staging host's local default Docker daemon")
    endpoint = json.loads(run(["docker", "context", "inspect"]))[0]["Endpoints"]["docker"]["Host"]
    if endpoint != "unix:///var/run/docker.sock":
        raise ValueError("Local Linux Docker socket required")
    for name in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "STAGING_TLS_NAME"):
        if not clean_value(os.environ.get(name, "")):
            raise ValueError("Missing or placeholder input: " + name)
    if len(os.environ["POSTGRES_PASSWORD"]) < 24:
        raise ValueError("Supply a randomly generated database password of at least 24 characters")
    for name in ("STAGING_TLS_CERT", "STAGING_TLS_KEY"):
        path = Path(os.environ.get(name, ""))
        if not path.is_absolute() or not path.is_file():
            raise ValueError("External absolute file required: " + name)
        if Path.cwd().resolve() in path.resolve().parents:
            raise ValueError("TLS material must be outside the checkout")
    if Path(os.environ["STAGING_TLS_KEY"]).stat().st_mode & 0o077:
        raise ValueError("Private key must have owner-only permissions")


def config() -> dict:
    value = json.loads(run([*COMPOSE, "config", "--format", "json"]))
    assert value["name"] == PROJECT
    assert set(value["services"]) == {"db", "tls"}
    db = value["services"]["db"]
    assert db["image"].startswith("postgres:16@sha256:")
    assert not db.get("ports") and db["healthcheck"]["test"]
    assert db["volumes"][0]["type"] == "volume"
    assert db["volumes"][0]["source"] == "postgres_data"
    assert set(db["networks"]) == {"database"}
    assert value["networks"]["database"]["internal"] is True
    assert value["services"]["tls"]["ports"][0]["host_ip"] == "127.0.0.1"
    return value


def sql(query: str) -> str:
    return run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "db",
            "sh",
            "-ec",
            'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
            "sh",
            query,
        ]
    )


def verify() -> dict:
    config()
    for service in ("db", "tls"):
        container = run([*COMPOSE, "ps", "-q", service])
        info = json.loads(run(["docker", "inspect", container]))[0]
        assert info["State"]["Health"]["Status"] == "healthy"
        assert info["Config"]["Labels"]["com.docker.compose.project"] == PROJECT
        bindings = info["HostConfig"].get("PortBindings") or {}
        if service == "db":
            assert not bindings
        else:
            assert bindings == {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    assert int(sql("SHOW server_version_num")) // 10000 == 16
    run([*COMPOSE, "exec", "-T", "tls", "nginx", "-t"])
    name = os.environ["STAGING_TLS_NAME"]
    run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--noproxy",
            "*",
            "--cacert",
            os.environ["STAGING_TLS_CERT"],
            "--resolve",
            f"{name}:8443:127.0.0.1",
            f"https://{name}:8443/infra-health",
        ]
    )
    target = {
        "scope": "A1-infrastructure",
        "environment": "staging",
        "project": PROJECT,
        "hostname": socket.gethostname(),
        "checkout_path": str(Path.cwd().resolve()),
        "database_system_identifier": sql("SELECT system_identifier FROM pg_control_system()"),
        "database": os.environ["POSTGRES_DB"],
        "database_user": os.environ["POSTGRES_USER"],
        "database_host": "db",
        "database_port": 5432,
        "tls_name": name,
        "admin_binding": "127.0.0.1:8443",
    }
    assert all(clean_value(str(value)) for value in target.values())
    assert re.fullmatch(r"[0-9]+", target["database_system_identifier"])
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("config", "up", "verify", "target", "ps", "logs", "stop")
    )
    args = parser.parse_args()
    validate_inputs()
    if args.action == "config":
        config()
    elif args.action == "up":
        config()
        run([*COMPOSE, "up", "-d", "--wait", "--wait-timeout", "120"])
        verify()
    elif args.action in {"verify", "target"}:
        target = verify()
        if args.action == "target":
            # Never replace a previously recorded destination implicitly.
            with Path("target.staging.json").open("x", encoding="utf-8") as handle:
                json.dump(target, handle, indent=2)
                handle.write("\n")
    else:
        print(run([*COMPOSE, args.action, *(["--tail", "100"] if args.action == "logs" else [])]))
    print("A1 " + args.action + " PASS")


if __name__ == "__main__":
    main()

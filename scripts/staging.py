"""A1 infrastructure operations; run on the staging Docker host with exported variables."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
from pathlib import Path, PurePosixPath

PROJECT = "ceiba-staging"
COMPOSE = ["docker", "compose", "--project-name", PROJECT, "-f", "compose.staging.yml"]


def run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, OSError):
        raise RuntimeError("Infrastructure command unavailable or timed out") from None
    if result.returncode:
        raise RuntimeError("Infrastructure command failed: " + args[0])
    return result.stdout.strip()


def clean_value(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not re.search(
            r"todo|changeme|example\.com|[<>]|not_provisioned|required_external|placeholder",
            value,
            re.I,
        )
    )


def validate_target(target: dict) -> None:
    """Validate SCOPE A1 structure only; operator evidence remains mandatory."""
    for name in (
        "environment",
        "hostname",
        "checkout_path",
        "project",
        "database_system_identifier",
        "backup_dir",
        "backup_gpg_recipient",
        "close_hook",
        "smoke_hook",
        "reopen_hook",
    ):
        if not clean_value(target.get(name)):
            raise ValueError("Missing or placeholder target field: " + name)
    if target["environment"] != "staging" or target["project"] != PROJECT:
        raise ValueError("A1 requires the staging environment and project")
    if not re.fullmatch(r"[0-9]+", target["database_system_identifier"]):
        raise ValueError("Observed PostgreSQL system identifier required")
    for name in ("checkout_path", "backup_dir", "close_hook", "smoke_hook", "reopen_hook"):
        if not PurePosixPath(target[name]).is_absolute():
            raise ValueError("Absolute host path required: " + name)
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", target["backup_gpg_recipient"]):
        raise ValueError("Approved full GPG fingerprint required")


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

    def require(condition: bool, label: str) -> None:
        if not condition:
            raise ValueError("Unsafe A1 Compose configuration: " + label)

    require(value.get("name") == PROJECT, "project")
    services = value.get("services", {})
    require(set(services) == {"db", "tls"}, "services")
    db, tls = services["db"], services["tls"]
    require(bool(re.fullmatch(r"postgres:16@sha256:[0-9a-f]{64}", db.get("image", ""))), "PG16")
    require(not db.get("ports"), "DB ports")
    for service in (db, tls):
        health = service.get("healthcheck", {})
        require(
            bool(health.get("test")) and not health.get("disable") and health["test"][0] != "NONE",
            "healthcheck",
        )
    require(
        any(
            m.get("type") == "volume"
            and m.get("source") == "postgres_data"
            and m.get("target") == "/var/lib/postgresql/data"
            for m in db.get("volumes", [])
        ),
        "persistent DB mount",
    )
    volume = value.get("volumes", {}).get("postgres_data", {})
    require(
        volume.get("name") == PROJECT + "_postgres_data" and not volume.get("external"),
        "dedicated volume",
    )
    require(set(db.get("networks", {})) == {"database"}, "DB network")
    require(set(tls.get("networks", {})) == {"edge"}, "TLS network")
    networks = value.get("networks", {})
    require(networks.get("database", {}).get("internal") is True, "internal DB network")
    for name in ("database", "edge"):
        network = networks.get(name, {})
        require(
            network.get("name") == PROJECT + "_" + name and not network.get("external"),
            "dedicated network",
        )
    ports = tls.get("ports", [])
    require(
        len(ports) == 1
        and ports[0].get("host_ip") == "127.0.0.1"
        and str(ports[0].get("published")) == "8443"
        and ports[0].get("target") == 8443,
        "admin loopback",
    )
    for target in ("/run/tls/fullchain.pem", "/run/tls/privkey.pem"):
        mounts = [m for m in tls.get("volumes", []) if m.get("target") == target]
        require(
            len(mounts) == 1
            and mounts[0].get("type") == "bind"
            and mounts[0].get("read_only") is True
            and not mounts[0].get("bind", {}).get("create_host_path", False),
            "TLS RO mount",
        )
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

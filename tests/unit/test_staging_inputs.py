"""A1 rejects missing or placeholder destination input without external calls."""

import copy
import json
import secrets
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import staging
from scripts.staging import clean_value


@pytest.mark.parametrize("value", ["", " ", "TODO", "changeme", "example.com", "<host>"])
def test_staging_rejects_placeholder(value: str) -> None:
    assert not clean_value(value)


def test_staging_accepts_observed_identity() -> None:
    assert clean_value("ceiba-staging")


@pytest.mark.parametrize("value", ["NOT_PROVISIONED", "required_external", "PLACEHOLDER", "<>"])
def test_unprovisioned_values_are_rejected(value: str) -> None:
    assert not clean_value(value)


@pytest.mark.parametrize("environment", [None, "production", "development", "testing", ""])
def test_environment_rejected_before_docker(
    monkeypatch: pytest.MonkeyPatch,
    environment: str | None,
) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    if environment is not None:
        monkeypatch.setenv("ENVIRONMENT", environment)
    runner = Mock(side_effect=AssertionError("Docker must not run"))
    monkeypatch.setattr(staging, "run", runner)
    with pytest.raises(ValueError, match="staging"):
        staging.validate_inputs()
    runner.assert_not_called()


@pytest.fixture
def inputs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)
    for name in ("DOCKER_HOST", "DOCKER_CONTEXT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "ENVIRONMENT": "staging",
        "POSTGRES_USER": "a1_test",
        "POSTGRES_DB": "a1_test",
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "STAGING_TLS_NAME": "staging-ci.localhost",
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("STAGING_TLS_CERT", "STAGING_TLS_KEY"):
        path = tmp_path / name
        path.touch()  # Filesystem validation only; not certificate evidence.
        monkeypatch.setenv(name, str(path))
    monkeypatch.setattr(
        staging,
        "run",
        Mock(
            return_value=json.dumps(
                [{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}]
            )
        ),
    )
    return checkout


@pytest.mark.parametrize(
    "name", ["POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "STAGING_TLS_NAME"]
)
def test_required_inputs_reject_empty(
    monkeypatch: pytest.MonkeyPatch,
    inputs: Path,
    name: str,
) -> None:
    monkeypatch.setenv(name, "")
    with pytest.raises(ValueError, match=name):
        staging.validate_inputs()


@pytest.mark.parametrize("name", ["STAGING_TLS_CERT", "STAGING_TLS_KEY"])
def test_tls_cannot_live_in_checkout(
    monkeypatch: pytest.MonkeyPatch,
    inputs: Path,
    name: str,
) -> None:
    path = inputs / "material"
    path.touch()
    monkeypatch.setenv(name, str(path))
    with pytest.raises(ValueError, match="outside the checkout"):
        staging.validate_inputs()


def test_private_key_requires_owner_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    inputs: Path,
) -> None:
    original = Path.stat

    def stat(path: Path, *args: object, **kwargs: object) -> object:
        result = original(path, *args, **kwargs)
        if path.name == "STAGING_TLS_KEY":
            return type("Stat", (), {"st_mode": 0o100644})()
        return result

    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(ValueError, match="owner-only"):
        staging.validate_inputs()


@pytest.fixture
def rendered() -> dict:
    return {
        "name": "ceiba-staging",
        "services": {
            "db": {
                "image": "postgres:16@sha256:" + "a" * 64,
                "healthcheck": {"test": ["CMD-SHELL", "pg_isready"]},
                "volumes": [
                    {
                        "type": "volume",
                        "source": "postgres_data",
                        "target": "/var/lib/postgresql/data",
                    }
                ],
                "networks": {"database": {}},
            },
            "tls": {
                "ports": [{"host_ip": "127.0.0.1", "published": "8443", "target": 8443}],
                "networks": {"edge": {}},
                "healthcheck": {"test": ["CMD", "wget"]},
                "volumes": [
                    {
                        "type": "bind",
                        "target": target,
                        "read_only": True,
                        "bind": {"create_host_path": False},
                    }
                    for target in ("/run/tls/fullchain.pem", "/run/tls/privkey.pem")
                ],
            },
        },
        "networks": {
            "database": {"internal": True, "name": "ceiba-staging_database"},
            "edge": {"name": "ceiba-staging_edge"},
        },
        "volumes": {"postgres_data": {"name": "ceiba-staging_postgres_data"}},
    }


@pytest.mark.parametrize(
    "defect",
    [
        "pg_major",
        "db_health",
        "db_port",
        "internal",
        "persistent",
        "volume_name",
        "loopback",
        "extra_port",
        "tls_health",
        "tls_rw",
        "tls_db_network",
        "external_volume",
    ],
)
def test_config_rejects_unsafe_topology(
    monkeypatch: pytest.MonkeyPatch,
    rendered: dict,
    defect: str,
) -> None:
    value = copy.deepcopy(rendered)
    db, tls = value["services"]["db"], value["services"]["tls"]
    if defect == "pg_major":
        db["image"] = db["image"].replace(":16@", ":15@")
    elif defect == "db_health":
        db["healthcheck"]["disable"] = True
    elif defect == "db_port":
        db["ports"] = [{"published": "5432"}]
    elif defect == "internal":
        value["networks"]["database"]["internal"] = False
    elif defect == "persistent":
        db["volumes"][0]["type"] = "tmpfs"
    elif defect == "volume_name":
        value["volumes"]["postgres_data"]["name"] = "production_postgres_data"
    elif defect == "loopback":
        tls["ports"][0]["host_ip"] = "0.0.0.0"
    elif defect == "extra_port":
        tls["ports"].append({"host_ip": "0.0.0.0", "published": "9443", "target": 8443})
    elif defect == "tls_health":
        tls["healthcheck"]["disable"] = True
    elif defect == "tls_rw":
        tls["volumes"][0]["read_only"] = False
    elif defect == "tls_db_network":
        tls["networks"]["database"] = {}
    else:
        value["volumes"]["postgres_data"]["external"] = True
    monkeypatch.setattr(staging, "run", Mock(return_value=json.dumps(value)))
    with pytest.raises(ValueError):
        staging.config()


def test_config_accepts_isolated_topology(monkeypatch: pytest.MonkeyPatch, rendered: dict) -> None:
    monkeypatch.setattr(staging, "run", Mock(return_value=json.dumps(rendered)))
    assert staging.config() == rendered


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_command_errors_do_not_expose_output(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    sentinel = secrets.token_hex(32)
    if failure == "exit":
        runner = Mock(return_value=subprocess.CompletedProcess(["docker"], 1, sentinel, sentinel))
    else:
        runner = Mock(
            side_effect=subprocess.TimeoutExpired(
                ["docker", sentinel], 180, output=sentinel, stderr=sentinel
            )
        )
    monkeypatch.setattr(staging.subprocess, "run", runner)
    with pytest.raises(RuntimeError) as error:
        staging.run(["docker", sentinel])
    assert sentinel not in str(error.value)


@pytest.fixture
def target() -> dict:
    # Synthetic identities only; never written as an operational target.
    return dict(
        environment="staging",
        hostname="ci-host",
        checkout_path="/ci/checkout",
        project="ceiba-staging",
        database_system_identifier="123456789",
        backup_dir="/ci/backup",
        backup_gpg_recipient="A" * 40,
        close_hook="/ci/close",
        smoke_hook="/ci/smoke",
        reopen_hook="/ci/reopen",
    )


@pytest.mark.parametrize(
    "field",
    [
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
    ],
)
@pytest.mark.parametrize("invalid", [None, "", "NOT_PROVISIONED", "<pending>"])
def test_target_requires_every_contract_field(
    target: dict, field: str, invalid: str | None
) -> None:
    target[field] = invalid
    with pytest.raises(ValueError):
        staging.validate_target(target)


def test_target_rejects_production(target: dict) -> None:
    target["environment"] = "production"
    with pytest.raises(ValueError):
        staging.validate_target(target)


def test_target_contract_accepts_complete_synthetic_input(target: dict) -> None:
    staging.validate_target(target)


def test_compose_password_is_required_external() -> None:
    source = Path("compose.postgres.yml").read_text()
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}" in source

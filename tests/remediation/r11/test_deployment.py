import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.release import BASE, HEAD, deploy_steps, execute_steps, validate_manifest, validate_sha


@pytest.mark.parametrize("identity", ["", "main", "latest", "abcdef", "x" * 40])
def test_d01_d02_r01_r02_reject_mutable_or_missing_identity(identity):
    with pytest.raises(ValueError):
        validate_sha(identity)


def test_d03_r03_exact_identity():
    value = dict(
        sha=BASE,
        tree="a" * 40,
        migration_head=HEAD,
        api_image="sha256:" + "b" * 64,
        frontend_image="sha256:" + "c" * 64,
    )
    assert validate_manifest(value, BASE) == value
    with pytest.raises(ValueError):
        validate_manifest(value, "d" * 40)


def test_d04_no_mutable_release_selection():
    for name in ("deploy.sh", "rollback.sh", "scripts/release.py"):
        source = Path(name).read_text()
        assert "origin/main" not in source
        assert "git pull" not in source


def test_d05_stop_backup_before_migration():
    steps = deploy_steps(rollback=False)
    assert steps.index("stop") < steps.index("uncertain") < steps.index("backup")
    assert steps.index("backup") < steps.index("preflight") < steps.index("migrate")
    assert steps.index("verify") < steps.index("api") < steps.index("worker")
    assert steps[-1] == "reopen"


def test_backup_failure_prevents_migration_and_reopen():
    called = []

    def action(step):
        called.append(step)
        if step == "backup":
            raise RuntimeError("backup failed")

    with pytest.raises(RuntimeError):
        execute_steps(deploy_steps(rollback=False), action)
    assert "migrate" not in called and "reopen" not in called


def test_r04_rollback_never_downgrades_or_defaults_to_r9():
    assert "migrate" not in deploy_steps(rollback=True)
    assert "downgrade" not in deploy_steps(rollback=True)
    from scripts.release import verify_checkout

    runner = Mock(return_value="")
    with pytest.raises(ValueError):
        verify_checkout("a9ce7f34342f19022ae608ab48bad4b0654b52d2", runner)


def test_manifest_rejects_mutable_image():
    with pytest.raises(ValueError):
        validate_manifest(json.loads('{"api_image":"latest"}'), BASE)


@pytest.mark.parametrize("rollback,fail_backup", [(False, False), (True, False), (False, True)])
def test_real_deployment_controller_orders_commands(monkeypatch, tmp_path, rollback, fail_backup):
    import sys

    from scripts import release

    artifact = dict(
        sha=BASE,
        tree="a" * 40,
        migration_head=HEAD,
        api_image="sha256:" + "b" * 64,
        frontend_image="sha256:" + "c" * 64,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(artifact))
    target = dict(
        environment="staging",
        hostname=release.os.uname().nodename,
        checkout_path=str(Path.cwd()),
        project="synthetic-r11",
        database_system_identifier="123",
        backup_dir=str(tmp_path),
        backup_gpg_recipient="synthetic-test-key",
    )
    for name in ("close", "smoke", "reopen"):
        hook = tmp_path / name
        hook.write_text("synthetic")
        target[name + "_hook"] = str(hook)
    target_file = tmp_path / "target.json"
    target_file.write_text(json.dumps(target))
    for key, value in dict(
        ENVIRONMENT="staging",
        POSTGRES_DB="test",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="synthetic",
        DATABASE_URL="postgresql+asyncpg://test:synthetic@db/test",
    ).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(release, "verify_checkout", lambda sha: "a" * 40)
    commands = []

    def command(args):
        commands.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [
                    dict(
                        Id=args[3],
                        Config=dict(
                            Labels={
                                "org.opencontainers.image.revision": BASE,
                                "ceiba.tree": "a" * 40,
                                "ceiba.migration": HEAD,
                            }
                        ),
                    )
                ]
            )
        if "pg_control_system" in args[-1]:
            return "123"
        if "SELECT count(*)" in args[-1]:
            return "0"
        return ""

    def backup(*args):
        commands.append(["BACKUP"])
        if fail_backup:
            raise RuntimeError("backup verification failure")

    monkeypatch.setattr(release, "run", command)
    monkeypatch.setattr(release, "encrypted_backup", backup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release",
            BASE,
            "--manifest",
            str(manifest),
            "--target",
            str(target_file),
            "--execute",
            *(["--rollback"] if rollback else []),
        ],
    )
    if fail_backup:
        with pytest.raises(RuntimeError):
            release.main()
    else:
        release.main()
    stop = next(i for i, args in enumerate(commands) if "stop" in args)
    checkpoint = commands.index(["BACKUP"])
    assert stop < checkpoint
    migrations = [i for i, args in enumerate(commands) if "alembic" in args]
    if fail_backup or rollback:
        assert migrations == []
    else:
        assert checkpoint < migrations[0]
        assert commands[migrations[0]][-1] == HEAD
    if fail_backup:
        assert [target["reopen_hook"]] not in commands
        assert not any("up" in args for args in commands)
    else:
        assert commands[-1] == [target["reopen_hook"]]

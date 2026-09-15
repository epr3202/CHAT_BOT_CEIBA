"""Build and inspect actual deployable images, using only ephemeral CI resources."""

import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

from scripts.release import run


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("CI only")
    sha = os.environ["GITHUB_SHA"]
    subprocess.run(
        ["python", "-m", "scripts.build_release", sha, "--output", "release-artifact"], check=True
    )
    artifact = json.loads(Path("release-artifact/manifest.json").read_text())
    for component in ("api", "frontend"):
        result = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", artifact[component + "_image"]],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            raise RuntimeError("Image accepted missing environment")
        if b"explicit" not in (result.stdout + result.stderr).lower():
            raise RuntimeError("Image failed for a reason other than the environment guard")
    # Positive protected one-shot validates config/storage without contacting providers.
    with tempfile.TemporaryDirectory(prefix="ceiba-storage-") as storage:
        Path(storage).chmod(0o777)
        env = {
            "ENVIRONMENT": "staging",
            "DEPLOYED_RUNTIME": "false",
            "DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@db/test",
            "META_APP_SECRET": "synthetic",
            "META_VERIFY_TOKEN": "synthetic",
            "META_ACCESS_TOKEN": "synthetic",
            "META_PHONE_NUMBER_ID": "123",
            "OPENROUTER_API_KEY": "synthetic",
            "CALENDAR_ADAPTER": "google",
            "CATALOG_STORAGE_DIR": "/data/catalogs",
            "PAYMENT_EVIDENCE_DIR": "/data/payment-evidence",
        }
        env_args = [value for key, value in env.items() for value in ("-e", key + "=" + value)]
        run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                *env_args,
                "-v",
                storage + ":/data/catalogs",
                "-v",
                storage + ":/data/payment-evidence:ro",
                artifact["api_image"],
                "python",
                "-c",
                "from app.config.settings import get_settings; "
                "assert get_settings().deployed_runtime",
            ]
        )
    # Test Docker's real context filtering, not a custom approximation of ignore syntax.
    with tempfile.TemporaryDirectory(prefix="ceiba-context-") as temp:
        root = Path(temp)
        (root / ".dockerignore").write_bytes(Path(".dockerignore").read_bytes())
        for name in (
            ".env",
            ".env.production",
            "credentials.json",
            "private.pem",
            "private.key",
            "secrets/value",
            ".r11-work/.env",
            ".git/config",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic-secret-context-test")
        (root / "public.txt").write_text("required-runtime-data")
        (root / "Dockerfile").write_text("FROM scratch\nCOPY . /\n")
        iid = root / "image-id"
        run(["docker", "build", "--iidfile", str(iid), str(root)])
        container = run(["docker", "create", iid.read_text().strip(), "/absent"])
        try:
            archive = root / "export.tar"
            run(["docker", "export", "--output", str(archive), container])
            with tarfile.open(archive) as tar:
                names = tar.getnames()
                if "public.txt" not in names:
                    raise RuntimeError("Context test lost runtime files")
                for entry in tar:
                    if entry.isfile():
                        content = tar.extractfile(entry).read()
                        if b"synthetic-secret-context-test" in content:
                            raise RuntimeError("Secret reached Docker context")
        finally:
            run(["docker", "rm", container])
    Path("release-artifact/build-checks.json").write_text(
        json.dumps(
            {
                "sha": sha,
                "context_secret_filter": "PASS",
                "protected_entrypoints": "PASS",
                "artifact": artifact,
            },
            indent=2,
        )
    )
    print("R11_ARTIFACT:" + json.dumps(artifact), flush=True)


if __name__ == "__main__":
    main()

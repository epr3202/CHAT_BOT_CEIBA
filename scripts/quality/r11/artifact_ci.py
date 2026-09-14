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


if __name__ == "__main__":
    main()

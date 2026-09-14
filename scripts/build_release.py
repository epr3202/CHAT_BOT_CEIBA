"""Build exact tracked SHA once and preserve both images for offline promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

from scripts.release import HEAD, run, verify_checkout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    tree = verify_checkout(args.sha)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = dict(sha=args.sha, tree=tree, migration_head=HEAD)
    with tempfile.TemporaryDirectory(prefix="ceiba-build-") as temporary:
        root = Path(temporary)
        archive = root / "source.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", "--output", str(archive), args.sha],
            check=True,
            timeout=60,
        )
        source = root / "source"
        with tarfile.open(archive) as tar:
            tar.extractall(source, filter="data")
        for component, dockerfile in (("api", "Dockerfile"), ("frontend", "frontend/Dockerfile")):
            iid = root / (component + ".iid")
            run(
                [
                    "docker",
                    "build",
                    "--iidfile",
                    str(iid),
                    "--label",
                    "org.opencontainers.image.revision=" + args.sha,
                    "--label",
                    "ceiba.tree=" + tree,
                    "--label",
                    "ceiba.migration=" + HEAD,
                    "-f",
                    str(source / dockerfile),
                    str(source),
                ]
            )
            manifest[component + "_image"] = iid.read_text().strip()
        image_archive = args.output / "images.tar"
        run(
            [
                "docker",
                "save",
                "--output",
                str(image_archive),
                manifest["api_image"],
                manifest["frontend_image"],
            ]
        )
        with image_archive.open("rb") as file:
            manifest["archive_sha256"] = hashlib.file_digest(file, "sha256").hexdigest()
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()

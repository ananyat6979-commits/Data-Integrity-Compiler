"""Build a source ZIP and a sidecar identifying its exact Git tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_value(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/kaggle_upload/data-integrity-compiler-source.zip"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    commit = git_value(root, "rev-parse", f"{args.revision}^{{commit}}")
    tree = git_value(root, "rev-parse", f"{args.revision}^{{tree}}")
    subprocess.run(["git", "archive", "--format=zip", f"--output={output}", args.revision],
                   cwd=root, check=True)
    embedded = {"revision": args.revision, "commit_sha": commit, "tree_sha": tree}
    with zipfile.ZipFile(output, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SOURCE_REVISION.json", json.dumps(embedded, indent=2) + "\n")
    provenance = {**embedded,
                  "source_archive_sha256": sha256(output)}
    sidecar = output.with_suffix(".provenance.json")
    sidecar.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Source archive: {output}")
    print(f"Provenance sidecar: {sidecar}")


if __name__ == "__main__":
    main()

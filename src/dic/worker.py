from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from dic.pipeline import run_in_process


def _deny_ground_truth(event: str, args: tuple[object, ...]) -> None:
    if event != "open" or not args:
        return
    path = str(args[0]).replace("\\", "/").lower()
    if any(part.startswith("ground_truth") for part in Path(path).parts):
        raise PermissionError(f"Detector attempted to open forbidden ground truth path: {path}")


def main() -> None:
    args = json.loads(sys.stdin.read())
    sys.addaudithook(_deny_ground_truth)
    root = Path(args["root"])
    runs = root / "data" / "runs"
    before = {path.resolve() for path in runs.iterdir() if path.is_dir()} if runs.exists() else set()
    try:
        result = run_in_process(Path(args["trips_path"]), Path(args["lookup_path"]), root,
                                args.get("fault_id"), Path(args["reference_lookup"]) if args.get("reference_lookup") else None)
    except Exception:
        current = root / "data" / "published" / "CURRENT"
        selected = None
        if current.is_file():
            try:
                selected = json.loads(current.read_text(encoding="utf-8")).get("run_id")
            except (OSError, json.JSONDecodeError):
                pass
        if runs.is_dir():
            for path in runs.iterdir():
                if path.is_dir() and path.resolve() not in before and path.name != selected:
                    shutil.rmtree(path, ignore_errors=True)
        raise
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
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
                                args.get("fault_id"), Path(args["reference_lookup"]) if args.get("reference_lookup") else None,
                                args.get("test_failpoint"))
    except Exception as exc:
        current = root / "data" / "published" / "CURRENT"
        selected = None
        if current.is_file():
            try:
                selected = json.loads(current.read_text(encoding="utf-8")).get("run_id")
            except (OSError, json.JSONDecodeError):
                pass
        failed_paths = []
        if runs.is_dir():
            for path in runs.iterdir():
                if path.is_dir() and path.resolve() not in before and path.name != selected:
                    failed_paths.append(path)
        failures = root / "data" / "failures"
        failures.mkdir(parents=True, exist_ok=True)
        failure_id = failed_paths[0].name if failed_paths else uuid.uuid4().hex
        record = {"failure_id": failure_id, "run_id": failure_id if failed_paths else None,
                  "status": "failed",
                  "failed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "error_type": type(exc).__name__, "error": str(exc),
                  "current_run_id": selected,
                  "staging_artifacts": [p.name for p in failed_paths[0].iterdir()] if failed_paths else []}
        (failures / f"{failure_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        for path in failed_paths:
            shutil.rmtree(path, ignore_errors=True)
        raise
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()

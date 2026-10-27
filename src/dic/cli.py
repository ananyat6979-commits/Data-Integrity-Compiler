from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from dic.pipeline import acquire, collect_orphaned_staging, evaluate, inject_m1, run


def main() -> None:
    p = argparse.ArgumentParser(prog="dic")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("acquire"); a.add_argument("--month", required=True)
    r = sub.add_parser("run"); r.add_argument("--month", required=True); r.add_argument("--lookup", type=Path); r.add_argument("--reference-lookup", type=Path); r.add_argument("--fault-id")
    i = sub.add_parser("inject-m1"); i.add_argument("--month", required=True); i.add_argument("--key", required=True)
    e = sub.add_parser("evaluate"); e.add_argument("--report", type=Path, required=True); e.add_argument("--ground-truth", type=Path, required=True)
    x = sub.add_parser("experiment-m1"); x.add_argument("--month", required=True); x.add_argument("--key", required=True)
    g = sub.add_parser("gc", help="inspect or remove old incomplete staging directories")
    g.add_argument("--root", type=Path, required=True, help="repository root containing .git and pyproject.toml")
    g.add_argument("--older-than-hours", type=float, default=24)
    g.add_argument("--delete", action="store_true", help="remove eligible candidates; default is dry-run")
    args = p.parse_args()
    root = Path.cwd()
    if args.cmd == "acquire":
        result = acquire(root / "data/raw", args.month)
    elif args.cmd == "run":
        result = run(root / "data/raw" / f"yellow_tripdata_{args.month}.parquet", args.lookup or root / "data/raw/taxi_zone_lookup.csv", root, args.fault_id, args.reference_lookup or root / "data/raw/taxi_zone_lookup.csv")
    elif args.cmd == "inject-m1":
        result = {k: str(v) for k, v in inject_m1(root / "data/raw/taxi_zone_lookup.csv", root / "data/runs", args.key).items()}
    elif args.cmd == "experiment-m1":
        trips = root / "data/raw" / f"yellow_tripdata_{args.month}.parquet"
        lookup = root / "data/raw/taxi_zone_lookup.csv"
        clean = run(trips, lookup, root)
        fault_input = inject_m1(lookup, root / "data/runs", args.key)
        fault = run(trips, fault_input["lookup"], root, fault_input["fault_id"], lookup)
        clean_report_path = root / "data/clean_report.json"
        fault_report_path = root / "data/fault_report.json"
        clean_report_path.parent.mkdir(parents=True, exist_ok=True)
        clean_report_path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
        fault_report_path.write_text(json.dumps(fault, indent=2), encoding="utf-8")
        evaluated = evaluate(root / "data/runs" / fault["run_id"] / "report.json", fault_input["ground_truth"])
        reconciliation = subprocess.run([sys.executable, str(root / "experiments/reconcile_reports.py"), "--root", str(root)],
                                        cwd=root, text=True, capture_output=True)
        if reconciliation.returncode:
            raise RuntimeError(reconciliation.stderr.strip() or reconciliation.stdout.strip())
        result = {"clean_run_id": clean["run_id"], "fault_run_id": fault["run_id"],
                  "evaluation": evaluated, "reconciliation": json.loads((root / "data/jan-2024-reconciliation.json").read_text(encoding="utf-8")),
                  "reports": {"clean": str(clean_report_path), "fault": str(fault_report_path)}}
    elif args.cmd == "gc":
        result = collect_orphaned_staging(args.root, args.older_than_hours, args.delete)
    else:
        result = evaluate(args.report, args.ground_truth)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

"""Read-only schema and source audit of NYC TLC Yellow Taxi monthly Parquet files.

Records, per month: file size, SHA-256, row count, ordered column names and types, pickup-time
coverage (separating near-boundary spill from pickups more than one day outside the month), null counts on key columns, and counts that mirror the declared cleaning rules. Months
with identical schemas are grouped into cohorts, and each transition between cohorts lists added,
removed, retyped, and case-only-renamed columns. Raw files are never modified and no timestamps are
written, so the same inputs always produce the same JSON.

Usage:
    python experiments/m2a/schema_audit.py --raw data/raw --start 2022-01 --end 2025-12 \
        --out experiments/m2a/audit/schema_audit_2022-01_2025-12.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import duckdb

AUDIT_VERSION = 1
NULL_COLUMNS = ["tpep_pickup_datetime", "tpep_dropoff_datetime", "PULocationID", "DOLocationID", "fare_amount"]


def month_range(start: str, end: str) -> list[str]:
    def parse(value: str) -> tuple[int, int]:
        year, month = value.split("-")
        if not (1 <= int(month) <= 12):
            raise ValueError(f"Invalid month: {value}")
        return int(year), int(month)

    y, m = parse(start)
    ey, em = parse(end)
    if (y, m) > (ey, em):
        raise ValueError("start must not be after end")
    months = []
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def audit_month(path: Path, month: str) -> dict[str, Any]:
    con = duckdb.connect()
    source = f"read_parquet('{_sql_path(path)}')"
    columns = [{"name": row[0], "type": row[1]} for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
    names = {column["name"] for column in columns}
    signature = hashlib.sha256(json.dumps(columns, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    expressions = ["count(*)"]
    labels = ["rows"]
    if "tpep_pickup_datetime" in names:
        expressions += ["min(tpep_pickup_datetime)::VARCHAR", "max(tpep_pickup_datetime)::VARCHAR",
                        f"count(*) FILTER (WHERE strftime(tpep_pickup_datetime, '%Y-%m') <> '{month}')",
                        f"count(*) FILTER (WHERE tpep_pickup_datetime < (DATE '{month}-01' - INTERVAL 1 DAY) "
                        f"OR tpep_pickup_datetime >= (DATE '{month}-01' + INTERVAL 1 MONTH + INTERVAL 1 DAY))"]
        labels += ["pickup_min", "pickup_max", "rows_outside_month", "rows_beyond_1_day_of_month"]
    for column in NULL_COLUMNS:
        if column in names:
            expressions.append(f'count(*) FILTER (WHERE "{column}" IS NULL)')
            labels.append(f"null:{column}")
    if "fare_amount" in names:
        expressions.append("count(*) FILTER (WHERE fare_amount < 0)")
        labels.append("negative_fare_rows")
    if "trip_distance" in names:
        expressions.append("count(*) FILTER (WHERE trip_distance <= 0)")
        labels.append("nonpositive_distance_rows")
    if "PULocationID" in names:
        expressions += ["min(PULocationID)", "max(PULocationID)"]
        labels += ["pu_min", "pu_max"]
    values = dict(zip(labels, con.execute(f"SELECT {', '.join(expressions)} FROM {source}").fetchone()))
    con.close()
    return {
        "month": month,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": values["rows"],
        "columns": columns,
        "schema_signature": signature,
        "pickup_min": values.get("pickup_min"),
        "pickup_max": values.get("pickup_max"),
        "rows_outside_month": values.get("rows_outside_month"),
        "rows_beyond_1_day_of_month": values.get("rows_beyond_1_day_of_month"),
        "nulls": {label.split(":", 1)[1]: value for label, value in values.items() if label.startswith("null:")},
        "negative_fare_rows": values.get("negative_fare_rows"),
        "nonpositive_distance_rows": values.get("nonpositive_distance_rows"),
        "pickup_location_id_range": [values.get("pu_min"), values.get("pu_max")],
    }


def _transition(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    old = {c["name"]: c["type"] for c in previous["columns"]}
    new = {c["name"]: c["type"] for c in current["columns"]}
    case_pairs = [{"from": o, "to": n} for o in old for n in new if o != n and o.casefold() == n.casefold()]
    renamed_from = {pair["from"] for pair in case_pairs}
    renamed_to = {pair["to"] for pair in case_pairs}
    return {
        "from": previous["cohort_id"], "to": current["cohort_id"], "first_month_of_to": current["months"][0],
        "added": sorted(set(new) - set(old) - renamed_to), "removed": sorted(set(old) - set(new) - renamed_from),
        "type_changed": [{"column": n, "from": old[n], "to": new[n]} for n in sorted(set(old) & set(new)) if old[n] != new[n]],
        "case_only_renames": case_pairs,
    }


def build_report(raw_dir: Path, months: list[str]) -> dict[str, Any]:
    missing = [m for m in months if not (raw_dir / f"yellow_tripdata_{m}.parquet").is_file()]
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} source files, first few: {', '.join(missing[:5])}")
    records = [audit_month(raw_dir / f"yellow_tripdata_{m}.parquet", m) for m in months]
    cohorts: list[dict[str, Any]] = []
    for record in records:
        if cohorts and cohorts[-1]["signature"] == record["schema_signature"]:
            cohorts[-1]["months"].append(record["month"])
        else:
            cohorts.append({"cohort_id": f"C{len(cohorts) + 1}", "signature": record["schema_signature"],
                            "column_count": len(record["columns"]), "columns": record["columns"], "months": [record["month"]]})
    for cohort in cohorts:
        for record in records:
            if record["month"] in cohort["months"]:
                record["cohort_id"] = cohort["cohort_id"]
    transitions = [_transition(a, b) for a, b in zip(cohorts, cohorts[1:])]
    for record in records:
        record.pop("columns")  # the full column list lives on the cohort; keep month records compact
    return {
        "audit_version": AUDIT_VERSION,
        "range": {"start": months[0], "end": months[-1], "months": len(months)},
        "tool": {"duckdb": duckdb.__version__, "python": platform.python_version()},
        "cohorts": cohorts,
        "transitions": transitions,
        "months": records,
    }


def summarize(report: dict[str, Any]) -> str:
    lines = [f"Months audited: {report['range']['months']} ({report['range']['start']} to {report['range']['end']})",
             f"Schema cohorts: {len(report['cohorts'])}"]
    for cohort in report["cohorts"]:
        lines.append(f"  {cohort['cohort_id']}: {cohort['months'][0]} to {cohort['months'][-1]} "
                     f"({len(cohort['months'])} months, {cohort['column_count']} columns)")
    for t in report["transitions"]:
        lines.append(f"  {t['from']} -> {t['to']} at {t['first_month_of_to']}: added={t['added']} removed={t['removed']} "
                     f"retyped={[x['column'] for x in t['type_changed']]} "
                     f"case_renames={[(x['from'], x['to']) for x in t['case_only_renames']]}")
    flagged = [(r["month"], r["rows_outside_month"]) for r in report["months"] if r["rows_outside_month"]]
    far = [(r["month"], r["rows_beyond_1_day_of_month"]) for r in report["months"] if r["rows_beyond_1_day_of_month"]]
    lines.append(f"Months with pickups outside their month (boundary spill plus far-out): {len(flagged)} of {len(report['months'])}")
    lines.append(f"Pickups MORE than 1 day outside their month, by month: {far or 'none'}")
    lines.append("Month, rows, negative fares, non-positive distances, null PULocationID:")
    for r in report["months"]:
        lines.append(f"  {r['month']}  {r['rows']:>9}  {r['negative_fare_rows']}  {r['nonpositive_distance_rows']}  "
                     f"{r['nulls'].get('PULocationID')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--start", default="2022-01")
    parser.add_argument("--end", default="2025-12")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.raw, month_range(args.start, args.end))
    except (FileNotFoundError, ValueError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(summarize(report))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

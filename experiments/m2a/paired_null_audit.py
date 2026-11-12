"""Reproducible per-month audit of paired nulls and NaNs in TLC passenger and rate code fields."""
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
PAIR_COLUMNS = ("passenger_count", "RatecodeID")


def month_range(start: str, end: str) -> list[str]:
    def parse(value: str) -> tuple[int, int]:
        try:
            year_text, month_text = value.split("-")
            year, month = int(year_text), int(month_text)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid month: {value}") from exc
        if len(year_text) != 4 or len(month_text) != 2 or not 1 <= month <= 12:
            raise ValueError(f"Invalid month: {value}")
        return year, month

    year, month = parse(start)
    end_year, end_month = parse(end)
    if (year, month) > (end_year, end_month):
        raise ValueError("start must not be after end")
    result = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def audit_month(path: Path, month: str) -> dict[str, Any]:
    con = duckdb.connect()
    try:
        source = f"read_parquet('{_sql_path(path)}')"
        columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
        missing_columns = sorted(set(PAIR_COLUMNS) - set(columns))
        if missing_columns:
            raise ValueError(f"{path.name} is missing required columns: {', '.join(missing_columns)}")
        row = con.execute(
            f"""SELECT
                count(*)::BIGINT,
                count(*) FILTER (WHERE passenger_count IS NULL)::BIGINT,
                count(*) FILTER (WHERE RatecodeID IS NULL)::BIGINT,
                count(*) FILTER (WHERE passenger_count IS NULL AND RatecodeID IS NULL)::BIGINT,
                count(*) FILTER (WHERE (passenger_count IS NULL) <> (RatecodeID IS NULL))::BIGINT,
                count(*) FILTER (WHERE isnan(passenger_count))::BIGINT,
                count(*) FILTER (WHERE isnan(RatecodeID))::BIGINT
            FROM {source}"""
        ).fetchone()
    finally:
        con.close()

    return {
        "month": month,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": row[0],
        "nulls": {"passenger_count": row[1], "RatecodeID": row[2]},
        "both_null_rows": row[3],
        "one_sided_null_rows": row[4],
        "nan_rows": {"passenger_count": row[5], "RatecodeID": row[6]},
    }


def build_report(raw_dir: Path, months: list[str]) -> dict[str, Any]:
    if not months:
        raise ValueError("At least one month is required")
    missing = [month for month in months if not (raw_dir / f"yellow_tripdata_{month}.parquet").is_file()]
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} source files, first few: {', '.join(missing[:5])}")
    records = [audit_month(raw_dir / f"yellow_tripdata_{month}.parquet", month) for month in months]
    return {
        "audit_version": AUDIT_VERSION,
        "range": {"start": months[0], "end": months[-1], "months": len(months)},
        "tool": {"duckdb": duckdb.__version__, "python": platform.python_version()},
        "months": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--start", default="2022-01")
    parser.add_argument("--end", default="2025-12")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.raw, month_range(args.start, args.end))
    except (FileNotFoundError, ValueError, duckdb.Error) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"Months audited: {report['range']['months']} ({report['range']['start']} to {report['range']['end']})")
    print(f"Months with one-sided nulls: {sum(bool(r['one_sided_null_rows']) for r in report['months'])}")
    print(f"Months with NaNs: {sum(any(r['nan_rows'].values()) for r in report['months'])}")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

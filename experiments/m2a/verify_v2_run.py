"""Independently reconcile a completed v2 run against source inputs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl
import duckdb

from dic.pipeline import build_v2_source_provenance, load_contract, sha256, validate_report
from experiments.m2a.oracles import canonical_rows, reference_clean, reference_daily_zone_metrics, reference_join


STAGE_COLUMNS = {
    "clean_trips": ["source_sha256", "source_row_ordinal", "pickup_zone", "pickup_date", "fare_decimal"],
    "diagnostic_join": ["source_sha256", "source_row_ordinal", "pickup_zone", "pickup_date", "fare_decimal", "matched_key", "zone_name"],
    "trip_enriched": ["source_sha256", "source_row_ordinal", "pickup_zone", "pickup_date", "fare_decimal", "matched_key", "zone_name"],
    "daily_zone_metrics": ["pickup_date", "pickup_zone", "trip_count", "revenue", "average_fare"],
}


def _row_counter(frame: pl.DataFrame, columns: list[str]) -> Counter[tuple[Any, ...]]:
    return Counter(canonical_rows(frame, columns))


def _compare(expected: pl.DataFrame, observed: pl.DataFrame, columns: list[str]) -> dict[str, Any]:
    expected_rows = _row_counter(expected, columns)
    observed_rows = _row_counter(observed, columns)
    missing = sum((expected_rows - observed_rows).values())
    unexpected = sum((observed_rows - expected_rows).values())
    return {"matches": missing == 0 and unexpected == 0,
            "expected_rows": expected.height, "observed_rows": observed.height,
            "missing_rows": missing, "unexpected_rows": unexpected}


def _source_month(report: dict[str, Any]) -> str:
    value = report.get("source_month")
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        raise ValueError("v2 report must declare source_month as YYYY-MM")
    return value


def _load_inputs(root: Path, source_path: Path, lookup_path: Path,
                 report: dict[str, Any]) -> tuple[dict[str, pl.DataFrame], dict[str, Any]]:
    contract, schema, contract_hash = load_contract(root, version="v2")
    validate_report(report)
    if report.get("contract_version") != 2 or report.get("contract_hash") != contract_hash:
        raise ValueError("Report contract identity does not match the bundled v2 contract")
    if report.get("source_artifacts", {}).get("trips_sha256") != sha256(source_path):
        raise ValueError("Source file hash differs from the report")
    if report.get("source_artifacts", {}).get("lookup_sha256") != sha256(lookup_path):
        raise ValueError("Lookup file hash differs from the report")

    raw = pl.read_parquet(source_path)
    if raw.height != report.get("source_provenance", {}).get("source_rows"):
        raise ValueError("Source row count differs from report provenance")
    source_sql = source_path.as_posix().replace("'", "''")
    with duckdb.connect(":memory:") as con:
        physical_schema = [
            {"name": row[0], "type": str(row[1])}
            for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{source_sql}')").fetchall()
        ]
    provenance = build_v2_source_provenance(
        root, source_path, _source_month(report), physical_schema, raw.height
    )
    if report.get("source_provenance") != provenance:
        raise ValueError("Report source provenance differs from the independently checked source audit")
    renames: dict[str, str] = {}
    canonical_by_fold = {name.casefold(): name for name in schema["columns"]}
    aliases = contract["normalization"]["column_aliases"]
    for name in raw.columns:
        semantic = aliases.get(name, canonical_by_fold.get(name.casefold()))
        if semantic is None:
            raise ValueError(f"No contract mapping for source column {name}")
        if semantic != name:
            renames[name] = semantic
    raw = raw.rename(renames).with_row_index("source_row_ordinal").with_columns(
        pl.lit(sha256(source_path)).alias("source_sha256"),
    )
    clean, rejected_by_rule = reference_clean(
        raw, contract["cleaning"]["rules"], _source_month(report), contract["date_coverage"]
    )
    if report.get("cleaning", {}).get("rejected_rows_by_rule") != rejected_by_rule:
        raise ValueError("First-failing-rule counts differ from independent source reconciliation")

    lookup = pl.read_csv(lookup_path, infer_schema=False)
    lookup_key = contract["join"]["lookup_key"]
    if lookup_key not in lookup.columns:
        raise ValueError(f"Lookup key {lookup_key} is missing from lookup source")
    lookup = lookup.with_columns(pl.col(lookup_key).cast(pl.Int64, strict=False).alias("lookup_zone"))
    join_key = contract["join"]["key"]
    if join_key not in clean.columns:
        raise ValueError(f"Configured join key {join_key} is missing from cleaned source")
    joined_input = clean.with_columns(
        pl.col(join_key).cast(pl.Int64, strict=False).alias("join_key"),
        pl.col(join_key).cast(pl.Int64, strict=False).alias("pickup_zone"),
        pl.col("tpep_pickup_datetime").cast(pl.Datetime, strict=False).dt.date().alias("pickup_date"),
        pl.col("fare_amount").cast(pl.Decimal(precision=18, scale=2), strict=False).alias("fare_decimal"),
    )
    # The data result is recomputed as a left join even when policy says to block.
    joined = reference_join(joined_input, lookup, "join_key", "lookup_zone", "many_to_many")
    diagnostic = joined.select(
        "source_sha256", "source_row_ordinal", "pickup_zone", "pickup_date", "fare_decimal",
        pl.col(lookup_key).cast(pl.Int64, strict=False).alias("matched_key"), pl.col("Zone").alias("zone_name"),
    )

    settings = contract["join"]
    duplicate_lookup = lookup.filter(pl.col("lookup_zone").is_not_null()).group_by("lookup_zone").len().filter(pl.col("len") > 1).height > 0
    null_lookup = lookup.get_column("lookup_zone").null_count() > 0
    multiple_matches = diagnostic.group_by("source_row_ordinal").len().filter(pl.col("len") > 1).height > 0
    unmatched = diagnostic.get_column("matched_key").null_count() > 0
    null_join = joined_input.get_column("join_key").null_count() > 0
    should_block = (
        ((duplicate_lookup or null_lookup) and settings["lookup_uniqueness_severity"] == "block")
        or (multiple_matches and settings["cardinality"] == "many_to_one" and settings["cardinality_severity"] == "block")
        or (unmatched and settings["unmatched_policy"] == "block")
        or (null_join and settings["key_non_null"])
    )
    if should_block != (report.get("outcome") == "blocked"):
        raise ValueError("Independent join-policy evaluation disagrees with report outcome")
    enriched = diagnostic.filter(pl.col("matched_key").is_not_null())
    daily_input = enriched
    if should_block:
        enriched = enriched.head(0)
    daily = reference_daily_zone_metrics(daily_input)
    return {
        "clean_trips": clean.select(STAGE_COLUMNS["clean_trips"]) if "pickup_zone" in clean.columns else joined_input.select(STAGE_COLUMNS["clean_trips"]),
        "diagnostic_join": diagnostic,
        "trip_enriched": enriched,
        "daily_zone_metrics": daily,
    }, {"contract_sha256": contract_hash, "rejected_rows_by_rule": rejected_by_rule,
        "source_rows": raw.height, "clean_rows": clean.height, "should_block": should_block}


def verify_v2_run(root: Path, run_dir: Path, source_path: Path, lookup_path: Path) -> dict[str, Any]:
    root, run_dir = root.resolve(), run_dir.resolve()
    if root not in run_dir.parents:
        raise ValueError("Run directory must be inside the repository root")
    report_path, manifest_path = run_dir / "report.json", run_dir / "manifest.json"
    if not report_path.is_file() or not manifest_path.is_file():
        raise ValueError("Run directory is missing report.json or manifest.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if report.get("run_id") != run_dir.name or manifest.get("run_id") != run_dir.name:
        raise ValueError("Run directory name, report, and manifest run IDs differ")
    if manifest.get("contract_sha256") != report.get("contract_hash"):
        raise ValueError("Manifest and report contract hashes differ")
    if manifest.get("inputs", {}).get("trips_sha256") != report.get("source_artifacts", {}).get("trips_sha256"):
        raise ValueError("Manifest and report source hashes differ")
    if manifest.get("inputs", {}).get("lookup_sha256") != report.get("source_artifacts", {}).get("lookup_sha256"):
        raise ValueError("Manifest and report lookup hashes differ")
    if manifest.get("logical_output_hashes") != report.get("logical_output_hashes"):
        raise ValueError("Manifest and report logical output hashes differ")
    expected, facts = _load_inputs(root, source_path.resolve(), lookup_path.resolve(), report)
    comparisons = {}
    for name, columns in STAGE_COLUMNS.items():
        output = run_dir / f"{name}.parquet"
        if not output.is_file():
            raise ValueError(f"Run is missing materialized output {output.name}")
        observed = pl.read_parquet(output)
        if observed.columns != columns:
            raise ValueError(f"Materialized {name} schema differs from the declared v2 output schema")
        comparisons[name] = _compare(expected[name], observed, columns)
        if not comparisons[name]["matches"]:
            raise ValueError(f"Independent {name} reconciliation failed: {comparisons[name]}")
        logical_record = report.get("logical_output_hashes", {}).get(name, "")
        try:
            recorded_rows = int(logical_record.split(";", 1)[0].removeprefix("rows="))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Report has an invalid logical row count for {name}") from exc
        if recorded_rows != expected[name].height:
            raise ValueError(f"Report row count differs from independent {name} result")

    publication_root = root / "data" / "published"
    publication_path = publication_root / "CURRENT"
    decision = report.get("publication", {}).get("decision")
    current_id = None
    if publication_path.is_file():
        current_id = json.loads(publication_path.read_text(encoding="utf-8")).get("run_id")
    if decision == "published":
        if current_id != run_dir.name or report.get("publication", {}).get("pointer_after") != run_dir.name:
            raise ValueError("Published run is not selected by CURRENT")
    elif decision == "blocked":
        pointer_before = report.get("publication", {}).get("pointer_before")
        if current_id != pointer_before:
            raise ValueError("Blocked run changed the previously selected CURRENT target")
    else:
        raise ValueError(f"Unsupported publication decision: {decision}")
    return {"verification": "valid_independent_reconciliation", "run_id": run_dir.name,
            "contract_sha256": facts["contract_sha256"], "source_rows": facts["source_rows"],
            "clean_rows": facts["clean_rows"], "publication_decision": decision,
            "current_run_id": current_id, "stages": comparisons}


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently verify an M2a contract v2 run")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lookup", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_v2_run(args.root, args.run_dir, args.source, args.lookup), indent=2))


if __name__ == "__main__":
    main()

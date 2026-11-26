"""Run the development lookup fault through the contract v2 worker."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import polars as pl

from dic.pipeline import load_contract, run
from experiments.m2a.fault_hooks import prepare_case
from experiments.m2a.verify_v2_run import verify_v2_run


def run_lookup_case(
    repository: Path, workspace: Path, source: Path, lookup: Path, severity: str, seed: int
) -> dict:
    """Run a clean control and one lookup case in a new, isolated workspace."""
    contract, _, _ = load_contract(repository, version="v2")
    audit_path = Path(contract["source_audit"]["path"])
    workspace.mkdir(parents=True, exist_ok=False)
    execution = workspace / "execution"
    shutil.copytree(repository / "contracts/v2", execution / "contracts/v2")
    (execution / audit_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repository / audit_path, execution / audit_path)

    clean = run(source, lookup, execution, contract_version="v2")
    if clean["publication"]["decision"] != "published":
        raise ValueError("The clean control did not publish")
    runs = execution / "data/runs"
    clean_dir = runs / clean["run_id"]
    verify_v2_run(execution, clean_dir, source, lookup)
    current = execution / "data/published/CURRENT"
    previous_pointer = current.read_bytes()

    clean_rows = pl.read_parquet(
        clean_dir / "clean_trips.parquet", columns=["pickup_zone", "pickup_date", "fare_decimal"]
    )
    pickup_keys = clean_rows.select(pl.col("pickup_zone").unique().alias("PULocationID"))
    lookup_frame = pl.read_csv(lookup, infer_schema=False).with_columns(pl.col("LocationID").cast(pl.Int64))
    inputs, truth = prepare_case("join_duplicate_lookup_key", severity, seed, pickup_keys, lookup_frame)
    observed_lookup = execution / "observed_lookup.csv"
    if inputs.lookup is None:
        raise RuntimeError("Lookup injection did not produce an input file")
    inputs.lookup.write_csv(observed_lookup)

    observed = run(source, observed_lookup, execution, reference_lookup=lookup, contract_version="v2")
    observed_dir = runs / observed["run_id"]
    reconciliation = verify_v2_run(execution, observed_dir, source, observed_lookup)
    if observed["publication"]["decision"] != "blocked" or current.read_bytes() != previous_pointer:
        raise ValueError("The lookup fault did not preserve the published control")

    (selected_key,) = truth.selected_keys
    copies = int(truth.parameters["duplicate_copies"])
    selected = clean_rows.filter(pl.col("pickup_zone") == selected_key)
    expected_groups = {
        (str(day), zone): (count * copies, fare * copies)
        for day, zone, count, fare in selected.group_by("pickup_date", "pickup_zone").agg(
            pl.len().alias("count"), pl.col("fare_decimal").sum()
        ).iter_rows()
    }
    entries = observed["downstream_aggregate_deltas"]
    reported_groups = {
        (entry["pickup_date"], entry["pickup_zone"]): (
            entry["trip_count_delta"], Decimal(entry["revenue_delta"])
        )
        for entry in entries
    }
    expected_inflation = selected.height * copies
    if (
        expected_inflation <= 0
        or observed["expected_observed"]["observed_row_inflation"] != expected_inflation
        or len(entries) != len(reported_groups)
        or reported_groups != expected_groups
    ):
        raise ValueError("Lookup fault impact differs from independently reconciled clean rows")

    evaluator = workspace / "evaluator"
    evaluator.mkdir()
    (evaluator / "ground_truth.lookup.json").write_text(
        json.dumps(asdict(truth), indent=2) + "\n", encoding="utf-8"
    )
    return {
        "clean_run_id": clean["run_id"],
        "observed_run_id": observed["run_id"],
        "publication_decision": reconciliation["publication_decision"],
        "current_run_id": reconciliation["current_run_id"],
        "row_inflation": expected_inflation,
        "affected_groups": len(expected_groups),
        "revenue_delta": str(sum(fare for _, fare in expected_groups.values())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lookup", type=Path, required=True)
    parser.add_argument("--severity", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--seed", type=int, choices=(11, 29, 47), default=11)
    args = parser.parse_args()
    result = run_lookup_case(
        args.repository.resolve(), args.workspace.resolve(), args.source.resolve(),
        args.lookup.resolve(), args.severity, args.seed,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

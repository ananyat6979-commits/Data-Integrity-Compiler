"""Run development faults through the contract v2 worker."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import duckdb
import dic.pipeline as pipeline
import dic.worker as worker

from dic.pipeline import SourceAuditMismatch, load_contract, run, sha256
from experiments.m2a import development_ledger, fault_hooks, oracles
from experiments.m2a.fault_hooks import prepare_case
from experiments.m2a.oracles import reference_daily_zone_metrics
from experiments.m2a.verify_v2_run import verify_v2_run


DEVELOPMENT_CASES = {
    "ingestion_duplicate_records": "duplicate-ingestion",
    "cleaning_fare_threshold": "cleaning-fare-threshold",
    "join_duplicate_lookup_key": "duplicate-lookup",
    "aggregation_sum_to_mean": "aggregation-sum-to-mean",
}


def development_plan(catalog: dict) -> list[dict]:
    design = catalog["case_design"]
    expected_severities = set(design["severities"])
    expected_seeds = set(design["seeds"])
    if (
        expected_severities != fault_hooks.SUPPORTED_SEVERITIES
        or expected_seeds != fault_hooks.SUPPORTED_SEEDS
        or len(design["severities"]) != len(expected_severities)
        or len(design["seeds"]) != len(expected_seeds)
    ):
        raise ValueError("Development plan must use each supported severity and seed exactly once")
    seen = set()
    plan = []
    for mechanism in catalog["mechanisms"]:
        if mechanism["split"] != "development":
            continue
        fault_id = mechanism["fault_id"]
        if fault_id not in DEVELOPMENT_CASES or fault_id in seen:
            raise ValueError(f"Unexpected development mechanism: {fault_id}")
        if (
            set(mechanism["severity_parameters"]) != expected_severities
            or set(mechanism["seeds"]) != expected_seeds
        ):
            raise ValueError(f"Development matrix differs from the catalog design for {fault_id}")
        seen.add(fault_id)
        for severity in design["severities"]:
            for seed in design["seeds"]:
                plan.append({"case": DEVELOPMENT_CASES[fault_id], "severity": severity, "seed": seed})
    if seen != DEVELOPMENT_CASES.keys():
        raise ValueError("Development catalog does not match the available runners")
    return plan


def _prepare_execution(repository: Path, workspace: Path) -> Path:
    contract, _, _ = load_contract(repository, version="v2")
    audit_path = Path(contract["source_audit"]["path"])
    workspace.mkdir(parents=True, exist_ok=False)
    execution = workspace / "execution"
    shutil.copytree(repository / "contracts/v2", execution / "contracts/v2")
    (execution / audit_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repository / audit_path, execution / audit_path)
    return execution


def run_lookup_case(
    repository: Path, workspace: Path, source: Path, lookup: Path, severity: str, seed: int
) -> dict:
    """Run a clean control and one lookup case in a new, isolated workspace."""
    execution = _prepare_execution(repository, workspace)
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


def run_ingestion_case(
    repository: Path, workspace: Path, source: Path, lookup: Path, severity: str, seed: int
) -> dict:
    """Verify that a source with appended duplicate rows fails the intake audit."""
    execution = _prepare_execution(repository, workspace)
    clean = run(source, lookup, execution, contract_version="v2")
    if clean["publication"]["decision"] != "published":
        raise ValueError("The clean control did not publish")
    current = execution / "data/published/CURRENT"
    before = current.read_bytes()
    runs = execution / "data/runs"
    previous_runs = {path.name for path in runs.iterdir()}

    original = pl.read_parquet(source)
    inputs, truth = prepare_case("ingestion_duplicate_records", severity, seed, original)
    observed_path = execution / "observed-source" / source.name
    observed_path.parent.mkdir()
    inputs.source.write_parquet(observed_path)

    # Reopen the actual worker input and compare the ordered prefix and appended rows.
    observed = pl.read_parquet(observed_path)
    expected = original.with_row_index().filter(
        pl.col("index").is_in(list(truth.selected_ordinals))
    ).drop("index")
    if (
        observed.height != original.height + int(truth.parameters["duplicate_rows"])
        or not observed.head(original.height).equals(original)
        or not observed.slice(original.height).equals(expected)
    ):
        raise ValueError("Appended rows do not match the selected original rows")

    try:
        run(observed_path, lookup, execution, contract_version="v2")
    except RuntimeError:
        failures = list((execution / "data/failures").glob("*.json"))
        if len(failures) != 1:
            raise
        record = json.loads(failures[0].read_text(encoding="utf-8"))
        if (
            record["error_type"] != SourceAuditMismatch.__name__
            or record["status"] != "failed"
            or record["current_run_id"] != clean["run_id"]
            or record["staging_artifacts"]
        ):
            raise
    else:
        raise ValueError("The worker accepted a source that differs from the pinned audit")

    if current.read_bytes() != before or {path.name for path in runs.iterdir()} != previous_runs:
        raise ValueError("Source rejection changed published or staged runs")

    evaluator = workspace / "evaluator"
    evaluator.mkdir()
    (evaluator / "ground_truth.ingestion.json").write_text(
        json.dumps(asdict(truth), indent=2) + "\n", encoding="utf-8"
    )
    return {
        "clean_run_id": clean["run_id"],
        "failure_id": record["failure_id"],
        "outcome": "rejected_at_source_audit",
        "appended_rows": observed.height - original.height,
        "current_run_id": record["current_run_id"],
    }


def run_stage_case(
    repository: Path, workspace: Path, source: Path, lookup: Path, severity: str, seed: int,
    *, fault_id: str,
) -> dict:
    """Compare a development stage mutation with verified clean output."""
    if fault_id not in {"cleaning_fare_threshold", "aggregation_sum_to_mean"}:
        raise ValueError("Unsupported development stage case")
    execution = _prepare_execution(repository, workspace)
    runs = execution / "data/runs"
    clean = run(source, lookup, execution, contract_version="v2")
    if clean["publication"]["decision"] != "published":
        raise ValueError("The clean control did not publish")
    control = runs / clean["run_id"]
    verify_v2_run(execution, control, source, lookup)

    def table(directory: Path, name: str) -> pl.DataFrame:
        return pl.read_parquet(directory / f"{name}.parquet")

    clean_metrics = table(control, "daily_zone_metrics")
    enriched = table(control, "trip_enriched")
    tables = ("clean_trips", "diagnostic_join", "trip_enriched")
    if fault_id == "cleaning_fare_threshold":
        candidates = pl.read_parquet(source, columns=["fare_amount"])
        _, truth = prepare_case(fault_id, severity, seed, candidates)
        dropped = pl.col("source_row_ordinal").is_in(list(truth.selected_ordinals))
        selected = list(truth.selected_ordinals)
        expected_metrics = reference_daily_zone_metrics(enriched.filter(~dropped))
        removed_rows = table(control, "clean_trips").filter(dropped).height
    else:
        aggregation_input = enriched.rename({"fare_decimal": "fare_amount"})
        inputs, truth = prepare_case(fault_id, severity, seed, aggregation_input)
        # The existing hook uses the catalog ranker and records the selected keys.
        inputs.stage_hooks["aggregation"](aggregation_input)
        keys = set(truth.selected_keys)
        selected = sorted(f"{day}|{zone}" for day, zone in keys)
        sums_and_counts = {
            (day, zone): (count, revenue)
            for day, zone, count, revenue in clean_metrics.select(
                "pickup_date", "pickup_zone", "trip_count", "revenue"
            ).iter_rows()
        }
        means = []
        for key, (count, revenue) in sums_and_counts.items():
            means.append(
                (revenue / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if key in keys else revenue
            )
        expected_metrics = clean_metrics.with_columns(
            pl.Series("revenue", means, dtype=clean_metrics.schema["revenue"])
        )
        removed_rows = 0

    observed = run(source, lookup, execution, contract_version="v2",
                   _development_override={"stage": truth.stage, "selected": selected})
    candidate = runs / observed["run_id"]
    for name in tables:
        expected = table(control, name)
        if truth.stage == "cleaning":
            expected = expected.filter(~dropped)
        if not table(candidate, name).equals(expected):
            raise ValueError(f"Unexpected difference in {name}")
    if not table(candidate, "daily_zone_metrics").equals(expected_metrics):
        raise ValueError("Daily zone metrics differ from independently calculated fault effects")
    if observed["row_counts"]["clean_trips"] != clean["row_counts"]["clean_trips"] - removed_rows:
        raise ValueError("Reported retained rows do not match the evaluated fault")

    evaluator = workspace / "evaluator"
    evaluator.mkdir()
    (evaluator / "ground_truth.stage.json").write_text(
        json.dumps(asdict(truth), default=str, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "clean_run_id": clean["run_id"],
        "observed_run_id": observed["run_id"],
        "publication_decision": observed["publication"]["decision"],
        "removed_clean_rows": removed_rows,
        "revenue_delta": str(expected_metrics["revenue"].sum() - clean_metrics["revenue"].sum()),
    }


def _identity(args) -> dict:
    _, _, contract_hash = load_contract(args.repository, version="v2")
    code = {
        module.__name__: sha256(Path(module.__file__))
        for module in (development_ledger, fault_hooks, oracles, pipeline, worker)
    }
    code["runner"] = sha256(Path(__file__))
    code["verifier"] = sha256(Path(__file__).with_name("verify_v2_run.py"))
    code["report_schema"] = sha256(Path(pipeline.__file__).resolve().parents[2] / "schemas/report-v2.schema.json")
    return {
        "split": "development",
        "case": args.case,
        "severity": args.severity,
        "seed": args.seed,
        "source": {"name": args.source.name, "sha256": sha256(args.source)},
        "lookup_sha256": sha256(args.lookup),
        "contract_sha256": contract_hash,
        "catalog_sha256": sha256(fault_hooks.CATALOG_PATH),
        "code": code,
        "runtime": {"python": platform.python_version(), "platform": platform.system(),
                    "duckdb": duckdb.__version__, "polars": pl.__version__},
    }


def _execute_case(args) -> dict:
    def run_case(attempt: Path) -> dict:
        inputs = (args.repository.resolve(), attempt, args.source.resolve(),
                  args.lookup.resolve(), args.severity, args.seed)
        if args.case == "duplicate-ingestion":
            return run_ingestion_case(*inputs)
        if args.case == "duplicate-lookup":
            return run_lookup_case(*inputs)
        return run_stage_case(*inputs, fault_id=args.case.replace("-", "_"))

    workspace = args.workspace.resolve()
    if args.ledger is None:
        return run_case(workspace)
    identity = _identity(args)

    def run_verified(attempt: Path) -> dict:
        outcome = run_case(attempt)
        if _identity(args) != identity:
            raise ValueError("Development case identity changed during execution")
        return outcome

    return development_ledger.execute_or_resume(workspace, args.ledger.resolve(), identity, run_verified)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lookup", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, help="Append verified results and resume matching development cases")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--case", choices=tuple(DEVELOPMENT_CASES.values()))
    mode.add_argument("--matrix", action="store_true", help="Run the catalog's development matrix")
    parser.add_argument("--severity", choices=("low", "medium", "high"))
    parser.add_argument("--seed", type=int, choices=(11, 29, 47))
    parser.add_argument("--offset", type=int, help="Skip this many entries in the matrix plan")
    parser.add_argument("--limit", type=int, help="Run at most this many entries from the offset")
    parser.add_argument("--plan-only", action="store_true", help="Print the selected matrix entries")
    args = parser.parse_args()
    if args.matrix:
        if args.severity is not None or args.seed is not None:
            parser.error("--matrix uses the catalog severities and seeds")
        if args.source.name != "yellow_tripdata_2024-01.parquet":
            parser.error("--matrix requires the January 2024 benchmark source")
        if args.ledger is None and not args.plan_only:
            parser.error("--matrix execution requires --ledger")
        catalog = json.loads(fault_hooks.CATALOG_PATH.read_text(encoding="utf-8"))
        plan = development_plan(catalog)
        offset = args.offset if args.offset is not None else 0
        limit = args.limit if args.limit is not None else len(plan)
        if not 0 <= offset < len(plan) or limit <= 0:
            parser.error("--offset must identify a matrix entry and --limit must be positive")
        selected = plan[offset:offset + limit]
        result = {
            "planned_cases": len(plan),
            "offset": offset,
            "cases": selected if args.plan_only else [
                {**case, "result": _execute_case(SimpleNamespace(**(vars(args) | case)))}
                for case in selected
            ],
        }
    else:
        if args.plan_only or args.offset is not None or args.limit is not None:
            parser.error("--plan-only, --offset and --limit require --matrix")
        args.case = args.case or "duplicate-lookup"
        args.severity = args.severity or "low"
        args.seed = args.seed if args.seed is not None else 11
        result = _execute_case(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

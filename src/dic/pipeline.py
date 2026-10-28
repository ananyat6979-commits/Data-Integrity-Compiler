from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import jsonschema
import psutil
import yaml

from dic import __version__

REPORT_SCHEMA = "dic-report-v2"
ALLOWED_OPERATORS = {"not_null", "parseable_timestamp", ">=", ">"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _contract_file_sha256(path: Path) -> str:
    """Hash text with normalized newlines so Windows and Unix share one contract identity."""
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def canonical_hash(rows: list[tuple[Any, ...]]) -> str:
    def norm(v: Any) -> Any:
        if v is None:
            return {"null": True}
        if isinstance(v, Decimal):
            return {"decimal": format(v, "f")}
        if hasattr(v, "isoformat"):
            return {"datetime": v.isoformat()}
        return v

    encoded = json.dumps([[norm(x) for x in row] for row in rows], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def load_contract(root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    contract_dir = root / "contracts"
    if not contract_dir.is_dir():
        contract_dir = Path(__file__).parents[2] / "contracts"
    yaml_path = contract_dir / "pipeline.yaml"
    if not yaml_path.is_file():
        raise ValueError(f"Missing required pipeline contract: {yaml_path}")
    contract = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("Pipeline contract must be a YAML mapping")
    required_settings = {"contract_id", "contract_version", "schema_file", "cleaning", "join", "schema_policy"}
    missing = required_settings - contract.keys()
    if missing:
        raise ValueError(f"Pipeline contract is missing required settings: {sorted(missing)}")
    schema_path = (contract_dir / str(contract["schema_file"])).resolve()
    if schema_path.parent != contract_dir.resolve() or not schema_path.is_file():
        raise ValueError("Contract schema_file must reference an existing file in the contracts directory")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema.get("columns"), dict) or not isinstance(schema.get("required_columns"), list):
        raise ValueError("Referenced schema must define columns and required_columns")
    if not set(schema["required_columns"]) <= set(schema["columns"]):
        raise ValueError("Referenced schema required_columns must be declared in columns")
    if not isinstance(schema.get("compatible_additions"), list) or not isinstance(schema.get("schema_contract"), str):
        raise ValueError("Referenced schema must define schema_contract and compatible_additions")
    schema_policy_fields = {"added_optional_columns", "unrecognized_added_columns", "removed_optional_columns", "missing_required_columns"}
    policy = contract["schema_policy"]
    if not isinstance(policy, dict) or not schema_policy_fields <= policy.keys():
        raise ValueError("Contract schema_policy settings are incomplete")
    if any(value not in {"compatible", "review", "incompatible"} for value in policy.values()):
        raise ValueError("Schema policy values must be compatible, review, or incompatible")
    if not isinstance(contract["cleaning"], dict) or not {"version", "rules"} <= contract["cleaning"].keys():
        raise ValueError("Contract cleaning settings require version and rules")
    rules = contract["cleaning"].get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Contract cleaning.rules must be a non-empty list")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or not {"id", "column", "operator"} <= rule.keys():
            raise ValueError("Each cleaning rule requires id, column, and operator fields")
        if not isinstance(rule["id"], str) or not rule["id"] or rule["id"] in seen:
            raise ValueError("Cleaning rule IDs must be non-empty and unique")
        seen.add(rule["id"])
        if rule["operator"] not in ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported cleaning operator: {rule['operator']}")
        if rule["column"] not in schema["columns"]:
            raise ValueError(f"Cleaning rule {rule['id']} references unknown schema column {rule['column']}")
        if rule["operator"] in {">=", ">"} and not {"value", "cast_type"} <= rule.keys():
            raise ValueError(f"Cleaning rule {rule['id']} requires comparison value and cast_type")
        if rule["operator"] in {">=", ">"} and (isinstance(rule["value"], bool) or not isinstance(rule["value"], (int, float))):
            raise ValueError(f"Cleaning rule {rule['id']} comparison value must be numeric")
        if rule["operator"] in {">=", ">"} and rule["cast_type"] not in {"decimal_18_2", "double", "integer"}:
            raise ValueError(f"Cleaning rule {rule['id']} has an unsupported cast_type")
        if rule["operator"] not in {">=", ">"} and ({"value", "cast_type"} & rule.keys()):
            raise ValueError(f"Cleaning rule {rule['id']} does not accept comparison fields")
    join = contract["join"]
    if not isinstance(join, dict) or not {"key", "lookup_key", "cardinality", "cardinality_severity", "lookup_uniqueness_severity", "unmatched_policy", "key_non_null", "diagnostic_join"} <= join.keys():
        raise ValueError("Contract join settings are incomplete")
    if join["diagnostic_join"] != "left_preserves_all_input_rows":
        raise ValueError("join.diagnostic_join must be left_preserves_all_input_rows")
    if join["key"] != "PULocationID":
        raise ValueError("join.key must be PULocationID for the current pickup-zone aggregation")
    if join["key"] not in schema["columns"]:
        raise ValueError(f"Join key {join['key']} is not in the referenced schema")
    if join["cardinality"] not in {"many_to_one", "many_to_many"}:
        raise ValueError("join.cardinality must be many_to_one or many_to_many")
    if join["cardinality_severity"] not in {"block", "warn"} or join["lookup_uniqueness_severity"] not in {"block", "warn"}:
        raise ValueError("Join violation severities must be block or warn")
    if join["unmatched_policy"] not in {"exclude", "block"}:
        raise ValueError("join.unmatched_policy must be exclude or block")
    if not isinstance(join["key_non_null"], bool):
        raise ValueError("join.key_non_null must be a boolean")
    hash_payload = {"pipeline.yaml": _contract_file_sha256(yaml_path),
                    "schema": _contract_file_sha256(schema_path)}
    contract_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return contract, schema, contract_hash


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _compile_rule(rule: dict[str, Any]) -> tuple[str, list[Any]]:
    column = _quote_identifier(rule["column"])
    operator = rule["operator"]
    if operator == "not_null":
        return f"{column} IS NOT NULL", []
    if operator == "parseable_timestamp":
        return f"try_cast({column} AS TIMESTAMP) IS NOT NULL", []
    sql_types = {"decimal_18_2": "DECIMAL(18,2)", "double": "DOUBLE", "integer": "BIGINT"}
    return f"try_cast({column} AS {sql_types[rule['cast_type']]}) {operator} ?", [rule["value"]]


def classify_schema(schema: list[dict[str, str]], baseline: dict[str, Any] | None = None,
                    policy: dict[str, Any] | None = None) -> dict[str, Any]:
    if baseline is None:
        baseline_path = Path(__file__).parents[2] / "contracts" / "tlc-yellow-v1.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf8"))
    current = {item["name"]: item["type"] for item in schema}
    expected = baseline["columns"]
    required = set(baseline["required_columns"])
    missing_required = sorted(required - current.keys())
    added = sorted(current.keys() - expected.keys())
    removed = sorted(expected.keys() - current.keys())
    type_changes = sorted(name for name in current.keys() & expected.keys() if current[name] != expected[name])
    required_type_changes = sorted(name for name in type_changes if name in required)
    compatible_additions = set(baseline["compatible_additions"])
    unrecognized_additions = sorted(set(added) - compatible_additions)
    optional_removals = sorted(set(removed) - required)
    optional_type_changes = sorted(set(type_changes) - required)
    policy = policy or {"added_optional_columns": "compatible", "unrecognized_added_columns": "review",
                        "removed_optional_columns": "review", "missing_required_columns": "incompatible"}
    if missing_required or required_type_changes:
        classification = policy["missing_required_columns"]
    elif unrecognized_additions:
        classification = policy["unrecognized_added_columns"]
    elif optional_removals or optional_type_changes:
        classification = policy["removed_optional_columns"]
    elif added:
        classification = policy["added_optional_columns"]
    else:
        classification = "compatible"
    return {"schema_contract": baseline["schema_contract"], "baseline_month": baseline["baseline_month"],
            "schema_classification": classification, "missing_required_columns": missing_required,
            "added_columns": added, "removed_columns": removed, "type_changes": type_changes,
            "unrecognized_added_columns": unrecognized_additions}


def measure_peak_working_set() -> dict[str, Any]:
    system = platform.system()
    base = {"metric": "peak_working_set", "platform": platform.platform(),
            "scope": "dedicated_experiment_process"}
    try:
        if system == "Windows":
            value = getattr(psutil.Process().memory_info(), "peak_wset", None)
            if value is None:
                raise RuntimeError("psutil did not expose the Windows peak working set")
            return {**base, "status": "available", "value_bytes": int(value),
                    "method": "psutil.Process.memory_info().peak_wset", "native_units": "bytes",
                    "conversion": "none"}
        if system in {"Linux", "Darwin"}:
            import resource
            native = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            if system == "Linux":
                return {**base, "status": "available", "value_bytes": native * 1024,
                        "method": "resource.getrusage(RUSAGE_SELF).ru_maxrss", "native_units": "KiB",
                        "conversion": "KiB multiplied by 1024"}
            return {**base, "status": "available", "value_bytes": native,
                    "method": "resource.getrusage(RUSAGE_SELF).ru_maxrss", "native_units": "bytes",
                    "conversion": "none"}
        raise RuntimeError(f"No peak working-set method is implemented for {system}")
    except Exception as exc:
        return {**base, "status": "unavailable", "value_bytes": None,
                "method": "unsupported or unavailable platform counter", "native_units": None,
                "conversion": None, "reason": str(exc)}


def _monthly_source_url(month: str) -> str:
    return f"https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month}.parquet"


def acquire(raw_dir: Path, month: str) -> dict[str, Any]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Month must use YYYY-MM format")
    raw_dir.mkdir(parents=True, exist_ok=True)
    trip = raw_dir / f"yellow_tripdata_{month}.parquet"
    lookup = raw_dir / "taxi_zone_lookup.csv"
    if not trip.is_file() or not lookup.is_file():
        raise FileNotFoundError(f"Expected {trip} and {lookup}; download official TLC files first")
    con = connect()
    cols = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{trip.as_posix()}')").fetchall()
    schema = [{"name": c[0], "type": c[1]} for c in cols]
    contract, schema_contract, contract_hash = load_contract(Path(__file__).parents[2])
    schema_result = classify_schema(schema, schema_contract, contract["schema_policy"])
    con.close()
    manifest_path = raw_dir.parent / "source-manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf8")) if manifest_path.exists() else {}
    if "months" in old:
        months = old["months"]
    elif old.get("month"):
        months = {old["month"]: old}
    else:
        months = {}
    trip_hash, lookup_hash = sha256(trip), sha256(lookup)
    previous = months.get(month, {})
    previous_sources = {item.get("path"): item for item in previous.get("sources", [])}
    same_inputs = (previous_sources.get(trip.name, {}).get("sha256") == trip_hash and
                   previous_sources.get(lookup.name, {}).get("sha256") == lookup_hash)
    retrieved_at = previous.get("retrieved_at_utc") if same_inputs else datetime.now(timezone.utc).isoformat()
    entry = {"month": month, "retrieved_at_utc": retrieved_at,
             "sources": [{"path": trip.name, "url": _monthly_source_url(month), "sha256": trip_hash},
                         {"path": lookup.name, "url": "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv", "sha256": lookup_hash}],
             "trip_schema": schema, "contract_sha256": contract_hash,
             "contract_version": contract["contract_version"], **schema_result}
    months[month] = entry
    _write_json(manifest_path, {"manifest_version": "dic-source-manifest-v1", "months": months})
    return entry

def _read_lookup(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _normalized_lookup_key(row: dict[str, str], key_column: str) -> str | None:
    raw = (row.get(key_column) or "").strip()
    if not raw:
        return None
    try:
        return str(int(raw))
    except ValueError:
        return None


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def _rows(con: duckdb.DuckDBPyConnection, query: str) -> list[tuple[Any, ...]]:
    return con.execute(query).fetchall()


def run(trips_path: Path, lookup_path: Path, root: Path, fault_id: str | None = None,
       reference_lookup: Path | None = None, _test_failpoint: str | None = None) -> dict[str, Any]:
    args = {"trips_path": str(trips_path.resolve()), "lookup_path": str(lookup_path.resolve()),
            "root": str(root.resolve()), "fault_id": fault_id,
            "reference_lookup": str(reference_lookup.resolve()) if reference_lookup else None,
            "test_failpoint": _test_failpoint}
    completed = subprocess.run([sys.executable, "-m", "dic.worker"], input=json.dumps(args),
                               text=True, capture_output=True, cwd=root)
    if completed.returncode:
        raise RuntimeError(f"Isolated experiment failed: {completed.stderr.strip() or completed.stdout.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Experiment subprocess returned invalid JSON: {completed.stdout[-1000:]}") from exc


def run_in_process(trips_path: Path, lookup_path: Path, root: Path, fault_id: str | None = None,
                   reference_lookup: Path | None = None, test_failpoint: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    contract, schema_contract, contract_hash = load_contract(root)
    contract_id = contract["contract_id"]
    run_id = uuid.uuid4().hex
    runs = root / "data" / "runs"
    stage = runs / run_id
    stage.mkdir(parents=True, exist_ok=False)
    con = connect()
    trips_sql = trips_path.resolve().as_posix().replace("'", "''")
    input_hash = sha256(trips_path)
    con.execute(f"CREATE VIEW raw AS SELECT *, '{input_hash}'::VARCHAR AS source_sha256, file_row_number AS source_row_ordinal FROM read_parquet('{trips_sql}', file_row_number=true)")
    cols = {x[0] for x in con.execute("DESCRIBE raw").fetchall()}
    missing = set(schema_contract["required_columns"]) - cols
    if missing:
        raise ValueError(f"Incompatible TLC schema; missing required columns: {sorted(missing)}")
    join_key = contract["join"]["key"]
    if join_key not in cols:
        raise ValueError(f"Configured join key {join_key} is absent from the input schema")
    predicates, params = zip(*[_compile_rule(rule) for rule in contract["cleaning"]["rules"]])
    failed_case_parts = []
    case_params: list[Any] = []
    for rule, (predicate, rule_params) in zip(contract["cleaning"]["rules"], zip(predicates, params)):
        failed_case_parts.append(f"WHEN NOT ({predicate}) THEN ?")
        case_params.extend(rule_params)
        case_params.append(rule["id"])
    first_failure_sql = "CASE " + " ".join(failed_case_parts) + " ELSE NULL END"
    pickup_column = _quote_identifier("tpep_pickup_datetime")
    fare_column = _quote_identifier("fare_amount")
    zone_column = _quote_identifier("PULocationID")
    join_column = _quote_identifier(join_key)
    clean_select = f"SELECT *, CAST({zone_column} AS INTEGER) AS pickup_zone, CAST({join_column} AS INTEGER) AS join_key, CAST(date_trunc('day', try_cast({pickup_column} AS TIMESTAMP)) AS DATE) AS pickup_date, CAST({fare_column} AS DECIMAL(18,2)) AS fare_decimal FROM raw"
    con.execute(f"CREATE TEMP TABLE assessed AS SELECT *, {first_failure_sql} AS first_failed_rule FROM ({clean_select}) clean_source", case_params)
    con.execute("CREATE TEMP VIEW clean AS SELECT * FROM assessed WHERE first_failed_rule IS NULL")
    rejected_by_rule = {rule_id: count for rule_id, count in con.execute("SELECT first_failed_rule, count(*) FROM assessed WHERE first_failed_rule IS NOT NULL GROUP BY 1").fetchall()}
    rejected_by_rule = {rule["id"]: int(rejected_by_rule.get(rule["id"], 0)) for rule in contract["cleaning"]["rules"]}
    clean_n = con.execute("SELECT count(*) FROM clean").fetchone()[0]
    raw_n = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    if raw_n - clean_n != sum(rejected_by_rule.values()):
        raise RuntimeError("Per-rule first-failure counts do not reconcile to total rejected rows")
    validation_started = time.perf_counter()
    lookup_rows = _read_lookup(lookup_path)
    reference_lookup = reference_lookup or lookup_path
    reference_rows = _read_lookup(reference_lookup)
    # Preserve original values/attributes; only normalize the join key for comparison.
    key_counts: dict[str, int] = {}
    null_keys = 0
    for row in lookup_rows:
        key = _normalized_lookup_key(row, contract["join"]["lookup_key"])
        if key is None:
            null_keys += 1
        else:
            key_counts[key] = key_counts.get(key, 0) + 1
    duplicates = {k: n for k, n in key_counts.items() if n > 1}
    reference_counts: dict[str, int] = {}
    reference_nulls = 0
    for row in reference_rows:
        key = _normalized_lookup_key(row, contract["join"]["lookup_key"])
        if key is None:
            reference_nulls += 1
        else:
            reference_counts[key] = reference_counts.get(key, 0) + 1
    preexisting_duplicates = {k: n for k, n in reference_counts.items() if n > 1}
    lookup_sql = lookup_path.resolve().as_posix().replace("'", "''")
    lookup_key = contract["join"]["lookup_key"]
    if lookup_key != "LocationID":
        lookup_columns = {row[0] for row in con.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{lookup_sql}', all_varchar=true)").fetchall()}
        if lookup_key not in lookup_columns:
            raise ValueError(f"Configured lookup key {lookup_key} is absent from lookup file")
    con.execute(f"CREATE TABLE lookup AS SELECT try_cast({_quote_identifier(lookup_key)} AS INTEGER) AS lookup_zone, * FROM read_csv_auto('{lookup_sql}', all_varchar=true)")
    # Materialize diagnostic join: left rows must equal clean input despite duplicate fanout/unmatched keys.
    con.execute("""CREATE TABLE diagnostic AS SELECT c.source_sha256, c.source_row_ordinal, c.pickup_zone, c.pickup_date,
      c.fare_decimal, l.lookup_zone AS matched_key, l.Zone AS zone_name
      FROM clean c LEFT JOIN lookup l ON c.join_key=l.lookup_zone""")
    diagnostic_n = con.execute("SELECT count(*) FROM diagnostic").fetchone()[0]
    matched = con.execute("SELECT count(*) FROM diagnostic WHERE matched_key IS NOT NULL").fetchone()[0]
    unmatched = con.execute("SELECT count(*) FROM diagnostic WHERE matched_key IS NULL").fetchone()[0]
    multi = con.execute("SELECT count(*) FROM (SELECT source_row_ordinal FROM diagnostic GROUP BY 1 HAVING count(*) > 1)").fetchone()[0]
    input_counts_by_key = {str(k): n for k, n in con.execute("SELECT join_key, count(*) FROM clean GROUP BY 1").fetchall()}
    injected_like_duplicates = {k: n for k, n in duplicates.items() if reference_counts.get(k) == 1}
    expected_extra_rows = sum(input_counts_by_key.get(k, 0) * (n - 1) for k, n in injected_like_duplicates.items())
    join_settings = contract["join"]
    null_join_rows = con.execute("SELECT count(*) FROM clean WHERE join_key IS NULL").fetchone()[0]
    uniqueness_failed = bool(null_keys or duplicates or reference_nulls or preexisting_duplicates)
    cardinality_failed = join_settings["cardinality"] == "many_to_one" and multi > 0
    expected_diagnostic_n = clean_n if join_settings["cardinality"] == "many_to_one" else sum(
        count * max(key_counts.get(key, 0), 1) for key, count in input_counts_by_key.items())
    conservation_failed = diagnostic_n != expected_diagnostic_n
    unmatched_failed = unmatched > 0 and join_settings["unmatched_policy"] == "block"
    blocking_failures = [
        uniqueness_failed and join_settings["lookup_uniqueness_severity"] == "block",
        cardinality_failed and join_settings["cardinality_severity"] == "block",
        conservation_failed and join_settings["cardinality_severity"] == "block",
        unmatched_failed,
        bool(null_join_rows) and join_settings["key_non_null"],
    ]
    contract_failed = any(blocking_failures)
    deltas = _aggregate_deltas(con, duplicates)
    validation_seconds = time.perf_counter() - validation_started
    current_path = root / "data" / "published" / "CURRENT"
    pointer_before = json.loads(current_path.read_text(encoding="utf8")).get("run_id") if current_path.exists() else None
    con.execute("""CREATE TABLE trip_enriched AS SELECT * FROM diagnostic WHERE matched_key IS NOT NULL
      AND NOT ?""", [contract_failed])
    # If blocked, keep a candidate for evidence only; no promotion occurs below.
    con.execute("""CREATE TABLE daily_zone_metrics AS SELECT pickup_date, pickup_zone,
      count(*)::BIGINT AS trip_count, sum(fare_decimal)::DECIMAL(18,2) AS revenue,
      avg(fare_decimal)::DECIMAL(18,6) AS average_fare
      FROM diagnostic WHERE matched_key IS NOT NULL GROUP BY 1,2 ORDER BY 1,2""")
    # Stream stage outputs to Parquet inside DuckDB (no Python-side row materialization) and compute
    # an order-independent logical hash per table: row count + sum of per-row value hashes.
    # Values (decimals, nulls, dates) are hashed as values, never as file bytes.
    outputs: dict[str, str] = {}
    materialization_started = time.perf_counter()
    for name, order in [("clean_trips", "source_row_ordinal"), ("diagnostic_join", "source_row_ordinal, matched_key"),
                        ("trip_enriched", "source_row_ordinal, matched_key"), ("daily_zone_metrics", "pickup_date, pickup_zone")]:
        src = {"clean_trips": "(SELECT source_sha256, source_row_ordinal, pickup_zone, pickup_date, fare_decimal FROM clean)",
               "diagnostic_join": "diagnostic", "trip_enriched": "trip_enriched", "daily_zone_metrics": "daily_zone_metrics"}[name]
        target = (stage / f"{name}.parquet").as_posix().replace("'", "''")
        con.execute(f"COPY (SELECT * FROM {src} ORDER BY {order}) TO '{target}' (FORMAT PARQUET)")
        if test_failpoint == "after_first_materialization" and name == "clean_trips":
            raise RuntimeError("injected failure after first output materialization")
        n, h = con.execute(f"SELECT count(*), coalesce(sum(hash(t)::HUGEINT), 0) FROM {src} t").fetchone()
        outputs[name] = f"rows={n};logical_hash={h}"
    output_materialization_seconds = time.perf_counter() - materialization_started
    counts = {"raw_trips": raw_n, "clean_trips": clean_n, "diagnostic_left_join": diagnostic_n,
              "matched_rows": matched, "unmatched_rows": unmatched, "multiple_match_input_rows": multi}
    report = {"schema_version": REPORT_SCHEMA, "run_id": run_id, "fault_id": fault_id,
      "source_artifacts": {"trips_sha256": input_hash, "lookup_sha256": sha256(lookup_path),
                           "reference_lookup_sha256": sha256(reference_lookup),
                           "contract_sha256": contract_hash},
      "contract_id": contract_id, "contract_version": contract["contract_version"],
      "contract_hash": contract_hash,
      "outcome": "blocked" if contract_failed else "passed",
      "cleaning": {"rejection_attribution": "first_failing_rule", "total_rejected_rows": raw_n-clean_n,
                   "rejected_rows_by_rule": rejected_by_rule},
      "checks": [{"id":"lookup_non_null_unique","severity":join_settings["lookup_uniqueness_severity"],"passed":not uniqueness_failed,"null_key_rows":null_keys,"duplicate_keys":duplicates},
                 {"id":"reference_lookup_non_null_unique","severity":join_settings["lookup_uniqueness_severity"],"passed":not bool(reference_nulls or preexisting_duplicates),"null_key_rows":reference_nulls,"duplicate_keys":preexisting_duplicates},
                 {"id":"left_join_row_count_conservation","severity":join_settings["cardinality_severity"],"passed":not conservation_failed,"input_rows":clean_n,"expected_rows":expected_diagnostic_n,"observed_rows":diagnostic_n},
                 {"id":"join_cardinality","severity":join_settings["cardinality_severity"],"passed":not cardinality_failed,"policy":join_settings["cardinality"],"multiple_match_input_rows":multi},
                 {"id":"join_key_non_null","severity":"block" if join_settings["key_non_null"] else "warn","passed":not bool(null_join_rows),"null_key_rows":null_join_rows,"key":join_key},
                 {"id":"unmatched_lookup_keys","severity":"block" if join_settings["unmatched_policy"] == "block" else "info","passed":not unmatched_failed,"policy":join_settings["unmatched_policy"],"unmatched_rows":unmatched}],
      "evidence":{"matched_rows":matched,"unmatched_rows":unmatched,"multiple_match_input_rows":multi,
                  "affected_key": next(iter(injected_like_duplicates), None),
                  "key_multiplicities":{"lookup": duplicates, "original_reference": reference_counts},
                  "affected_input_rows": sum(input_counts_by_key.get(k, 0) for k in injected_like_duplicates),
                  "preexisting_source_violations":{"null_key_rows":reference_nulls,"duplicate_keys":preexisting_duplicates},
                  "earliest_divergence":"trip_enriched" if contract_failed else None,
                  "suspected_transformation":"pickup_zone_lookup_join" if contract_failed else None,
                  "attribution":"inferred from join contract and cardinality evidence" if contract_failed else "none",
                  "diagnostic_limitations":["single batch run; no temporal divergence tracking", "join fault localization is not a root-cause accuracy benchmark"]},
      "expected_observed":{"expected_clean_output_rows":clean_n,"observed_diagnostic_output_rows":diagnostic_n,
                            "expected_row_inflation_from_new_duplicate_keys":expected_extra_rows,
                            "observed_row_inflation":diagnostic_n-clean_n,"row_inflation":diagnostic_n-clean_n,
                            "formula":"sum(N_k * (lookup_multiplicity - reference_multiplicity))"},
      "downstream_aggregate_deltas": deltas, "publication":{"decision":"blocked" if contract_failed else "published","pointer_before":pointer_before,"pointer_after":pointer_before if contract_failed else run_id},
      "runtimes_seconds":{"total_pipeline_seconds":round(time.perf_counter()-started,6),
                           "validation_seconds":round(validation_seconds,6),
                           "output_materialization_seconds":round(output_materialization_seconds,6),
                           "publication_seconds":0.0},
      "peak_memory": measure_peak_working_set(),
      "versions":{"compiler":__version__,"python":platform.python_version(),"duckdb":duckdb.__version__,"contract":str(contract["contract_version"]),"cleaning":str(contract["cleaning"]["version"])},
      "row_counts":{**counts,"enriched_candidate_rows":con.execute("SELECT count(*) FROM trip_enriched").fetchone()[0]},
      "logical_output_hashes":outputs}
    validate_report(report)
    manifest = {"manifest_version": "dic-manifest-v1", "run_id": run_id,
                "inputs": {"trips_sha256": input_hash, "lookup_sha256": sha256(lookup_path),
                           "reference_lookup_sha256": sha256(reference_lookup)},
                "versions": report["versions"], "contract_id": contract_id,
                "contract_version": contract["contract_version"], "contract_sha256": contract_hash,
                "configuration_version": "pipeline-v2", "row_counts": counts,
                "logical_output_hashes": outputs}
    _write_json(stage / "manifest.json", manifest)
    _write_json(stage / "report.json", report)
    if not contract_failed:
        if test_failpoint == "invalid_publication_report":
            report["schema_version"] = "invalid-report-version"
        _publish(stage, root / "data" / "published", run_id, report)
    con.close()
    return report


def validate_report(report: dict[str, Any]) -> None:
    schema_path = Path(__file__).parents[2] / "schemas" / "report-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(report, schema)


def collect_orphaned_staging(root: Path, older_than_hours: float = 24, delete: bool = False) -> dict[str, Any]:
    """List or remove old, incomplete run directories; completed evidence is never collected."""
    root = root.resolve()
    if not (root / ".git").exists() or not (root / "pyproject.toml").is_file():
        raise ValueError("Garbage collection requires the repository root containing .git and pyproject.toml")
    if older_than_hours <= 0:
        raise ValueError("older_than_hours must be positive")
    runs = root / "data" / "runs"
    published = root / "data" / "published"
    if runs.is_symlink() or published.is_symlink():
        raise ValueError("Garbage collection refuses symlinked run or publication directories")
    def read_current() -> str | None:
        path = published / "CURRENT"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("run_id")
        except (OSError, json.JSONDecodeError):
            return None

    current_id = read_current()
    published_ids = {p.name for p in published.iterdir() if p.is_dir()} if published.is_dir() else set()
    cutoff = time.time() - older_than_hours * 3600
    candidates: list[Path] = []
    if runs.is_dir():
        for path in runs.iterdir():
            if (path.is_symlink() or not path.is_dir() or
                    not re.fullmatch(r"[0-9a-f]{32}", path.name) or
                    path.name == current_id or path.name in published_ids):
                continue
            if (path / "report.json").exists() or (path / "manifest.json").exists():
                continue
            try:
                if path.stat().st_mtime <= cutoff:
                    candidates.append(path)
            except FileNotFoundError:
                continue

    required_tables = {"clean_trips.parquet", "trip_enriched.parquet", "daily_zone_metrics.parquet"}
    if published.is_dir():
        for path in published.iterdir():
            if path.is_symlink():
                continue
            if path.is_dir() and re.fullmatch(r"[0-9a-f]{32}", path.name) and path.name != current_id:
                complete = ((path / "manifest.json").is_file() and (path / "report.json").is_file()
                            and required_tables <= {child.name for child in path.iterdir() if child.is_file()})
                if not complete:
                    try:
                        if path.stat().st_mtime <= cutoff:
                            candidates.append(path)
                    except FileNotFoundError:
                        continue
            elif path.is_file() and (path.name == "CURRENT.tmp" or
                                     re.fullmatch(r"CURRENT\.[0-9a-f]{32}\.tmp", path.name)):
                try:
                    if path.stat().st_mtime <= cutoff:
                        candidates.append(path)
                except FileNotFoundError:
                    continue

    removed: list[str] = []
    if delete:
        for path in candidates:
            # Recheck selection and references immediately before deletion.
            current_id = read_current()
            published_ids = {p.name for p in published.iterdir() if p.is_dir()} if published.is_dir() else set()
            try:
                if path.stat().st_mtime > cutoff:
                    continue
            except FileNotFoundError:
                continue
            relative = path.relative_to(root)
            if relative.parent == Path("data/runs"):
                if (path.is_symlink() or not re.fullmatch(r"[0-9a-f]{32}", path.name) or
                        path.name == current_id or path.name in published_ids or not path.is_dir()):
                    continue
                if (path / "report.json").exists() or (path / "manifest.json").exists():
                    continue
                shutil.rmtree(path)
            elif relative.parent == Path("data/published") and path.is_dir():
                if (path.is_symlink() or not re.fullmatch(r"[0-9a-f]{32}", path.name) or
                        path.name == current_id):
                    continue
                complete = ((path / "manifest.json").is_file() and (path / "report.json").is_file()
                            and required_tables <= {child.name for child in path.iterdir() if child.is_file()})
                if complete:
                    continue
                shutil.rmtree(path)
            elif relative.parent == Path("data/published") and path.is_file():
                if path.name != "CURRENT.tmp" and not re.fullmatch(r"CURRENT\.[0-9a-f]{32}\.tmp", path.name):
                    continue
                shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
            else:
                continue
            removed.append(relative.as_posix())
    return {"mode": "delete" if delete else "dry_run",
            "older_than_hours": older_than_hours,
            "candidates": [p.relative_to(root).as_posix() for p in candidates], "removed": removed}


def _publish(stage: Path, published: Path, run_id: str, report: dict[str, Any], failpoint: str | None = None) -> None:
    try:
        _publish_impl(stage, published, run_id, report, failpoint)
    except Exception:
        current = published / "CURRENT"
        selected = None
        if current.is_file():
            try:
                selected = json.loads(current.read_text(encoding="utf-8")).get("run_id")
            except (OSError, json.JSONDecodeError):
                pass
        if selected != run_id:
            shutil.rmtree(published / run_id, ignore_errors=True)
            (published / f"CURRENT.{run_id}.tmp").unlink(missing_ok=True)
            (published / "CURRENT.tmp").unlink(missing_ok=True)
        raise


def _publish_impl(stage: Path, published: Path, run_id: str, report: dict[str, Any], failpoint: str | None = None) -> None:
    publication_started = time.perf_counter()
    published.mkdir(parents=True, exist_ok=True)
    version = published / run_id
    shutil.copytree(stage, version)
    manifest = {"manifest_version": "dic-publication-v1", "run_id": run_id,
                "tables": ["clean_trips", "trip_enriched", "daily_zone_metrics"],
                "hashes": report["logical_output_hashes"], "inputs": report.get("source_artifacts", {}),
                "versions": report.get("versions", {}), "contract_id": report.get("contract_id"),
                "contract_version": report.get("contract_version"), "contract_sha256": report.get("contract_hash"),
                "configuration_version": "pipeline-v2"}
    candidate = published / f"CURRENT.{run_id}.tmp"
    report["runtimes_seconds"]["publication_seconds"] = round(time.perf_counter() - publication_started, 6)
    report["runtimes_seconds"]["total_pipeline_seconds"] = round(report["runtimes_seconds"]["total_pipeline_seconds"] + report["runtimes_seconds"]["publication_seconds"], 6)
    manifest["runtimes_seconds"] = report["runtimes_seconds"]
    validate_report(report)
    _write_json(stage / "report.json", report)
    _write_json(version / "report.json", report)
    stage_manifest_path = stage / "manifest.json"
    version_manifest_path = version / "manifest.json"
    _write_json(stage_manifest_path, {**json.loads(stage_manifest_path.read_text(encoding="utf8")), "runtimes_seconds": report["runtimes_seconds"]})
    _write_json(version_manifest_path, {**json.loads(version_manifest_path.read_text(encoding="utf8")), "runtimes_seconds": report["runtimes_seconds"]})
    _write_json(candidate, manifest)
    if failpoint == "before_pointer_swap":
        raise RuntimeError("simulated interruption before atomic manifest-pointer swap")
    current_tmp = published / "CURRENT.tmp"
    shutil.copyfile(candidate, current_tmp)
    os.replace(current_tmp, published / "CURRENT")
    candidate.unlink(missing_ok=True)


def _aggregate_deltas(con: duckdb.DuckDBPyConnection, duplicate_keys: dict[str, int]) -> list[dict[str, Any]]:
    """Compare observed fanout to a one-row-per-key reference without reading injector ground truth."""
    if not duplicate_keys:
        return []
    rows = con.execute("""WITH one_lookup AS (
        SELECT *, row_number() OVER (PARTITION BY lookup_zone ORDER BY Zone, Borough) AS rn FROM lookup
      ), clean_metrics AS (
        SELECT c.pickup_date, c.pickup_zone, count(*)::BIGINT AS trips,
          sum(c.fare_decimal)::DECIMAL(18,2) AS revenue,
          avg(c.fare_decimal)::DECIMAL(18,6) AS avg_fare
        FROM clean c JOIN one_lookup l ON c.pickup_zone=l.lookup_zone AND l.rn=1
        GROUP BY 1,2
      ), observed_metrics AS (
        SELECT pickup_date, pickup_zone, count(*)::BIGINT AS trips,
          sum(fare_decimal)::DECIMAL(18,2) AS revenue,
          avg(fare_decimal)::DECIMAL(18,6) AS avg_fare
        FROM diagnostic WHERE matched_key IS NOT NULL GROUP BY 1,2
      )
      SELECT coalesce(o.pickup_date,c.pickup_date), coalesce(o.pickup_zone,c.pickup_zone),
        coalesce(c.trips,0), coalesce(o.trips,0), coalesce(c.revenue,0), coalesce(o.revenue,0),
        coalesce(c.avg_fare,0), coalesce(o.avg_fare,0)
      FROM clean_metrics c FULL OUTER JOIN observed_metrics o USING(pickup_date,pickup_zone)
      WHERE c.trips IS DISTINCT FROM o.trips OR c.revenue IS DISTINCT FROM o.revenue
        OR c.avg_fare IS DISTINCT FROM o.avg_fare ORDER BY 1,2""").fetchall()
    return [{"pickup_date":str(r[0]),"pickup_zone":r[1],"expected_trip_count":r[2],"observed_trip_count":r[3],
             "trip_count_delta":r[3]-r[2],"expected_revenue":str(r[4]),"observed_revenue":str(r[5]),
             "revenue_delta":str(r[5]-r[4]),"expected_average_fare":str(r[6]),"observed_average_fare":str(r[7]),
             "average_fare_unchanged":r[6]==r[7]} for r in rows]


def inject_m1(lookup_path: Path, out_dir: Path, key: str) -> dict[str, Any]:
    rows = _read_lookup(lookup_path)
    matches = [r for r in rows if (r.get("LocationID") or "").strip() == str(key)]
    if len(matches) != 1:
        raise ValueError(f"Selected key must have exactly one original lookup row; found {len(matches)}")
    fault_id = "m1-" + uuid.uuid4().hex
    out_dir = out_dir / fault_id
    out_dir.mkdir(parents=True, exist_ok=False)
    corrupted = out_dir / "lookup_corrupted.csv"
    with corrupted.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows + [matches[0].copy()])
    truth = {"fault_id": fault_id, "fault_type":"exact_duplicate_lookup_row", "target_transformation":"pickup_zone_lookup_join",
             "key": str(key), "original_multiplicity":1,"corrupted_multiplicity":2,"extra_copies":1}
    _write_json(out_dir / "ground_truth.private.json", truth)
    return {"fault_id": fault_id, "lookup": corrupted, "ground_truth": out_dir / "ground_truth.private.json"}


def evaluate(report_path: Path, truth_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf8"))
    truth = json.loads(truth_path.read_text(encoding="utf8"))
    # Called only by evaluation; compiler run() accepts neither truth path nor truth object.
    evidence = report["evidence"]
    return {"fault_id_matches": report.get("fault_id") == truth["fault_id"],
            "key_matches": evidence.get("affected_key") == truth["key"],
            "invariant_detected": any(c["id"] == "lookup_non_null_unique" and not c["passed"] for c in report["checks"])}

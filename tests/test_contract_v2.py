from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import duckdb

import dic.pipeline as pipeline
from dic.pipeline import build_v2_source_provenance, load_contract, run


ROOT = Path(__file__).parents[1]
V1_HASH = "947e696d07ed07482a9d542febf5a345693e5a1a29b4db5875dc0fbdeca3c953"


@pytest.fixture
def v2_root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    audit = tmp_path / "experiments/m2a/audit"
    audit.mkdir(parents=True)
    shutil.copy2(ROOT / "experiments/m2a/audit/schema_audit_2022-01_2025-12.json", audit)
    return tmp_path


def test_contract_version_defaults_to_pinned_v1_and_rejects_unknown_version():
    assert load_contract(ROOT)[2] == V1_HASH
    with pytest.raises(ValueError, match="Unsupported contract version"):
        load_contract(ROOT, version="v3")


def test_v2_contract_loads_and_hash_covers_yaml_and_schema(v2_root: Path):
    _, schema, original_hash = load_contract(v2_root, version="v2")
    assert schema["schema_contract"] == "tlc-yellow-v2-semantic"

    yaml_path = v2_root / "contracts/v2/pipeline.yaml"
    yaml_original = yaml_path.read_bytes()
    yaml_path.write_bytes(yaml_original + b"\n# hash input change\n")
    assert load_contract(v2_root, version="v2")[2] != original_hash
    yaml_path.write_bytes(yaml_original)

    schema_path = v2_root / "contracts/v2/tlc-yellow-v2.json"
    schema_original = schema_path.read_bytes()
    schema_doc = json.loads(schema_original)
    schema_doc["schema_contract"] += "-revision"
    schema_path.write_text(json.dumps(schema_doc), encoding="utf-8")
    assert load_contract(v2_root, version="v2")[2] != original_hash


def test_v2_contract_rejects_a_missing_or_modified_pinned_audit(v2_root: Path):
    audit_path = v2_root / "experiments/m2a/audit/schema_audit_2022-01_2025-12.json"
    audit_bytes = audit_path.read_bytes()
    audit_path.write_bytes(audit_bytes + b" ")
    with pytest.raises(ValueError, match="audit SHA-256"):
        load_contract(v2_root, version="v2")
    audit_path.unlink()
    with pytest.raises(ValueError, match="existing file inside the repository"):
        load_contract(v2_root, version="v2")


def test_v2_audit_pin_is_stable_across_line_endings(v2_root: Path):
    audit_path = v2_root / "experiments/m2a/audit/schema_audit_2022-01_2025-12.json"
    original = audit_path.read_bytes()
    lf = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    audit_path.write_bytes(lf)
    _, _, lf_contract_hash = load_contract(v2_root, version="v2")
    audit_path.write_bytes(lf.replace(b"\n", b"\r\n"))
    _, _, crlf_contract_hash = load_contract(v2_root, version="v2")
    assert crlf_contract_hash == lf_contract_hash


def test_v2_audit_hash_method_must_be_explicit_and_supported(v2_root: Path):
    yaml_path = v2_root / "contracts/v2/pipeline.yaml"
    original = yaml_path.read_text(encoding="utf-8")
    yaml_path.write_text(original.replace("sha256_method: utf8_lf_normalized", "sha256_method: raw_bytes"))
    with pytest.raises(ValueError, match="sha256_method is unsupported"):
        load_contract(v2_root, version="v2")
    yaml_path.write_text(original.replace("  sha256_method: utf8_lf_normalized\n", ""))
    with pytest.raises(ValueError, match="source_audit settings are incomplete"):
        load_contract(v2_root, version="v2")


@pytest.mark.parametrize(
    ("field", "replacement", "error"),
    [
        ("Airport_fee: [DOUBLE]", "Airport_fee: [VARCHAR]", "no physical type mapping"),
        ("airport_fee: Airport_fee", "airport_fee: missing_column", "does not map source column"),
    ],
)
def test_v2_contract_rejects_incomplete_or_invalid_normalization(
    v2_root: Path, field: str, replacement: str, error: str
):
    yaml_path = v2_root / "contracts/v2/pipeline.yaml"
    original = yaml_path.read_text(encoding="utf-8")
    yaml_path.write_text(original.replace(field, replacement), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        load_contract(v2_root, version="v2")


def test_v2_source_provenance_captures_physical_and_semantic_schemas(
    v2_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audit = json.loads(
        (v2_root / "experiments/m2a/audit/schema_audit_2022-01_2025-12.json").read_text()
    )
    entry = next(item for item in audit["months"] if item["month"] == "2022-01")
    cohort = next(item for item in audit["cohorts"] if item["cohort_id"] == entry["cohort_id"])
    source_path = tmp_path / entry["file"]
    source_path.write_bytes(b"fixture placeholder for audited parquet")
    resolved_source_path = source_path.resolve()
    real_sha256 = pipeline.sha256
    monkeypatch.setattr(
        pipeline,
        "sha256",
        lambda path: entry["sha256"] if Path(path) == resolved_source_path else real_sha256(path),
    )
    real_stat = Path.stat

    def stat_with_audited_size(path: Path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == resolved_source_path:
            return SimpleNamespace(st_size=entry["bytes"], st_mode=result.st_mode)
        return result

    monkeypatch.setattr(Path, "stat", stat_with_audited_size)
    provenance = build_v2_source_provenance(
        v2_root, source_path, "2022-01", cohort["columns"], entry["rows"]
    )
    assert provenance["source_month"] == "2022-01"
    assert provenance["source_rows"] == entry["rows"]
    assert provenance["audit"]["cohort_id"] == "C1"
    assert provenance["original_columns"] == cohort["columns"]
    airport = next(item for item in provenance["column_mapping"] if item["source_name"] == "airport_fee")
    assert airport["semantic_name"] == "Airport_fee"
    assert airport["source_type"] == airport["semantic_type"] == "DOUBLE"
    assert "D:\\" not in json.dumps(provenance)


def test_v2_source_provenance_rejects_mismatched_row_count(
    v2_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    audit = json.loads(
        (v2_root / "experiments/m2a/audit/schema_audit_2022-01_2025-12.json").read_text()
    )
    entry = next(item for item in audit["months"] if item["month"] == "2022-01")
    cohort = next(item for item in audit["cohorts"] if item["cohort_id"] == entry["cohort_id"])
    source_path = tmp_path / entry["file"]
    source_path.write_bytes(b"fixture placeholder for audited parquet")
    resolved_source_path = source_path.resolve()
    real_sha256 = pipeline.sha256
    monkeypatch.setattr(
        pipeline,
        "sha256",
        lambda path: entry["sha256"] if Path(path) == resolved_source_path else real_sha256(path),
    )
    real_stat = Path.stat

    def stat_with_audited_size(path: Path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == resolved_source_path:
            return SimpleNamespace(st_size=entry["bytes"], st_mode=result.st_mode)
        return result

    monkeypatch.setattr(Path, "stat", stat_with_audited_size)
    with pytest.raises(ValueError, match="Source bytes, row count, or physical schema differ"):
        build_v2_source_provenance(
            v2_root, source_path, "2022-01", cohort["columns"], entry["rows"] - 1
        )


def test_v2_subprocess_run_rejects_far_out_rows_without_blocking(tmp_path: Path):
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    audit = tmp_path / "experiments/m2a/audit"
    audit.mkdir(parents=True)
    shutil.copy2(ROOT / "experiments/m2a/audit/schema_audit_2022-01_2025-12.json", audit)
    trips = tmp_path / "yellow_tripdata_2023-01.parquet"
    audit_path = audit / "schema_audit_2022-01_2025-12.json"
    audit_doc = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_record = next(item for item in audit_doc["months"] if item["month"] == "2023-01")
    cohort = next(item for item in audit_doc["cohorts"] if item["cohort_id"] == audit_record["cohort_id"])
    fixture_rows = [
        {"tpep_pickup_datetime": "2022-12-31 23:59:00", "tpep_dropoff_datetime": "2023-01-01 00:10:00",
         "PULocationID": 1, "DOLocationID": 2, "fare_amount": 10.0, "trip_distance": 2.0},
        {"tpep_pickup_datetime": "2023-01-31 23:59:00", "tpep_dropoff_datetime": "2023-02-01 00:10:00",
         "PULocationID": 1, "DOLocationID": 2, "fare_amount": 20.0, "trip_distance": 3.0},
        {"tpep_pickup_datetime": "2023-02-01 23:59:00", "tpep_dropoff_datetime": "2023-02-02 00:10:00",
         "PULocationID": 2, "DOLocationID": 1, "fare_amount": 5.0, "trip_distance": 1.0},
        {"tpep_pickup_datetime": "2023-02-02 00:00:00", "tpep_dropoff_datetime": "2023-02-02 00:15:00",
         "PULocationID": 2, "DOLocationID": 1, "fare_amount": 8.0, "trip_distance": 1.0},
    ]
    overrides = {
        "VendorID": 1, "passenger_count": 1.0, "RatecodeID": 1.0,
        "store_and_fwd_flag": "N", "payment_type": 1, "extra": 0.0, "mta_tax": 0.0,
        "tip_amount": 0.0, "tolls_amount": 0.0, "improvement_surcharge": 0.0,
        "total_amount": 0.0, "congestion_surcharge": 0.0, "airport_fee": 0.0,
    }

    def sql_value(value, data_type):
        if value is None:
            return f"CAST(NULL AS {data_type})"
        if data_type == "TIMESTAMP":
            return f"TIMESTAMP '{value}'"
        if data_type == "VARCHAR":
            return "'" + str(value).replace("'", "''") + "'"
        return f"CAST({value} AS {data_type})"

    select_rows = []
    for fixture_row in fixture_rows:
        values = {**overrides, **fixture_row}
        expressions = [
            f"{sql_value(values.get(column['name']), column['type'])} AS \"{column['name']}\""
            for column in cohort["columns"]
        ]
        select_rows.append("SELECT " + ", ".join(expressions))
    con = duckdb.connect()
    source_sql = " UNION ALL ".join(select_rows)
    target_sql = trips.as_posix().replace("'", "''")
    con.execute(f"COPY ({source_sql}) TO '{target_sql}' (FORMAT PARQUET)")
    con.close()
    audit_record["bytes"] = trips.stat().st_size
    audit_record["rows"] = len(fixture_rows)
    audit_record["sha256"] = pipeline.sha256(trips)
    audit_path.write_text(json.dumps(audit_doc, indent=2) + "\n", encoding="utf-8")
    yaml_path = tmp_path / "contracts/v2/pipeline.yaml"
    yaml_text = yaml_path.read_text(encoding="utf-8")
    yaml_text = re.sub(r"(?m)^  sha256: [a-f0-9]{64}$",
                       f"  sha256: {pipeline._normalized_json_sha256(audit_path)}", yaml_text, count=1)
    yaml_path.write_text(yaml_text, encoding="utf-8")
    lookup = tmp_path / "lookup.csv"
    lookup.write_text(
        "LocationID,Borough,Zone,service_zone\n1,Manhattan,Alpha,Yellow\n2,Queens,Beta,Boro\n",
        encoding="utf-8",
    )
    report = run(trips, lookup, tmp_path, contract_version="v2")

    assert report["contract_version"] == 2
    assert report["source_month"] == "2023-01"
    assert report["date_coverage"]["lower_bound_inclusive"] == "2022-12-31 00:00:00"
    assert report["date_coverage"]["upper_bound_exclusive"] == "2023-02-02 00:00:00"
    assert report["date_coverage"]["rejected_rows"] == 1
    assert report["date_coverage"]["alerts"] == 0
    assert report["cleaning"]["rejected_rows_by_rule"]["far_out_pickup"] == 1
    assert report["cleaning"]["total_rejected_rows"] == 1
    assert report["row_counts"]["raw_trips"] == 4
    assert report["row_counts"]["clean_trips"] == 3
    assert report["outcome"] == "passed"
    assert report["publication"]["decision"] == "published"
    assert report["peak_memory"]["scope"] == "dedicated_experiment_process"
    assert report["source_provenance"]["source_rows"] == 4

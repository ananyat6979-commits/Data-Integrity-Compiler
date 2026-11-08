import importlib.util
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("schema_audit", ROOT / "experiments" / "m2a" / "schema_audit.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _write(directory: Path, month: str, extra: bool = False, fare_type: str = "DOUBLE", airport: str = "Airport_fee"):
    path = directory / f"yellow_tripdata_{month}.parquet"
    target = path.as_posix().replace("'", "''")
    tail = ", 0.75::DOUBLE" if extra else ""
    tail_zero = ", 0.0::DOUBLE" if extra else ""
    header = ", cbd_congestion_fee" if extra else ""
    duckdb.connect().execute(f"""COPY (SELECT * FROM (VALUES
        (TIMESTAMP '{month}-05 10:00:00', TIMESTAMP '{month}-05 10:20:00', 1, 2, 12.5::{fare_type}, 3.0::DOUBLE, 1.25::DOUBLE{tail}),
        (TIMESTAMP '{month}-06 11:00:00', TIMESTAMP '{month}-06 11:10:00', NULL, 3, -4.0::{fare_type}, 0.0::DOUBLE, 0.0::DOUBLE{tail_zero}),
        (TIMESTAMP '2000-01-01 00:00:00', TIMESTAMP '2000-01-01 00:10:00', 4, 5, 8.0::{fare_type}, 1.0::DOUBLE, 0.0::DOUBLE{tail_zero})
      ) t(tpep_pickup_datetime, tpep_dropoff_datetime, PULocationID, DOLocationID, fare_amount, trip_distance, "{airport}"{header})
    ) TO '{target}' (FORMAT PARQUET)""")
    return path


def test_month_range_is_inclusive_and_rejects_bad_input():
    assert audit.month_range("2022-11", "2023-02") == ["2022-11", "2022-12", "2023-01", "2023-02"]
    with pytest.raises(ValueError):
        audit.month_range("2023-02", "2022-11")
    with pytest.raises(ValueError):
        audit.month_range("2022-13", "2023-01")


def test_audit_records_counts_coverage_and_cohort_transitions(tmp_path):
    _write(tmp_path, "2022-01")
    _write(tmp_path, "2022-02")
    _write(tmp_path, "2022-03", extra=True)
    _write(tmp_path, "2022-04", extra=True, fare_type="FLOAT")
    _write(tmp_path, "2022-05", extra=True, fare_type="FLOAT", airport="airport_fee")
    report = audit.build_report(tmp_path, audit.month_range("2022-01", "2022-05"))
    assert [c["months"] for c in report["cohorts"]] == [["2022-01", "2022-02"], ["2022-03"], ["2022-04"], ["2022-05"]]
    first = report["months"][0]
    assert "columns" not in first and first["cohort_id"] == "C1"
    assert first["rows"] == 3 and first["rows_outside_month"] == 1
    assert first["negative_fare_rows"] == 1 and first["nonpositive_distance_rows"] == 1
    assert first["nulls"]["PULocationID"] == 1 and first["pickup_location_id_range"] == [1, 4]
    assert len(first["sha256"]) == 64 and first["file"] == "yellow_tripdata_2022-01.parquet"
    t1, t2, t3 = report["transitions"]
    assert t1["added"] == ["cbd_congestion_fee"] and t1["removed"] == [] and t1["first_month_of_to"] == "2022-03"
    assert [x["column"] for x in t2["type_changed"]] == ["fare_amount"]
    assert t3["case_only_renames"] == [{"from": "Airport_fee", "to": "airport_fee"}]
    assert t3["added"] == [] and t3["removed"] == []


def test_audit_is_deterministic_and_fails_clearly_on_missing_files(tmp_path):
    _write(tmp_path, "2022-01")
    out1, out2 = tmp_path / "a.json", tmp_path / "b.json"
    assert audit.main(["--raw", str(tmp_path), "--start", "2022-01", "--end", "2022-01", "--out", str(out1)]) == 0
    assert audit.main(["--raw", str(tmp_path), "--start", "2022-01", "--end", "2022-01", "--out", str(out2)]) == 0
    assert out1.read_bytes() == out2.read_bytes() and b"\r\n" not in out1.read_bytes()
    assert audit.main(["--raw", str(tmp_path), "--start", "2022-01", "--end", "2022-03", "--out", str(tmp_path / "c.json")]) == 1

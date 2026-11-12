import importlib.util
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "paired_null_audit", ROOT / "experiments" / "m2a" / "paired_null_audit.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _write_pair_file(directory: Path, month: str) -> Path:
    path = directory / f"yellow_tripdata_{month}.parquet"
    target = path.as_posix().replace("'", "''")
    duckdb.connect().execute(
        f"""COPY (SELECT * FROM (VALUES
            (NULL::DOUBLE, 1.0::DOUBLE),
            (2.0::DOUBLE, NULL::DOUBLE),
            (NULL::DOUBLE, NULL::DOUBLE),
            (3.0::DOUBLE, 3.0::DOUBLE),
            ('NaN'::DOUBLE, 4.0::DOUBLE)
        ) t(passenger_count, RatecodeID)) TO '{target}' (FORMAT PARQUET)"""
    )
    return path


def test_month_range_is_inclusive_and_validates_inputs():
    assert audit.month_range("2022-11", "2023-02") == [
        "2022-11", "2022-12", "2023-01", "2023-02"
    ]
    with pytest.raises(ValueError):
        audit.month_range("2023-02", "2022-11")
    with pytest.raises(ValueError):
        audit.month_range("2022-13", "2023-01")
    with pytest.raises(ValueError):
        audit.month_range("2022-1", "2022-02")


def test_audit_distinguishes_equal_marginals_from_paired_nulls(tmp_path):
    path = _write_pair_file(tmp_path, "2022-01")
    record = audit.audit_month(path, "2022-01")
    assert record["rows"] == 5
    assert record["nulls"] == {"passenger_count": 2, "RatecodeID": 2}
    assert record["both_null_rows"] == 1
    assert record["one_sided_null_rows"] == 2
    assert record["nan_rows"] == {"passenger_count": 1, "RatecodeID": 0}
    assert len(record["sha256"]) == 64


def test_report_is_deterministic_and_rejects_missing_columns(tmp_path):
    _write_pair_file(tmp_path, "2022-01")
    first = audit.build_report(tmp_path, ["2022-01"])
    second = audit.build_report(tmp_path, ["2022-01"])
    assert first == second

    bad_path = tmp_path / "yellow_tripdata_2022-02.parquet"
    target = bad_path.as_posix().replace("'", "''")
    duckdb.connect().execute(
        f"""COPY (SELECT 1::INTEGER AS passenger_count)
        TO '{target}' (FORMAT PARQUET)"""
    )
    with pytest.raises(ValueError, match="missing required columns"):
        audit.audit_month(bad_path, "2022-02")

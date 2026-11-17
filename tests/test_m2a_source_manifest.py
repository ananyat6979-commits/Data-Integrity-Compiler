import json
import shutil
from pathlib import Path

import pytest

from experiments.m2a.validate_source_manifest import discover_monthly_sources
from experiments.m2a.validate_source_manifest import verify_source_manifest

ROOT = Path(__file__).parents[1]


def test_monthly_source_inventory_must_match_contract_exactly(tmp_path: Path):
    (tmp_path / "yellow_tripdata_2022-01.parquet").touch()
    (tmp_path / "yellow_tripdata_2022-02.parquet").touch()
    sources = discover_monthly_sources(tmp_path, ["2022-01", "2022-02"])
    assert list(sources) == ["2022-01", "2022-02"]

    (tmp_path / "yellow_tripdata_2022-03.parquet").touch()
    with pytest.raises(ValueError, match="extra=.*2022-03"):
        discover_monthly_sources(tmp_path, ["2022-01", "2022-02"])


def test_monthly_source_inventory_rejects_missing_month(tmp_path: Path):
    (tmp_path / "yellow_tripdata_2022-01.parquet").touch()
    with pytest.raises(ValueError, match="missing=.*2022-02"):
        discover_monthly_sources(tmp_path, ["2022-01", "2022-02"])


def test_compact_source_manifest_verifier_accepts_and_rejects_evidence(tmp_path: Path):
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    audit_dir = tmp_path / "experiments/m2a/audit"
    audit_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "experiments/m2a/audit/schema_audit_2022-01_2025-12.json", audit_dir)
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    manifest_path = audit_dir / "source_manifest_v2.json"
    shutil.copy2(ROOT / "experiments/m2a/audit/source_manifest_v2.json", manifest_path)

    verified = verify_source_manifest(tmp_path, manifest_path)
    assert verified["validation"] == "valid_internal_evidence"
    assert verified["source_count"] == 48
    assert verified["raw_files_reopened"] is False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["rows"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 does not match"):
        verify_source_manifest(tmp_path, manifest_path)

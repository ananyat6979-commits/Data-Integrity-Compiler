import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import jsonschema
import pytest

from dic.pipeline import load_contract


ROOT = Path(__file__).parents[1]
VERIFIER_PATH = ROOT / "experiments" / "kaggle_upload" / "verify_kaggle_results.py"
SPEC = importlib.util.spec_from_file_location("evidence_verifier", VERIFIER_PATH)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _make_evidence(root: Path, manifest_clean_trips: int = 4) -> Path:
    from shutil import copy2

    bundle = root / "evidence"
    bundle.mkdir(parents=True)
    (bundle / "contracts").mkdir()
    (bundle / "schemas").mkdir()
    copy2(ROOT / "contracts/pipeline.yaml", bundle / "contracts/pipeline.yaml")
    copy2(ROOT / "contracts/tlc-yellow-v1.json", bundle / "contracts/tlc-yellow-v1.json")
    copy2(ROOT / "schemas/report-v2.schema.json", bundle / "schemas/report-v2.schema.json")
    contract_hash = load_contract(ROOT)[2]
    clean_id, repeat_id, fault_id = "clean-2024-01", "repeat-2024-01", "fault-duplicate"
    fingerprint = "rows=4;logical_hash=123"
    expected = {"evidence_version": "test", "clean_run_id": clean_id,
                "repeat_clean_run_id": repeat_id, "fault_run_id": fault_id,
                "published_run_id_after_fault": repeat_id, "contract_version": 2,
                "contract_sha256": contract_hash, "clean_trips_fingerprint": fingerprint,
                "expected_injected_row_inflation": 50}
    _write_json(bundle / "expected.json", expected)

    def report(run_id, outcome="passed", row_inflation=0, deltas=None):
        return {"schema_version": "dic-report-v2", "run_id": run_id,
                "source_artifacts": {}, "contract_id": "fixture", "contract_version": 2,
                "contract_hash": contract_hash,
                "cleaning": {"rejection_attribution": "first_failing_rule", "total_rejected_rows": 0,
                             "rejected_rows_by_rule": {}},
                "peak_memory": {"status": "unavailable", "metric": "peak_working_set",
                                "platform": "fixture", "method": "unavailable fixture counter",
                                "native_units": None, "conversion": None,
                                "scope": "dedicated_experiment_process", "value_bytes": None,
                                "reason": "fixture does not measure memory"},
                "outcome": outcome, "checks": [], "evidence": {},
                "expected_observed": {"row_inflation": row_inflation},
                "downstream_aggregate_deltas": deltas or [],
                "publication": {"decision": "blocked" if outcome == "blocked" else "published",
                                "pointer_before": repeat_id if outcome == "blocked" else None,
                                "pointer_after": repeat_id if outcome == "blocked" else run_id},
                "runtimes_seconds": {}, "versions": {},
                "row_counts": {"raw_trips": 8, "clean_trips": 4, "enriched_candidate_rows": 4},
                "logical_output_hashes": {"clean_trips": fingerprint}}

    clean = report(clean_id)
    repeat = report(repeat_id)
    deltas = []
    for i in range(22):
        deltas.append({"trip_count_delta": 8 if i == 0 else 2,
                       "revenue_delta": "4113.35" if i == 0 else "1.00",
                       "average_fare_unchanged": True})
    fault = report(fault_id, "blocked", 50, deltas)
    for value in (clean, repeat, fault):
        run_id = value["run_id"]
        _write_json(bundle / f"data/runs/{run_id}/report.json", value)
        _write_json(bundle / f"data/runs/{run_id}/manifest.json",
                    {"run_id": run_id, "contract_sha256": contract_hash,
                     "row_counts": {"raw_trips": 8, "clean_trips": manifest_clean_trips},
                     "logical_output_hashes": value["logical_output_hashes"]})

    controls = bundle / "data/clean-controls"
    for month in ("2022-01", "2022-02", "2022-03", "2022-04"):
        _write_json(controls / f"{month}.json", report(f"control-{month}"))
    _write_json(bundle / "data/clean_report.json", clean)
    _write_json(bundle / "data/fault_report.json", fault)
    _write_json(bundle / "data/source-manifest.json", {"months": {}})
    _write_json(bundle / "data/published/CURRENT", {"run_id": repeat_id})
    _write_json(bundle / "data/jan-2024-reconciliation.json",
                {"clean_run_id": clean_id, "fault_run_id": fault_id,
                 "contract_sha256": contract_hash, "expected_row_inflation": 50,
                 "observed_row_inflation": 50, "publication_pointer_preserved": True,
                 "affected_daily_zone_groups": 22, "total_trip_count_delta": 50,
                 "total_revenue_delta": "4134.35"})
    _write_json(bundle / "reconciliation-witness.json",
                {"source_report": f"data/runs/{fault_id}/report.json",
                 "affected_daily_zone_groups": 22, "trip_count_delta": 50,
                 "revenue_delta": "4134.35", "all_average_fares_unchanged": True})
    _write_json(bundle / "provenance.json",
                {"m1_verified_tree_hash": "a" * 40, "commit_sha": "b" * 40,
                 "tree_sha": "c" * 40, "source_archive_sha256": "d" * 64,
                 "notebook_sha256": "e" * 64, "kaggle_notebook_version": "17"})
    (bundle / "README.md").write_text("Test evidence only.\n", encoding="utf-8")
    sums = {p.relative_to(bundle).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(bundle.rglob("*")) if p.is_file()}
    _write_json(bundle / "SHA256SUMS.json", sums)
    return bundle


def test_evidence_verifier_accepts_folder_and_zip(tmp_path):
    bundle = _make_evidence(tmp_path)
    folder_result = verifier.verify_bundle(bundle, ROOT)
    assert folder_result["valid"] is True, folder_result
    assert folder_result["current_repository_contract_matches"] is True
    archive_path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle.rglob("*"):
            if path.is_file():
                archive.write(path, f"results/m1/{path.relative_to(bundle).as_posix()}")
    archive_result = verifier.verify_bundle(archive_path, ROOT)
    assert archive_result["valid"] is True
    assert archive_result["bundle_kind"] == "zip"


def test_evidence_verifier_rejects_modified_or_missing_evidence(tmp_path):
    bundle = _make_evidence(tmp_path)
    target = bundle / "data/runs/clean-2024-01/manifest.json"
    target.write_text(target.read_text().replace("clean-2024-01", "altered"))
    result = verifier.verify_bundle(bundle, ROOT)
    assert result["valid"] is False
    assert any("checksum mismatch" in error for error in result["errors"])
    (bundle / "data/source-manifest.json").unlink()
    missing_result = verifier.verify_bundle(bundle, ROOT)
    assert missing_result["valid"] is False
    assert any("missing required evidence file: data/source-manifest.json" in error
               for error in missing_result["errors"])


def test_evidence_verifier_rejects_report_schema_violation(tmp_path):
    bundle = _make_evidence(tmp_path)
    target_name = "data/runs/clean-2024-01/report.json"
    target = bundle / target_name
    report = json.loads(target.read_text())
    report["schema_version"] = "invalid"
    _write_json(target, report)
    sums = json.loads((bundle / "SHA256SUMS.json").read_text())
    sums[target_name] = hashlib.sha256(target.read_bytes()).hexdigest()
    _write_json(bundle / "SHA256SUMS.json", sums)
    with pytest.raises(jsonschema.ValidationError):
        verifier.verify_bundle(bundle, ROOT)


def test_evidence_verifier_rejects_unsafe_zip_paths(tmp_path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")
    with pytest.raises(ValueError, match="Unsafe ZIP member path"):
        verifier.Bundle(archive_path)


def test_later_repository_contract_change_does_not_invalidate_history(tmp_path):
    bundle = _make_evidence(tmp_path)
    later_repo = tmp_path / "later-repository"
    (later_repo / "contracts").mkdir(parents=True)
    shutil.copy2(ROOT / "contracts/pipeline.yaml", later_repo / "contracts/pipeline.yaml")
    shutil.copy2(ROOT / "contracts/tlc-yellow-v1.json", later_repo / "contracts/tlc-yellow-v1.json")
    changed = later_repo / "contracts/pipeline.yaml"
    changed.write_text(changed.read_text() + "\n# later contract version\n")
    result = verifier.verify_bundle(bundle, later_repo)
    assert result["valid"] is True
    assert result["current_repository_contract_matches"] is False


def test_manifest_may_omit_derived_report_counts_but_not_contradict_them(tmp_path):
    # Real pipeline manifests omit enriched_candidate_rows, which only the report carries.
    ok = verifier.verify_bundle(_make_evidence(tmp_path / "ok"), ROOT)
    assert ok["valid"] is True, ok
    bad = verifier.verify_bundle(_make_evidence(tmp_path / "bad", manifest_clean_trips=5), ROOT)
    assert bad["valid"] is False
    assert any("manifest row counts mismatch" in error for error in bad["errors"])


def test_committed_m1_evidence_verifies_from_a_fresh_checkout():
    # Catches line-ending conversion (e.g. core.autocrlf on Windows) breaking the committed checksums.
    evidence = ROOT / "results" / "m1"
    if not evidence.is_dir():
        pytest.skip("results/m1 is not present in this checkout")
    result = verifier.verify_bundle(evidence, ROOT)
    assert result["valid"] is True, result["errors"]

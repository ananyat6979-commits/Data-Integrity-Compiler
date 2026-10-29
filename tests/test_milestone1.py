import json
import hashlib
import os
import platform
import sys
import shutil
import subprocess
import time
from types import SimpleNamespace
from pathlib import Path

import jsonschema
import pytest

from dic.pipeline import (_publish, canonical_hash, classify_schema, collect_orphaned_staging,
                          evaluate, inject_m1, load_contract, measure_peak_working_set, run)


SCHEMA = Path(__file__).parents[1] / "schemas" / "report-v2.schema.json"


def assert_report_shape(report):
    """Validate this versioned report schema's required fields and fixed enumerations."""
    schema = json.loads(SCHEMA.read_text())
    jsonschema.validate(report, schema)
    assert all(key in report for key in schema["required"])
    assert report["schema_version"] == schema["properties"]["schema_version"]["const"]
    assert report["outcome"] in schema["properties"]["outcome"]["enum"]
    for check in report["checks"]:
        assert {"id", "severity", "passed"} <= check.keys()
        assert check["severity"] in {"block", "warn", "info"}
        assert isinstance(check["passed"], bool)


def test_clean_passes_repeatably_and_report_validates(sample):
    trips, lookup, root = sample
    one = run(trips, lookup, root)
    two = run(trips, lookup, root)
    assert one["outcome"] == two["outcome"] == "passed"
    assert one["row_counts"] == two["row_counts"]
    assert one["row_counts"]["unmatched_rows"] == 1
    assert one["checks"][2]["passed"] is True
    assert one["logical_output_hashes"] == two["logical_output_hashes"]
    assert_report_shape(one)
    current = json.loads((root / "data/published/CURRENT").read_text())
    assert current["run_id"] == two["run_id"]


def test_duplicate_m1_block_evidence_and_independent_effect(sample):
    trips, lookup, root = sample
    good = run(trips, lookup, root)
    fault = inject_m1(lookup, root / "data/runs", "1")
    report = run(trips, fault["lookup"], root, fault["fault_id"], lookup)
    assert report["outcome"] == "blocked"
    assert report["evidence"]["affected_key"] == "1"
    assert report["checks"][0]["passed"] is False
    assert report["checks"][2]["passed"] is False
    # Independently calculated from the tiny source fixture: two trips match key 1, one extra copy.
    assert report["evidence"]["affected_input_rows"] == 2
    assert report["expected_observed"]["row_inflation"] == 2
    assert report["expected_observed"]["expected_row_inflation_from_new_duplicate_keys"] == 2
    impacts = [x for x in report["downstream_aggregate_deltas"] if x["pickup_zone"] == 1]
    assert len(impacts) == 1
    impact = impacts[0]
    assert impact["trip_count_delta"] == 2
    assert impact["revenue_delta"] == "30.00"
    assert impact["average_fare_unchanged"] is True
    assert_report_shape(report)
    assert evaluate(Path(root / "data/runs" / report["run_id"] / "report.json"), fault["ground_truth"])["key_matches"]
    assert json.loads((root / "data/published/CURRENT").read_text())["run_id"] == good["run_id"]
    assert (root / "data/runs" / report["run_id"] / "report.json").is_file()


def test_worker_fails_on_any_ground_truth_path_open(sample):
    trips, lookup, root = sample
    forbidden_input = root / "ground_truth-input.parquet"
    shutil.copyfile(trips, forbidden_input)
    with pytest.raises(RuntimeError, match="Detector attempted to open forbidden ground truth path"):
        run(forbidden_input, lookup, root)


def test_blocked_first_run_publishes_nothing(sample):
    trips, lookup, root = sample
    fault = inject_m1(lookup, root / "data/runs", "1")
    report = run(trips, fault["lookup"], root, fault["fault_id"], lookup)
    assert report["outcome"] == "blocked"
    assert not (root / "data/published/CURRENT").exists()


def test_interrupted_pointer_promotion_preserves_prior_version(sample):
    trips, lookup, root = sample
    first = run(trips, lookup, root)
    current = root / "data/published/CURRENT"
    before = current.read_bytes()
    stage = root / "data/runs" / "interrupted-stage"
    stage.mkdir()
    (stage / "report.json").write_text(json.dumps(first))
    (stage / "manifest.json").write_text(json.dumps({"run_id": first["run_id"]}))
    with pytest.raises(RuntimeError, match="simulated interruption"):
        _publish(stage, root / "data/published", "interrupted", first, "before_pointer_swap")
    assert current.read_bytes() == before
    assert json.loads(current.read_text())["run_id"] == first["run_id"]


def test_original_lookup_is_unchanged_and_injector_requires_single_row(sample):
    trips, lookup, root = sample
    before = lookup.read_bytes()
    trips_before = trips.read_bytes()
    inject_m1(lookup, root / "data/runs", "1")
    assert lookup.read_bytes() == before
    assert trips.read_bytes() == trips_before
    duplicate = root / "duplicate.csv"
    shutil.copyfile(lookup, duplicate)
    duplicate.write_text(duplicate.read_text() + '1,Manhattan,Alpha,Yellow\n')
    with pytest.raises(ValueError, match="exactly one"):
        inject_m1(duplicate, root / "data/runs", "1")


def test_preexisting_duplicate_is_reported_as_baseline_violation(sample):
    trips, lookup, root = sample
    preexisting = root / "preexisting.csv"
    preexisting.write_text(lookup.read_text() + "1,Manhattan,Alpha,Yellow\n")
    report = run(trips, preexisting, root, reference_lookup=preexisting)
    assert report["outcome"] == "blocked"
    assert report["evidence"]["preexisting_source_violations"]["duplicate_keys"] == {"1": 2}
    assert report["evidence"]["affected_key"] is None


def test_runtime_schema_validator_rejects_invalid_reports():
    with pytest.raises(jsonschema.ValidationError):
        from dic.pipeline import validate_report as production_validate_report
        production_validate_report({"schema_version": "dic-report-v1"})


def test_schema_classifier_distinguishes_compatible_review_and_incompatible():
    baseline = json.loads((Path(__file__).parents[1] / "contracts/tlc-yellow-v1.json").read_text())
    schema = [{"name": name, "type": kind} for name, kind in baseline["columns"].items()]
    assert classify_schema(schema)["schema_classification"] == "compatible"
    known_addition = schema + [{"name": "cbd_congestion_fee", "type": "DOUBLE"}]
    result = classify_schema(known_addition)
    assert result["schema_classification"] == "compatible"
    assert result["added_columns"] == ["cbd_congestion_fee"]
    unknown_addition = schema + [{"name": "unexpected_field", "type": "DOUBLE"}]
    assert classify_schema(unknown_addition)["schema_classification"] == "review"
    missing_required = [item for item in schema if item["name"] != "PULocationID"]
    assert classify_schema(missing_required)["schema_classification"] == "incompatible"


def test_stage_outputs_are_parquet_and_runtimes_are_separate(sample):
    trips, lookup, root = sample
    report = run(trips, lookup, root)
    stage = root / "data/runs" / report["run_id"]
    for name in ["clean_trips", "diagnostic_join", "trip_enriched", "daily_zone_metrics"]:
        assert (stage / f"{name}.parquet").is_file()
        assert report["logical_output_hashes"][name].startswith("rows=")
    times = report["runtimes_seconds"]
    assert times["validation_seconds"] <= times["total_pipeline_seconds"]
    assert times["output_materialization_seconds"] <= times["total_pipeline_seconds"]
    assert times["publication_seconds"] >= 0
    memory = report["peak_memory"]
    assert memory["scope"] == "dedicated_experiment_process"
    assert memory["status"] in {"available", "unavailable"}
    if memory["status"] == "available":
        assert memory["value_bytes"] > 0
    assert report["contract_hash"] == report["source_artifacts"]["contract_sha256"]


def test_small_fixture_canonical_fingerprint_is_portable(sample):
    import duckdb
    trips, lookup, root = sample
    report = run(trips, lookup, root)
    output = root / "data/runs" / report["run_id"] / "clean_trips.parquet"
    con = duckdb.connect()
    rows = con.execute(
        "SELECT source_row_ordinal, pickup_zone, pickup_date, fare_decimal "
        "FROM read_parquet(?) ORDER BY source_row_ordinal", [str(output)]).fetchall()
    con.close()
    expected = json.loads((Path(__file__).parent / "fixtures" / "small-fingerprint.json").read_text())
    assert expected["row_count"] == len(rows)
    assert expected["canonical_sha256"] == canonical_hash(rows)


def test_contract_hash_covers_yaml_and_referenced_schema(sample):
    _, _, root = sample
    before = load_contract(root)[2]
    contract_file = root / "contracts/pipeline.yaml"
    contract_file.write_text(contract_file.read_text().replace("unmatched_policy: exclude", "unmatched_policy: block"))
    after_yaml = load_contract(root)[2]
    assert before != after_yaml
    contract_file.write_text(contract_file.read_text().replace("unmatched_policy: block", "unmatched_policy: exclude"))
    schema_file = root / "contracts/tlc-yellow-v1.json"
    schema = json.loads(schema_file.read_text())
    schema["description"] = "hash coverage regression"
    schema_file.write_text(json.dumps(schema))
    assert load_contract(root)[2] != before


def test_contract_hash_is_stable_across_line_endings(sample):
    _, _, root = sample
    paths = [root / "contracts/pipeline.yaml", root / "contracts/tlc-yellow-v1.json"]
    originals = [path.read_bytes() for path in paths]
    expected = load_contract(root)[2]
    try:
        for path, content in zip(paths, originals):
            normalized = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            path.write_bytes(normalized.replace(b"\n", b"\r\n"))
        assert load_contract(root)[2] == expected
    finally:
        for path, content in zip(paths, originals):
            path.write_bytes(content)


def test_contract_rejects_unsupported_operator_and_missing_setting(sample):
    _, _, root = sample
    contract_file = root / "contracts/pipeline.yaml"
    original = contract_file.read_text()
    contract_file.write_text(original.replace("operator: not_null", "operator: arbitrary_sql"))
    with pytest.raises(ValueError, match="Unsupported cleaning operator"):
        load_contract(root)
    contract_file.write_text(original.replace("  unmatched_policy: exclude\n", ""))
    with pytest.raises(ValueError, match="join settings are incomplete"):
        load_contract(root)
    contract_file.write_text(original.replace("column: fare_amount", "column: nonexistent_fare"))
    with pytest.raises(ValueError, match="unknown schema column"):
        load_contract(root)


def test_cleaning_contract_changes_behavior_and_reports_first_failure(sample):
    trips, lookup, root = sample
    first = run(trips, lookup, root)
    contract_file = root / "contracts/pipeline.yaml"
    original = contract_file.read_text()
    contract_file.write_text(original.replace("value: 0", "value: 10", 1))
    second = run(trips, lookup, root)
    assert first["row_counts"]["clean_trips"] == 4
    assert second["row_counts"]["clean_trips"] == 2
    cleaning = second["cleaning"]
    assert cleaning["rejection_attribution"] == "first_failing_rule"
    assert cleaning["total_rejected_rows"] == sum(cleaning["rejected_rows_by_rule"].values()) == 2
    assert cleaning["rejected_rows_by_rule"]["nonnegative_fare"] == 2


def test_unsupported_join_key_is_rejected(sample):
    trips, lookup, root = sample
    contract_file = root / "contracts/pipeline.yaml"
    original = contract_file.read_text()
    contract_file.write_text(original.replace("key: PULocationID", "key: DOLocationID", 1))
    with pytest.raises(RuntimeError, match="join.key must be PULocationID"):
        run(trips, lookup, root)
    contract_file.write_text(original)


def test_unmatched_key_policy_changes_handling(sample):
    trips, lookup, root = sample
    contract_file = root / "contracts/pipeline.yaml"
    original = contract_file.read_text()
    contract_file.write_text(original.replace("unmatched_policy: exclude", "unmatched_policy: block"))
    assert run(trips, lookup, root)["outcome"] == "blocked"


def test_lookup_uniqueness_and_cardinality_policies_change_enforcement(sample):
    trips, lookup, root = sample
    contract_file = root / "contracts/pipeline.yaml"
    original = contract_file.read_text()
    fault = inject_m1(lookup, root / "data/runs", "1")
    contract_file.write_text(original.replace("lookup_uniqueness_severity: block", "lookup_uniqueness_severity: warn"))
    still_blocked = run(trips, fault["lookup"], root, fault["fault_id"], lookup)
    assert still_blocked["outcome"] == "blocked"
    contract_file.write_text(original.replace("cardinality: many_to_one", "cardinality: many_to_many"))
    unique_block = run(trips, fault["lookup"], root, fault["fault_id"], lookup)
    assert unique_block["outcome"] == "blocked"
    contract_file.write_text(original.replace("cardinality: many_to_one", "cardinality: many_to_many")
                             .replace("lookup_uniqueness_severity: block", "lookup_uniqueness_severity: warn"))
    allowed = run(trips, fault["lookup"], root, fault["fault_id"], lookup)
    assert allowed["outcome"] == "passed"
    assert allowed["checks"][0]["severity"] == "warn"
    contract_file.write_text(original.replace("lookup_uniqueness_severity: block", "lookup_uniqueness_severity: warn")
                             .replace("cardinality_severity: block", "cardinality_severity: warn"))
    cardinality_warn = run(trips, fault["lookup"], root, fault["fault_id"], lookup)
    assert cardinality_warn["outcome"] == "passed"
    assert cardinality_warn["checks"][2]["severity"] == "warn"


def test_memory_measurement_conversion_and_unavailable(monkeypatch):
    import dic.pipeline as pipeline
    fake_resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: SimpleNamespace(ru_maxrss=7))
    monkeypatch.setitem(sys.modules, "resource", fake_resource)
    monkeypatch.setattr(pipeline.platform, "system", lambda: "Linux")
    result = measure_peak_working_set()
    assert result["status"] == "available"
    assert result["value_bytes"] == 7 * 1024
    assert result["native_units"] == "KiB"
    monkeypatch.setattr(pipeline.platform, "system", lambda: "Darwin")
    mac_result = measure_peak_working_set()
    assert mac_result["value_bytes"] == 7
    assert mac_result["native_units"] == "bytes"
    monkeypatch.setattr(pipeline.platform, "system", lambda: "Plan9")
    unavailable = measure_peak_working_set()
    assert unavailable["status"] == "unavailable"
    assert unavailable["reason"]


def test_windows_peak_memory_counter(monkeypatch):
    import dic.pipeline as pipeline
    monkeypatch.setattr(pipeline.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pipeline.psutil, "Process", lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(peak_wset=4096)))
    result = measure_peak_working_set()
    assert result["status"] == "available"
    assert result["method"] == "psutil.Process.memory_info().peak_wset"
    assert result["value_bytes"] == 4096


def test_unmocked_peak_memory_smoke_records_metadata():
    script = "import json; from dic.pipeline import measure_peak_working_set; print(json.dumps(measure_peak_working_set()))"
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["metric"] == "peak_working_set"
    assert result["platform"] and result["method"] and result["scope"] == "dedicated_experiment_process"
    if result["status"] == "available":
        assert isinstance(result["value_bytes"], int) and 0 < result["value_bytes"] < 128 * 1024**3
        assert result["native_units"] and result["conversion"] is not None
    else:
        assert result["reason"] and result["value_bytes"] is None


def test_contract_validation_failure_preserves_current(sample):
    trips, lookup, root = sample
    current = run(trips, lookup, root)
    pointer = (root / "data/published/CURRENT").read_bytes()
    contract_file = root / "contracts/pipeline.yaml"
    contract_file.write_text(contract_file.read_text().replace("schema_file: tlc-yellow-v1.json", "schema_file: missing.json"))
    with pytest.raises(RuntimeError, match="schema_file"):
        run(trips, lookup, root)
    assert (root / "data/published/CURRENT").read_bytes() == pointer
    assert json.loads((root / "data/published/CURRENT").read_text())["run_id"] == current["run_id"]


def test_input_validation_failure_cleans_staging_and_preserves_current(sample):
    trips, lookup, root = sample
    current = run(trips, lookup, root)
    pointer = (root / "data/published/CURRENT").read_bytes()
    before = {path.name for path in (root / "data/runs").iterdir() if path.is_dir()}
    invalid = root / "invalid-schema.parquet"
    con = __import__("duckdb").connect()
    con.execute(f"COPY (SELECT 1 AS wrong_column) TO '{invalid.as_posix()}' (FORMAT PARQUET)")
    con.close()
    with pytest.raises(RuntimeError, match="missing required columns"):
        run(invalid, lookup, root)
    after = {path.name for path in (root / "data/runs").iterdir() if path.is_dir()}
    assert after == before
    assert (root / "data/published/CURRENT").read_bytes() == pointer
    assert json.loads((root / "data/published/CURRENT").read_text())["run_id"] == current["run_id"]


def test_report_validation_failure_precedes_pointer_swap_and_records_error(sample):
    trips, lookup, root = sample
    current_report = run(trips, lookup, root)
    current = root / "data/published/CURRENT"
    pointer_before = current.read_bytes()
    published_before = {p.name for p in (root / "data/published").iterdir() if p.is_dir()}
    runs_before = {p.name for p in (root / "data/runs").iterdir() if p.is_dir()}
    with pytest.raises(RuntimeError, match="invalid-report-version"):
        run(trips, lookup, root, _test_failpoint="invalid_publication_report")
    assert current.read_bytes() == pointer_before
    assert json.loads(current.read_text())["run_id"] == current_report["run_id"]
    assert {p.name for p in (root / "data/published").iterdir() if p.is_dir()} == published_before
    assert {p.name for p in (root / "data/runs").iterdir() if p.is_dir()} == runs_before
    failures = list((root / "data/failures").glob("*.json"))
    record = json.loads(max(failures, key=lambda p: p.stat().st_mtime).read_text())
    assert record["status"] == "failed"
    assert record["error_type"] == "ValidationError"
    assert record["run_id"] and "schema_version" in record["error"]


def test_mid_materialization_error_cleans_stage_and_next_run_succeeds(sample):
    trips, lookup, root = sample
    prior = run(trips, lookup, root)
    current_path = root / "data/published/CURRENT"
    prior_current = current_path.read_bytes()
    runs = root / "data/runs"
    before = {p.name for p in runs.iterdir() if p.is_dir()} if runs.exists() else set()
    with pytest.raises(RuntimeError, match="after first output materialization"):
        run(trips, lookup, root, _test_failpoint="after_first_materialization")
    after = {p.name for p in runs.iterdir() if p.is_dir()} if runs.exists() else set()
    assert after == before
    assert current_path.read_bytes() == prior_current
    assert json.loads(current_path.read_text())["run_id"] == prior["run_id"]
    record = json.loads(max((root / "data/failures").glob("*.json"), key=lambda p: p.stat().st_mtime).read_text())
    assert record["status"] == "failed"
    assert record["error_type"] == "RuntimeError"
    assert record["staging_artifacts"] == ["clean_trips.parquet"]
    recovered = run(trips, lookup, root)
    assert recovered["outcome"] == "passed"
    assert json.loads(current_path.read_text())["run_id"] == recovered["run_id"]


def test_gc_dry_run_and_delete_preserve_current_and_complete_evidence(sample):
    trips, lookup, root = sample
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    clean = run(trips, lookup, root)
    fault_input = inject_m1(lookup, root / "data/runs", "1")
    blocked = run(trips, fault_input["lookup"], root, fault_input["fault_id"], lookup)
    orphan_id = "a" * 32
    orphan = root / "data/runs" / orphan_id
    orphan.mkdir()
    partial_id = "b" * 32
    partial_publication = root / "data/published" / partial_id
    partial_publication.mkdir()
    pointer_temp = root / "data/published" / ("CURRENT." + "c" * 32 + ".tmp")
    pointer_temp.write_text("incomplete")
    injector = root / "data/runs" / "m1-injector-evidence"
    injector.mkdir()
    (injector / "ground_truth.private.json").write_text("private")
    old = time.time() - 3 * 3600
    for path in (orphan, partial_publication, pointer_temp):
        os.utime(path, (old, old))
    current = root / "data/published/CURRENT"
    pointer = current.read_bytes()
    preview = collect_orphaned_staging(root, older_than_hours=1)
    expected_orphans = {f"data/runs/{orphan_id}", f"data/published/{partial_id}",
                        f"data/published/CURRENT.{'c' * 32}.tmp"}
    assert set(preview["candidates"]) == expected_orphans and orphan.exists()
    removed = collect_orphaned_staging(root, older_than_hours=1, delete=True)
    assert set(removed["removed"]) == expected_orphans
    assert not orphan.exists() and not partial_publication.exists() and not pointer_temp.exists()
    assert (injector / "ground_truth.private.json").is_file()
    assert current.read_bytes() == pointer
    assert (root / "data/runs" / blocked["run_id"] / "report.json").is_file()
    assert json.loads(current.read_text())["run_id"] == clean["run_id"]


def test_gc_refuses_malformed_or_unreadable_current(sample, monkeypatch):
    _, _, root = sample
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    runs = root / "data/runs"
    published = root / "data/published"
    runs.mkdir(parents=True)
    published.mkdir(parents=True)
    orphan = runs / ("a" * 32)
    orphan.mkdir()
    old = time.time() - 3 * 3600
    os.utime(orphan, (old, old))
    current = published / "CURRENT"
    current.write_text("{malformed")
    with pytest.raises(ValueError, match="malformed CURRENT"):
        collect_orphaned_staging(root, older_than_hours=1, delete=True)
    assert orphan.is_dir()

    current.write_text(json.dumps({"run_id": "b" * 32}))
    original_read_text = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == current:
            raise OSError("simulated unreadable pointer")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(ValueError, match="cannot read CURRENT"):
        collect_orphaned_staging(root, older_than_hours=1, delete=True)
    assert orphan.is_dir()


def test_gc_refuses_symlinked_data_directory(sample):
    _, _, root = sample
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    outside = root.parent / "outside-data"
    outside.mkdir()
    try:
        (root / "data").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    with pytest.raises(ValueError, match="symlinked data"):
        collect_orphaned_staging(root, older_than_hours=1, delete=True)

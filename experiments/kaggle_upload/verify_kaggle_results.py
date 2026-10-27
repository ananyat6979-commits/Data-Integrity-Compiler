"""Verify M1 evidence bundles supplied as a directory or ZIP, without raw TLC data."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path, PurePosixPath

import jsonschema


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contract_hash(read) -> str:
    normalize = lambda content: content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    parts = {"pipeline.yaml": _sha256(normalize(read("contracts/pipeline.yaml"))),
             "schema": _sha256(normalize(read("contracts/tlc-yellow-v1.json")))}
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(payload)


class Bundle:
    def __init__(self, path: Path):
        self.files: dict[str, bytes] = {}
        self.kind = "folder"
        if path.is_dir():
            for item in path.rglob("*"):
                if item.is_symlink():
                    raise ValueError(f"Evidence folder must not contain symbolic links: {item}")
                if item.is_file():
                    self.files[item.relative_to(path).as_posix()] = item.read_bytes()
        else:
            self.kind = "zip"
            with zipfile.ZipFile(path) as archive:
                if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
                    raise ValueError("Evidence ZIP exceeds the 512 MiB uncompressed size limit")
                seen: set[str] = set()
                for info in archive.infolist():
                    name = info.filename.replace("\\", "/")
                    if name in seen:
                        raise ValueError(f"Duplicate ZIP member path: {name}")
                    seen.add(name)
                    pure = PurePosixPath(name)
                    mode = (info.external_attr >> 16) & 0o170000
                    if pure.is_absolute() or ".." in pure.parts or (pure.parts and ":" in pure.parts[0]) or mode == 0o120000:
                        raise ValueError(f"Unsafe ZIP member path: {name}")
                    if info.is_dir():
                        continue
                    self.files[name] = archive.read(info)
        # Accept a results/m1 prefix in ZIPs or a parent directory containing that bundle.
        if "expected.json" not in self.files:
            candidates = [name[:-len("expected.json")] for name in self.files if name.endswith("expected.json")]
            if len(candidates) != 1:
                raise ValueError("Evidence bundle must contain one expected.json at its root")
            prefix = candidates[0]
            self.files = {name[len(prefix):]: data for name, data in self.files.items() if name.startswith(prefix)}

    def read(self, name: str) -> bytes:
        if name not in self.files:
            raise ValueError(f"Missing evidence file: {name}")
        return self.files[name]

    def json(self, name: str):
        return json.loads(self.read(name).decode("utf-8-sig"))


def verify_bundle(path: Path, repo_root: Path | None = None) -> dict:
    bundle = Bundle(path)
    expected = bundle.json("expected.json")
    errors: list[str] = []

    def require(ok: bool, message: str) -> None:
        if not ok:
            errors.append(message)

    sums = bundle.json("SHA256SUMS.json")
    require(set(sums) == set(bundle.files) - {"SHA256SUMS.json"}, "checksum manifest file set differs from bundle")
    for name, expected_digest in sums.items():
        if name in bundle.files:
            require(_sha256(bundle.files[name]) == expected_digest, f"checksum mismatch: {name}")
    require(not any(name.lower().endswith(".parquet") for name in bundle.files),
            "compact evidence bundle must not include large Parquet artifacts")
    require(not any("ground_truth" in name.lower() for name in bundle.files),
            "private ground-truth artifacts must not be included in the ordinary evidence bundle")
    for required_file in ("README.md", "provenance.json", "data/source-manifest.json",
                          "data/clean_report.json", "data/fault_report.json"):
        require(required_file in bundle.files, f"missing required evidence file: {required_file}")

    bundled_contract_hash = _contract_hash(bundle.read)
    require(bundled_contract_hash == expected.get("contract_sha256"), "bundled contract hash differs from expected.json")
    require(expected.get("contract_version") is not None, "expected contract version is missing")
    provenance = bundle.json("provenance.json")
    for key in ("m1_verified_tree_hash", "commit_sha", "tree_sha"):
        require(isinstance(provenance.get(key), str) and len(provenance[key]) == 40
                and all(char in "0123456789abcdef" for char in provenance[key].lower()),
                f"provenance {key} is missing or malformed")
    for key in ("source_archive_sha256", "notebook_sha256"):
        require(isinstance(provenance.get(key), str) and len(provenance[key]) == 64
                and all(char in "0123456789abcdef" for char in provenance[key].lower()),
                f"provenance {key} is missing or malformed")
    require(isinstance(provenance.get("kaggle_notebook_version"), str)
            and bool(provenance["kaggle_notebook_version"].strip()),
            "Kaggle notebook version is missing")
    schema = bundle.json("schemas/report-v2.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)

    report_names = sorted(name for name in bundle.files if name.startswith("data/runs/") and name.endswith("/report.json"))
    reports: dict[str, dict] = {}
    for name in report_names:
        report = bundle.json(name)
        jsonschema.validate(report, schema)
        run_id = report["run_id"]
        reports[run_id] = report
        manifest = bundle.json(f"data/runs/{run_id}/manifest.json")
        require(manifest.get("run_id") == run_id, f"manifest run ID mismatch: {run_id}")
        require(manifest.get("contract_sha256") == report.get("contract_hash"), f"manifest contract hash mismatch: {run_id}")
        require(manifest.get("contract_sha256") == bundled_contract_hash, f"report does not match bundled contract: {run_id}")
        require(manifest.get("row_counts") == report.get("row_counts"), f"manifest row counts mismatch: {run_id}")
        require(manifest.get("logical_output_hashes") == report.get("logical_output_hashes"),
                f"manifest fingerprints mismatch: {run_id}")
        require(report.get("contract_version") == expected["contract_version"], f"report contract version mismatch: {run_id}")

    clean_id = expected.get("clean_run_id")
    repeat_id = expected.get("repeat_clean_run_id")
    fault_id = expected.get("fault_run_id")
    clean, repeat, fault = reports.get(clean_id), reports.get(repeat_id), reports.get(fault_id)
    require(clean is not None and repeat is not None and fault is not None, "expected clean, repeat, or fault report is missing")
    recon = bundle.json("data/jan-2024-reconciliation.json")
    require(recon.get("contract_sha256") == bundled_contract_hash, "reconciliation contract hash differs from bundled contract")
    require(recon.get("clean_run_id") == clean_id and recon.get("fault_run_id") == fault_id,
            "reconciliation run IDs disagree with expected.json")

    controls = sorted(name for name in bundle.files if name.startswith("data/clean-controls/") and name.endswith(".json"))
    require(len(controls) == 4, "expected four archived clean-control reports")
    for name in controls:
        report = bundle.json(name)
        jsonschema.validate(report, schema)
        require(report.get("outcome") == "passed", f"clean control did not pass: {name}")
        require(report.get("contract_hash") == bundled_contract_hash, f"clean control contract mismatch: {name}")

    if clean and repeat and fault:
        summary_clean = bundle.json("data/clean_report.json")
        summary_fault = bundle.json("data/fault_report.json")
        jsonschema.validate(summary_clean, schema)
        jsonschema.validate(summary_fault, schema)
        require(summary_clean.get("run_id") == clean_id and summary_fault.get("run_id") == fault_id,
                "top-level report summaries disagree with expected run IDs")
        expected_fingerprint = expected.get("clean_trips_fingerprint")
        require(clean["logical_output_hashes"].get("clean_trips") == expected_fingerprint,
                "clean fingerprint differs from expected.json")
        require(repeat["logical_output_hashes"].get("clean_trips") == expected_fingerprint,
                "repeat clean fingerprint differs from expected.json")
        require(clean["logical_output_hashes"] == repeat["logical_output_hashes"],
                "clean and repeat output fingerprints differ")
        require(fault.get("outcome") == "blocked", "fault run was not blocked")
        require(fault.get("expected_observed", {}).get("row_inflation") == expected.get("expected_injected_row_inflation"),
                "fault report row inflation differs from expected.json")
        require(recon.get("expected_row_inflation") == recon.get("observed_row_inflation") == expected.get("expected_injected_row_inflation"),
                "reconciled expected and observed row inflation do not match")
        require(recon.get("publication_pointer_preserved") is True, "fault run did not preserve the publication pointer")

    pointer = bundle.json("data/published/CURRENT")
    require(pointer.get("run_id") == expected.get("published_run_id_after_fault"), "CURRENT does not select expected last-known-good run")
    require(pointer.get("run_id") == repeat_id, "CURRENT does not select the January repeat clean run")
    if fault:
        pub = fault.get("publication", {})
        require(pub.get("decision") == "blocked" and pub.get("pointer_before") == pub.get("pointer_after") == pointer.get("run_id"),
                "fault report publication fields are inconsistent with CURRENT")

    witness = bundle.json("reconciliation-witness.json")
    require(witness.get("source_report") == f"data/runs/{fault_id}/report.json", "witness points to the wrong report")
    deltas = fault.get("downstream_aggregate_deltas", []) if fault else []
    try:
        witness_groups = len(deltas)
        witness_rows = sum(int(item["trip_count_delta"]) for item in deltas)
        witness_revenue = sum((Decimal(item["revenue_delta"]) for item in deltas), Decimal("0"))
        require(witness.get("affected_daily_zone_groups") == witness_groups == recon.get("affected_daily_zone_groups"),
                "aggregate witness group count does not reconcile")
        require(witness.get("trip_count_delta") == witness_rows == recon.get("total_trip_count_delta"),
                "aggregate witness trip deltas do not reconcile")
        require(Decimal(witness.get("revenue_delta", "NaN")) == witness_revenue == Decimal(recon.get("total_revenue_delta", "NaN")),
                "aggregate witness revenue deltas do not reconcile")
        require(witness.get("all_average_fares_unchanged") is all(item["average_fare_unchanged"] for item in deltas),
                "aggregate witness average-fare result does not reconcile")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        errors.append(f"cannot recompute aggregate witness: {exc}")

    current_contract_match = None
    if repo_root is not None:
        repo_root = repo_root.resolve()
        try:
            current_contract_match = _contract_hash(lambda name: (repo_root / name).read_bytes()) == bundled_contract_hash
        except OSError:
            errors.append("current repository contract is missing or unreadable")

    return {"bundle_kind": bundle.kind, "valid": not errors, "errors": errors,
            "bundled_contract_sha256": bundled_contract_hash,
            "current_repository_contract_matches": current_contract_match}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="M1 evidence directory or ZIP archive")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="repository root for a separate current-contract comparison")
    args = parser.parse_args()
    try:
        result = verify_bundle(args.evidence, args.repo_root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile, jsonschema.ValidationError) as exc:
        print(f"FAIL  {exc}")
        sys.exit(1)
    for error in result["errors"]:
        print(f"FAIL  {error}")
    if result["current_repository_contract_matches"] is not None:
        print("INFO  current repository contract " + ("matches historical evidence" if result["current_repository_contract_matches"] else "differs from historical evidence"))
    print("RESULT:", "VALID EVIDENCE" if result["valid"] else "INVALID EVIDENCE")
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()

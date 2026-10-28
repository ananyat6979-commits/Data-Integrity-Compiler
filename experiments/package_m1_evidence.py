"""Create the compact, row-level-independent evidence bundle for M1."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalized_text_digest(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def combined_contract_hash(contract_dir: Path) -> str:
    parts = {"pipeline.yaml": normalized_text_digest(contract_dir / "pipeline.yaml"),
             "schema": normalized_text_digest(contract_dir / "tlc-yellow-v1.json")}
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="extracted Kaggle result folder")
    parser.add_argument("--destination", type=Path, default=Path("results/m1"))
    parser.add_argument("--historical-contract-dir", type=Path,
                        help="directory containing the exact contracts/pipeline.yaml and tlc-yellow-v1.json used for this run")
    parser.add_argument("--source-archive", type=Path,
                        help="exact source archive uploaded to Kaggle, for provenance hashing")
    parser.add_argument("--kaggle-notebook-version",
                        help="platform version identifier recorded from the run metadata")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve()
    destination = (root / args.destination).resolve() if not args.destination.is_absolute() else args.destination.resolve()
    if destination.exists():
        existing = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
        if existing - {"README.md", "expected.json"}:
            raise SystemExit(f"Refusing to overwrite an existing evidence package: {destination}")
    recon_path = source / "data" / "jan-2024-reconciliation.json"
    recon = json.loads(recon_path.read_text(encoding="utf-8-sig"))
    clean_id, fault_id = recon["clean_run_id"], recon["fault_run_id"]
    current = json.loads((source / "data" / "published" / "CURRENT").read_text(encoding="utf-8-sig"))
    fault_report = json.loads((source / "data" / "runs" / fault_id / "report.json").read_text(encoding="utf-8-sig"))
    clean_report = json.loads((source / "data" / "runs" / clean_id / "report.json").read_text(encoding="utf-8-sig"))
    repeat_id = current["run_id"]
    repeat_report = json.loads((source / "data" / "runs" / repeat_id / "report.json").read_text(encoding="utf-8-sig"))

    contract_dir = (args.historical_contract_dir.resolve() if args.historical_contract_dir else
                    source / "contracts" if (source / "contracts").is_dir() else root / "contracts")
    contract_hash = combined_contract_hash(contract_dir)
    if contract_hash != recon["contract_sha256"]:
        raise SystemExit("Repository contract does not match the contract hash in the Kaggle evidence")

    destination.mkdir(parents=True, exist_ok=True)
    (destination / "contracts").mkdir()
    (destination / "schemas").mkdir()
    shutil.copy2(contract_dir / "pipeline.yaml", destination / "contracts" / "pipeline.yaml")
    shutil.copy2(contract_dir / "tlc-yellow-v1.json", destination / "contracts" / "tlc-yellow-v1.json")
    report_schema = source / "schemas" / "report-v2.schema.json"
    if not report_schema.is_file():
        report_schema = root / "schemas" / "report-v2.schema.json"
    shutil.copy2(report_schema, destination / "schemas" / "report-v2.schema.json")

    paths = ["data/source-manifest.json", "data/jan-2024-reconciliation.json",
             "data/clean_report.json", "data/fault_report.json", "data/published/CURRENT"]
    paths.extend(str(p.relative_to(source)).replace("\\", "/") for p in (source / "data" / "clean-controls").glob("*.json"))
    for run_id in sorted({clean_id, repeat_id, fault_id}):
        paths.extend([f"data/runs/{run_id}/report.json", f"data/runs/{run_id}/manifest.json"])
    for relative in paths:
        src = source / Path(relative)
        if not src.is_file():
            raise SystemExit(f"Missing required Kaggle evidence file: {src}")
        target = destination / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    deltas = fault_report.get("downstream_aggregate_deltas", [])
    witness = {
        "witness_version": "m1-aggregate-witness-v1",
        "source_report": f"data/runs/{fault_id}/report.json",
        "affected_daily_zone_groups": len(deltas),
        "trip_count_delta": sum(int(item["trip_count_delta"]) for item in deltas),
        "revenue_delta": str(sum((Decimal(item["revenue_delta"]) for item in deltas), Decimal("0"))),
        "all_average_fares_unchanged": all(item["average_fare_unchanged"] for item in deltas),
    }
    (destination / "reconciliation-witness.json").write_text(json.dumps(witness, indent=2) + "\n", encoding="utf-8")
    expected = {
        "evidence_version": "m1-evidence-v1",
        "clean_run_id": clean_id,
        "repeat_clean_run_id": repeat_id,
        "fault_run_id": fault_id,
        "published_run_id_after_fault": current["run_id"],
        "contract_version": clean_report["contract_version"],
        "contract_sha256": contract_hash,
        "clean_trips_fingerprint": clean_report["logical_output_hashes"]["clean_trips"],
        "expected_injected_row_inflation": 50,
    }
    (destination / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")

    archive = args.source_archive.resolve() if args.source_archive else root / "experiments" / "kaggle_upload" / "data-integrity-compiler-source.zip"
    notebook = root / "experiments" / "kaggle_upload" / "kaggle_m1_validation.ipynb"
    try:
        tree_hash = subprocess.check_output(["git", "rev-parse", "m1-verified^{tree}"], cwd=root, text=True).strip()
    except subprocess.CalledProcessError:
        tree_hash = None
    sidecar = archive.with_suffix(".provenance.json")
    source_provenance_path = source / "data" / "provenance.json"
    if not source_provenance_path.is_file() and sidecar.is_file():
        source_provenance_path = sidecar
    if not source_provenance_path.is_file():
        raise SystemExit("Missing source provenance. Include the build sidecar and Kaggle notebook version metadata in the result export.")
    source_provenance = json.loads(source_provenance_path.read_text(encoding="utf-8"))
    actual_archive_hash = digest(archive) if archive.is_file() else None
    recorded_archive_hash = source_provenance.get("source_archive_sha256")
    if actual_archive_hash and recorded_archive_hash and actual_archive_hash != recorded_archive_hash:
        raise SystemExit("Source archive hash differs from the archive identified by the Kaggle run")
    provenance = {**source_provenance,
                  "m1_verified_tree_hash": tree_hash,
                  "source_archive_sha256": recorded_archive_hash or actual_archive_hash,
                  "notebook_sha256": digest(notebook) if notebook.is_file() else None,
                  "kaggle_notebook_version": args.kaggle_notebook_version or source_provenance.get("kaggle_notebook_version"),
                  "full_parquet_artifacts_included": False}
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    readme = (
        "# M1 historical evidence\n\n"
        "This bundle preserves the January clean controls and injected join-fault reports, manifests, source metadata, "
        "contract, report schema, and a compact aggregate witness. It excludes raw TLC inputs and materialized Parquet "
        "outputs. The verifier checks checksums, report and manifest consistency, contract identity, publication state, "
        "and the recorded aggregate sums. It cannot independently reproduce row-level results without the Parquet files.\n\n"
        "The Kaggle platform notebook version was not present in the downloaded export; the notebook content hash is "
        "recorded in `provenance.json`.\n"
    )
    (destination / "README.md").write_text(readme, encoding="utf-8")
    checksums = {str(p.relative_to(destination)).replace("\\", "/"): digest(p)
                 for p in sorted(destination.rglob("*")) if p.is_file()}
    (destination / "SHA256SUMS.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence bundle created at {destination}")


if __name__ == "__main__":
    main()

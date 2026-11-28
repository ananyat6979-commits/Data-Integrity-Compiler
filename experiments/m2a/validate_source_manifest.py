from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
from pathlib import Path
from typing import Any

import duckdb
import jsonschema

from dic.pipeline import build_v2_source_provenance, load_contract


MONTH_FILE = re.compile(r"yellow_tripdata_(\d{4}-\d{2})\.parquet$")


def discover_monthly_sources(raw_dir: Path, expected_months: list[str]) -> dict[str, Path]:
    if not raw_dir.is_dir():
        raise ValueError(f"Raw source directory does not exist: {raw_dir}")
    expected = {f"yellow_tripdata_{month}.parquet": month for month in expected_months}
    actual: dict[str, Path] = {}
    for path in raw_dir.iterdir():
        if path.is_file() and path.name.startswith("yellow_tripdata_") and path.suffix == ".parquet":
            actual[path.name] = path
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        raise ValueError(f"Monthly source inventory differs from contract; missing={missing}, extra={extra}")
    return {expected[name]: actual[name] for name in sorted(expected)}


def validate_source_manifest(root: Path, raw_dir: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    contract, _, contract_hash = load_contract(root, version="v2")
    audit_ref = contract["source_audit"]
    audit_path = root / audit_ref["path"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    sources = discover_monthly_sources(raw_dir, audit_ref["months"])
    entries = []
    for month, path in sources.items():
        sql_path = path.resolve().as_posix().replace("'", "''")
        with duckdb.connect(":memory:") as con:
            columns = [
                {"name": row[0], "type": str(row[1])}
                for row in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{sql_path}')").fetchall()
            ]
            row_count = int(con.execute(f"SELECT count(*) FROM read_parquet('{sql_path}')").fetchone()[0])
        provenance = build_v2_source_provenance(root, path, month, columns, row_count)
        record = next(item for item in audit["months"] if item["month"] == month)
        entries.append({
            "month": month,
            "file": path.name,
            "source_sha256": provenance["source_sha256"],
            "bytes": path.stat().st_size,
            "rows": row_count,
            "physical_schema_sha256": record["schema_signature"],
            "cohort_id": provenance["audit"]["cohort_id"],
            "status": "validated",
        })

    manifest = {
        "manifest_version": "dic-m2a-source-manifest-v1",
        "contract_id": contract["contract_id"],
        "contract_version": contract["contract_version"],
        "contract_sha256": contract_hash,
        "audit_sha256": audit_ref["sha256"],
        "audit_sha256_method": audit_ref["sha256_method"],
        "source_count": len(entries),
        "validation": "passed",
        "entries": entries,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _verify_manifest_document(root, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    return manifest


def _verify_manifest_document(root: Path, manifest: dict[str, Any]) -> None:
    schema_path = root / "schemas/m2a-source-manifest-v1.schema.json"
    jsonschema.validate(manifest, json.loads(schema_path.read_text(encoding="utf-8")))
    payload = dict(manifest)
    recorded_hash = payload.pop("manifest_sha256")
    observed_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if recorded_hash != observed_hash:
        raise ValueError("Source manifest SHA-256 does not match its contents")
    contract, _, contract_hash = load_contract(root, version="v2")
    audit_ref = contract["source_audit"]
    if manifest["contract_sha256"] != contract_hash:
        raise ValueError("Source manifest contract hash differs from the current v2 contract")
    if (manifest["audit_sha256"] != audit_ref["sha256"]
            or manifest["audit_sha256_method"] != audit_ref["sha256_method"]):
        raise ValueError("Source manifest audit pin differs from the current v2 contract")
    audit = json.loads((root / audit_ref["path"]).read_text(encoding="utf-8"))
    expected_by_month = {record["month"]: record for record in audit["months"]}
    entries = manifest["entries"]
    if [entry["month"] for entry in entries] != audit_ref["months"]:
        raise ValueError("Source manifest month inventory differs from the pinned audit")
    for entry in entries:
        expected = expected_by_month[entry["month"]]
        if (entry["file"] != expected["file"] or entry["source_sha256"] != expected["sha256"]
                or entry["bytes"] != expected["bytes"] or entry["rows"] != expected["rows"]
                or entry["physical_schema_sha256"] != expected["schema_signature"]
                or entry["cohort_id"] != expected["cohort_id"] or entry["status"] != "validated"):
            raise ValueError(f"Source manifest evidence disagrees with the audit for {entry['month']}")


def verify_source_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_manifest_document(root.resolve(), manifest)
    return {"validation": "valid_internal_evidence", "source_count": manifest["source_count"],
            "manifest_sha256": manifest["manifest_sha256"],
            "raw_files_reopened": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate all audited TLC monthly sources against contract v2")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify-only", action="store_true",
                        help="verify a previously generated compact manifest without reopening raw parquet")
    parser.add_argument("--manifest", type=Path,
                        help="manifest path for --verify-only")
    args = parser.parse_args()
    if args.verify_only:
        if args.manifest is None:
            parser.error("--manifest is required with --verify-only")
        result = verify_source_manifest(args.root, args.manifest)
    else:
        if args.raw is None or args.out is None:
            parser.error("--raw and --out are required unless --verify-only is selected")
        result = validate_source_manifest(args.root, args.raw, args.out)
        result = {"validation": result["validation"], "source_count": result["source_count"],
                  "manifest_sha256": result["manifest_sha256"], "output": str(args.out),
                  "raw_files_reopened": True}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

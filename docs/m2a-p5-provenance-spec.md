# M2a Contract v2 Provenance Specification

**Status:** P5 implementation specification for review. This document does not freeze contract v2. The v2 YAML and schema JSON must be implemented and validated before Phase 1. M1 contracts, hashes, commands, and evidence remain unchanged.

## Purpose

Contract v2 must preserve both the physical schema observed in each monthly TLC file and the semantic schema used by the pipeline. Normalization is a read-layer view. It must never overwrite or conceal the source column names, physical types, file identity, or audit basis.

## Pinned audit reference

Contract v2 YAML will reference the audit artifact using a repository-relative path and its SHA-256:

- Path: `experiments/m2a/audit/schema_audit_2022-01_2025-12.json`
- SHA-256: `1c0ebcf027fd1c47e086eaeaa276b5f1e53b52853addecba633208d77e0afbdb`.
- Audit version: 1
- Coverage: 48 monthly files, 2022-01 through 2025-12

The SHA-256 field is part of the v2 YAML, so the contract hash changes if the pinned audit identity changes. The audit JSON is not itself added as another direct contract-hash input. A mismatch between the file and its pinned SHA-256 must fail contract loading with a clear integrity error. A re-audit must be explicitly versioned and reviewed, then the v2 YAML reference and contract hash updated together.

## Per-file provenance record

For every input month, the run manifest must contain exactly one source provenance record with:

- Contract version and source month.
- Repository-independent logical source name, such as `yellow_tripdata_2022-01.parquet`. Do not embed a machine-specific absolute path.
- SHA-256 of the exact source file bytes, byte size, and source row count.
- Schema audit version, pinned audit artifact path and SHA-256, audit cohort ID, and recorded schema signature.
- The complete original column list in source order. Each entry contains the exact case-sensitive source name and the physical type string observed for that month.
- The normalized semantic schema identifier and the explicit name and type mapping used by the reader.

Use values from the matching month record and cohort definition in the pinned audit. Do not infer an original schema from a later month, from the normalized schema, or from a hand-maintained year label. Preserve original and normalized schemas as separate fields.

## Validation rules

The contract loader and manifest validator must reject:

1. An absent or changed audit file, a mismatched audit SHA-256, or an unsupported audit version.
2. Missing, duplicate, or out-of-range month records. The intended input inventory is exactly 48 months from 2022-01 through 2025-12.
3. A source file whose bytes, byte size, row count, physical column names, physical types, cohort ID, or schema signature do not match the pinned audit.
4. A semantic mapping that silently drops a source column, merges two source columns, or changes a physical type without an explicit mapping declared in contract v2.
5. Provenance records containing machine-specific absolute paths.

For each run, validate the bytes and schema of the actual file being read against its manifest record before transformation. Report the observed schema and normalized schema separately. Never substitute the audit's row count or schema for inspection of the actual run input.

## Hash boundaries and historical compatibility

The v2 contract hash is computed from `contracts/v2/pipeline.yaml` and `contracts/v2/tlc-yellow-v2.json` using the established newline-normalized procedure. The YAML pins the audit artifact's SHA-256. The audit artifact remains outside the direct hash pair, and its digest is verified independently.

The v1 contract loader continues to default to v1. The complete v1 contract hash remains `947e696d07ed07482a9d542febf5a345693e5a1a29b4db5875dc0fbdeca3c953`. No v2 provenance change may alter M1 evidence or its historical verification.

## P5 completion gate

P5 is complete only when:

- The v2 YAML declares the pinned audit reference and normalization mappings.
- The contract loader verifies the audit digest and rejects an altered or missing audit.
- A v2 run manifest records original and normalized schemas for every source month.
- A validation check proves the manifest matches all 48 audit month records and the actual source files.
- M1 hash and evidence verification remain unchanged.

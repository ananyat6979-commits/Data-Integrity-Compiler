# M2a Contract v2 Implementation Status

**Status:** Initial implementation proposal on `m2a-contract-v2-foundation`. This is not merged, does not freeze Phase 0, and is not a verified M2a release.

## Included in this proposal

- `contracts/v2/pipeline.yaml` and `contracts/v2/tlc-yellow-v2.json` define the semantic schema, audited source cohort mappings, the D2 one-day half-open pickup window, and the distinct exact and distribution month ranges.
- `load_contract(root, version="v1")` preserves the v1 default. Selecting v2 validates the contract/schema pair, the pinned audit digest and version, the complete 48-month inventory, cohort signatures, explicit physical type mappings, and required semantic columns. The audit digest is UTF-8 JSON with newline normalization, explicitly declared in the contract and stable across Windows and Linux.
- `build_v2_source_provenance` validates a source file's exact bytes, size, row count, ordered physical schema and cohort against the pinned audit. It returns portable provenance without machine-specific paths and keeps physical and normalized schemas separate.
- The run API and CLI accept `contract_version="v2"` or `--contract-version v2`; they continue to default to v1. A v2 run normalizes source column names from the contract and applies the D2 one-day half-open pickup window as a first-failure rejection rule with per-rule counts, but does not alert or fail the month for spill. Provenance-valid synthetic Parquet files from each of the three physical schema cohorts have passed through the actual worker subprocess, report validation, materialization and publication path.
- An independent Polars reference module now covers ingestion reconciliation, cleaning and first-failure counts, timestamp offsets, join cardinality/key behavior, and sum/mean aggregation. Hand-computed fixtures cover the reference transformations for all eight catalog mechanisms and directly applicable threshold/offset values. These are oracle unit fixtures, not the catalog's full severity and seed matrix. Polars 1.44.2 and its runtime are isolated in a separate pinned oracle dependency file and installed in CI.
- Focused tests cover v1 hash compatibility, v2 contract hash sensitivity, audit tampering and missing-audit rejection, stable LF/CRLF pins, unsupported hash methods, invalid normalization, provenance schema separation, D2 boundary behavior, source-manifest validation, independent oracle fixtures, and catalog matrix structure. The full local suite passes. CI for the latest source-manifest and oracle changes is pending.
- The v1 contract files are unchanged. Existing commands keep the v1 default. The explicit command `dic run --month 2023-01 --contract-version v2` selects the v2 path. No M2a detector, fault hook, distribution threshold, or experimental evaluation is enabled by this proposal.

## Still required before Phase 1 acceptance

- The 48-file source manifest was generated from the local raw directory and all files matched pinned SHA-256, byte size, row count, physical schema and cohort. Its manifest digest is `11db74829a7820870666a5ada355ce3f684366ec038446ebd9647b9996283b71`. Run `python experiments/m2a/validate_source_manifest.py --raw data/raw --out experiments/m2a/audit/source_manifest_v2.json` to reopen and validate the raw files again. The compact `--verify-only` mode checks the report schema, manifest digest, contract hash and audit consistency, but does not reopen Parquet or independently reproduce row-level results.
- Run the v2 command end to end on an audited full-data file and compare its outputs with the independent Polars references before claiming Phase 1 acceptance. The full 48-file source identity audit passed, but the production-scale v2 pipeline has not yet run.
- Implement the private harness-owned stage hooks and injectors for the eight catalog mechanisms. Keep execution-specific labels and mutation parameters outside the detector bundle.
- Implement and freeze the production-available integrity checks from independently justified rules, then exercise detection and diagnosis methods separately. Distribution alerts remain disabled under protocol v1.2 and are not a blocker for the current scope.
- Build resumable per-case evaluation, metrics and the results verifier only after hook and detector fixtures pass. M2a remains unfrozen and unevaluated.

Protocol v1.2 and the D9 deferral are adopted on `main`; the full M2a protocol remains unfrozen until the remaining oracle and catalog review gates pass.

No M1 evidence or tag is changed by this proposal.

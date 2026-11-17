# M2a Contract v2 Implementation Status

**Status:** Initial implementation proposal on `m2a-contract-v2-foundation`. This is not merged, does not freeze Phase 0, and is not a verified M2a release.

## Included in this proposal

- `contracts/v2/pipeline.yaml` and `contracts/v2/tlc-yellow-v2.json` define the semantic schema, audited source cohort mappings, the D2 one-day half-open pickup window, and the distinct exact and distribution month ranges.
- `load_contract(root, version="v1")` preserves the v1 default. Selecting v2 validates the contract/schema pair, the pinned audit digest and version, the complete 48-month inventory, cohort signatures, explicit physical type mappings, and required semantic columns. The audit digest is UTF-8 JSON with newline normalization, explicitly declared in the contract and stable across Windows and Linux.
- `build_v2_source_provenance` validates a source file's exact bytes, size, row count, ordered physical schema and cohort against the pinned audit. It returns portable provenance without machine-specific paths and keeps physical and normalized schemas separate.
- The run API and CLI accept `contract_version="v2"` or `--contract-version v2`; they continue to default to v1. A v2 run normalizes source column names from the contract and applies the D2 one-day half-open pickup window as a first-failure rejection rule with per-rule counts, but does not alert or fail the month for spill.
- Focused tests cover v1 hash compatibility, v2 contract hash sensitivity, audit tampering and missing-audit rejection, stable LF/CRLF pins, unsupported hash methods, invalid normalization, provenance schema separation, D2 boundary behavior and catalog matrix structure. The full test suite passes locally. The four CI matrix jobs passed for the cross-platform pin fix; CI for the newer D2 run-path changes is pending.
- The v1 contract files are unchanged. Existing commands keep the v1 default. The explicit command `dic run --month 2023-01 --contract-version v2` selects the v2 path. No M2a detector, fault hook, distribution threshold, or experimental evaluation is enabled by this proposal.

## Still required before Phase 1 acceptance

- Produce and verify a compact source manifest against all 48 actual source files and the audit, rather than relying on the single local provenance smoke check. The v2 runner validates its own selected source before materialization.
- Validate reference-stage calculations against the hand-computed fixtures in the oracle specification.
- Resolve P4 calibration before enabling distribution alerts. This proposal sets no thresholds.
- End-to-end test the v2 command with audited full-data files, including publication behavior, before claiming Phase 1 acceptance.

Protocol v1.2 and the D9 deferral are adopted on `main`; the full M2a protocol remains unfrozen until the remaining oracle and catalog review gates pass.

No M1 evidence or tag is changed by this proposal.

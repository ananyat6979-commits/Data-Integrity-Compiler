# M2a Contract v2 Implementation Status

**Status:** Initial implementation proposal on `m2a-contract-v2-foundation`. This is not merged, does not freeze Phase 0, and is not a verified M2a release.

## Included in this proposal

- `contracts/v2/pipeline.yaml` and `contracts/v2/tlc-yellow-v2.json` define the semantic schema, audited source cohort mappings, the D2 one-day half-open pickup window, and the distinct exact and distribution month ranges.
- `load_contract(root, version="v1")` preserves the v1 default. Selecting v2 validates the contract/schema pair, the pinned audit digest and version, the complete 48-month inventory, cohort signatures, explicit physical type mappings, and required semantic columns.
- `build_v2_source_provenance` validates a source file's exact bytes, size, row count, ordered physical schema and cohort against the pinned audit. It returns portable provenance without machine-specific paths and keeps physical and normalized schemas separate.
- Focused tests cover v1 hash compatibility, v2 contract hash sensitivity, audit tampering and missing-audit rejection, invalid normalization, provenance schema separation, and catalog matrix structure. The existing suite also passes with the new loader defaulting to v1.
- The v1 contract files are unchanged. The existing pipeline continues to call the v1 default. No M2a detector, fault hook, distribution threshold, or publication behavior is enabled by this proposal.

## Still required before Phase 1 acceptance

- Wire the v2 contract into an explicit M2a run entry point and apply the D2 row-level rejection rule with first-failure counts. The M1 command remains on v1 unless a caller explicitly selects v2.
- Validate manifests against all 48 actual source files and the audit, rather than relying on the single local provenance smoke check.
- Validate reference-stage calculations against the hand-computed fixtures in the oracle specification.
- Resolve P4 calibration before enabling distribution alerts. This proposal sets no thresholds.
- Implement the explicit M2a run entry point, date-window rejection and first-failure accounting before claiming v2 pipeline behavior.

Protocol v1.2 and the D9 deferral are adopted on `main`; the full M2a protocol remains unfrozen until the remaining oracle and catalog review gates pass.

No M1 evidence or tag is changed by this proposal.

# M2a Independent Oracle Specification v1

**Status:** Phase 0 review draft. This document defines the proposed reference calculations before detector or injector implementation. Phase 1 must first pass hand-computed fixture checks below. The reference code must not import pipeline transformations or use the harness fault hooks.

## Common oracle rules

- Pin the second engine to `polars==1.44.2`; the pipeline engine remains DuckDB 1.2.2. Polars is a separate Parquet reader and expression/grouping implementation. [Polars release record](https://github.com/pola-rs/polars/releases/tag/py-1.44.2).
- Read immutable source files and stage outputs by explicit paths. Do not read detector input bundles, injector labels, mutation parameters, or evaluator-only expected rows from the detector process.
- For each eligible clean month, independently calculate source and per-stage row counts, null counts on declared columns, exact fare sums using decimal arithmetic, and join multiplicities. Apply applicable TLC data-dictionary column/type/date/range checks.
- Record the properties each oracle can establish. An incomplete oracle cannot score unobserved properties.
- Keep fault hooks in the harness around the production stage boundary. Reference stage functions accept only their declared inputs and configuration and cannot call the hook registry.
- Validate every reference transformation against its hand-computed fixture before use. A test compares the complete canonical expected output, not only a final aggregate.

## Per-mechanism oracle specifications

| Mechanism | Independent calculation | Hand-computed validation fixture and acceptance | Measurable properties |
|---|---|---|---|
| `ingestion_duplicate_records` | Compare input row hashes and immutable source records, then count and sum with Polars. | Three source rows, one repeated exactly: expected input count 4, unique source-row count 3, and repeated fare contributes twice. | Exact duplicate rows, row inflation, fare-sum delta. |
| `ingestion_missing_records` | Match input row hashes and ordinals to the immutable source; Polars independently sums affected records. | Five rows with one removed: exact missing ordinal, count delta 1, and hand-summed group fare delta. | Missing rows, affected keys and fare sums. |
| `cleaning_fare_threshold` | Independently evaluate the declared row-level predicate in Polars from raw values. | Fares -1, 0, 0.5, 4, 10, null, with hand-written keep/drop masks for thresholds 1, 5, and 20. Exact mask equality required. | Retained ordinals, rejected rows, exact fare sums. |
| `cleaning_timestamp_offset` | Compare source timestamps and pickup-date keys to an independent Polars expression and TLC local-time semantics. | Local timestamps 00:15, 12:00, 23:45 with hand-calculated date assignments for offsets +15, +60, +180 minutes. Exact timestamp and date equality required. | Timestamp mismatches, date-key changes, per-date row and fare deltas. |
| `join_duplicate_lookup_key` | Compute lookup-key multiplicities and join expected multiplicities in Polars. | Two trips on key 1, one lookup row; duplicate the lookup row once: exact expected joined row count 4 and key multiplicity 2. | Duplicate keys, join inflation and downstream group deltas. |
| `join_wrong_key` | Independently join raw trip rows to lookup attributes on declared `PULocationID`; compare row-level attributes. | Three trips with distinct pickup/dropoff IDs and hand-authored labels; exact expected pickup label for each row. | Wrong attributes, mismatched key count, affected aggregates. |
| `aggregation_sum_to_mean` | Group clean-stage rows in Polars and compute exact decimal fare sums independently. | Groups [10,20], [5], [2,4,6]; expected sums 30, 5, 12 and means 15, 5, 4. Exact output match required. | Mismatched groups and exact per-group fare-sum deltas. |
| `aggregation_wrong_grouping_key` | Recompute groups from pickup service date and pickup zone in Polars, retaining row ordinals for key comparison. | Cross-midnight trips with explicitly listed pickup and dropoff dates; expected group keys and counts are hand-enumerated. | Mismatched keys, per-group counts and fare sums. |

## Reference-stage validation gate

Before a reference is eligible for diagnosis or replay, its fixture test must pass for all low, medium, and high parameter values that apply. Include nulls, empty input, ties, boundary timestamps, unmatched keys, and decimal values. Compare ordered canonical business rows and independently hand-calculate all listed aggregates. Reference code and fixture hashes are frozen with the Phase 3 experiment artifacts. A later reference defect requires a new frozen version and a new untouched held-out evaluation.

Counterfactual replay is eligible only for mechanisms with an independent trusted transformation or input version. For data-locus faults, replacing transformation code alone does not repair the input. For code-locus faults, replacing a trusted input alone does not repair the transformation. Score each attempted intervention against the independent oracle and report residual mismatches.

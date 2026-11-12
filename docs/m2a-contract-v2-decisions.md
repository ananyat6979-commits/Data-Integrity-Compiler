# M2a Contract v2 Decision Note

**Status:** D1 through D8 are owner decisions. D2, D3, D4 and D7 are recorded here with the clarifications below. Contract v2 and the M2a protocol are not locked or frozen: P3, P4, P5, independent oracle definitions, catalog review, and implementation details remain. The experimental freeze occurs only at `m2a-frozen`.
**Evidence:** experiments/m2a/audit/schema_audit_2022-01_2025-12.json and experiments/m2a/audit/paired_null_audit_2022-01_2025-12.json. Both cover 48 monthly Yellow Taxi files from 2022-01 to 2025-12 and record source SHA-256 values. The paired-null report matches the schema audit on every monthly source hash and row count. The 2024-01, 2024-02 and 2025-01 hashes match the M1 evidence.
**Scope:** contract v2 is a new contract. M1 evidence stays tied to the M1 contract hash; v2 files live under `contracts/v2/` so the v1 hash cannot change.

## 1. What the audit established

| Cohort | Months | Columns | Notes |
|---|---|---|---|
| C1 | 2022-01 to 2023-01 (13) | 19 | `airport_fee` lowercase; IDs `BIGINT`; `passenger_count`, `RatecodeID` `DOUBLE` |
| C2 | 2023-02 to 2024-12 (23) | 19 | `Airport_fee`; IDs `INTEGER`; `passenger_count`, `RatecodeID` `BIGINT` |
| C3 | 2025-01 to 2025-12 (12) | 20 | adds `cbd_congestion_fee` |

- Null `PULocationID`, `DOLocationID`, `fare_amount` and both timestamps: zero in all 48 months. Pickup location IDs span 1 to 265 in every month.
- Pickups outside the file's month occur in all 48 months. Most are boundary spill within one day. Pickups more than one day outside the month total 612 (2022), 323 (2023), 49 (2024) and 8 (2025). The worst months are 2022-06 (447 rows, 0.013%) and 2023-03 (158 rows, 0.005%). The 2024-06 file contains a pickup dated 2026-06-26.
- Negative-fare share rises from about 0.5% (2022-01) to 2.1% (2024-12), 4.2% (2025-01), 9.5% (2025-11), then falls to 1.1% (2025-12).
- Non-positive distance share jumps from 2.0% (2023-08) to 3.5% (2023-09 and 2023-10), then declines.

## 2. Proposed decisions

**D1. Schema cohorts (DECIDED: yes).** Treat C1 and C2 as one *semantic* cohort: match column names case-insensitively, canonical `INTEGER` for ID columns, canonical `BIGINT` for `passenger_count` and `RatecodeID`. Normalization is applied when reading; contract v2 provenance preserves each file's original column names and types, so the historical schema differences are never erased. Basis: P1 (section 5) found no non-integral and no NaN values in either `DOUBLE` column across the 13 C1 months and all IDs fit `INTEGER`; P1b (section 6) found no discontinuity at the boundary (null share 2.34% in 2023-01, 2.64% in 2023-02). The paired-null report confirms zero one-sided-null rows and zero NaNs across all 48 files.

**D2. Date coverage (DECIDED with clarifications).** Apply the rule per row, with rule ID `far_out_pickup` and per-month rejected-row counts. Do not fail an entire month. For a source file labeled month `M`, accept pickup timestamps in the half-open interval `[M start - 1 day, next month start + 1 day)`. This matches the schema audit. Boundary spill within that interval is counted and reported, and never alerts. Rows outside it are rejected and counted, but the month itself is not failed. The far-out count is excluded from distribution features because it falls year over year (612, 323, 49, 8). Recompute the January 2024 regression expectation under v2; do not assume M1's 50-row inflation carries over.

**D3. 2025 regime (DECIDED).** The 2025 regime begins with the `2025-01` source file, even though congestion pricing began on January 5. Exact checks cover 36 months (2023-01 through 2025-12); distribution checks cover 24 months (2023-01 through 2024-12). Keep these denominators separate and record both in report metadata. No distribution alerts run for 2025. Fare-sign and rejection-rate checks are excluded from distribution alerts because the negative-fare share drifts within 2025.

**D4. Source classification and scoring (DECIDED).** Recompute statistics independently from source files, but treat recomputation as evidence of computational consistency, not proof that a statistic is anomalous. Classify each alert as: (1) pipeline-origin discrepancy, where independent recomputation disagrees with pipeline output; (2) source-origin alert meeting an anomaly criterion registered before detector execution and independently of detector outputs; or (3) source-origin alert not meeting that criterion. A correctly flagged pipeline-origin discrepancy is an integrity detection, not a false positive; incorrect source attribution is scored separately. Category 2 is a correct source-anomaly detection. Category 3 is a false positive. Unresolved origin or anomaly status is uncertain/abstained and outside ordinary binary scoring. Report all categories separately. The headline false-positive rate is the run-level rate on independently verified non-anomalous clean runs; alerts on those runs count as false positives. Report pipeline-origin detections and source-attribution errors separately. Register anomaly criteria before detector outputs are seen.

**D5. Control-month evaluation (DECIDED: yes).** Score the 24 eligible months (2023-01 to 2024-12) walk-forward. Each scored month uses only its preceding 12 eligible months from the same semantic cohort and operating regime; no later month enters its baseline, and a month with fewer than 12 such predecessors is ineligible. The 2022 months are used only for debugging and warm-up. The detector's rule form and constants are frozen before any further inspection of monthly statistics. The owner has already seen aggregate counts for all 48 months; this is disclosed under threats to validity.

**D6. Fault-hosting month (DECIDED: yes).** Keep 2024-01 as the fixed fault-hosting month for every comparison method, for continuity with M1. Maintain separate clean and fault-injected variants of 2024-01: injected variants never enter baseline construction, threshold selection or clean-control scoring. Limitation: all fault executions share one host month, so results say nothing about month-to-month variation in fault detectability.

**D7. Versioning (DECIDED).** The contract-loader change for v2 will take an explicit contract version and default to v1, preserving existing M1 command behavior. Pin the complete v1 hash (`947e696d07ed07482a9d542febf5a345693e5a1a29b4db5875dc0fbdeca3c953`) in a regression test and retain valid M1 evidence. Contract v2 is `contracts/v2/pipeline.yaml` plus `contracts/v2/tlc-yellow-v2.json`, with the established newline-normalized hashing. The v2 YAML will reference the audited source schemas by SHA-256. Keep the audit file outside the contract-hash dependency chain unless it is explicitly versioned. Required v2 checks include cleaning retention completeness and join-key verification. Do not edit the v1 contract or its historical evidence.

**D8. Feature policy for distribution checks (DECIDED: yes).** The audit shows many monthly rate features drift inside the eligible range, so a level-based baseline would alert on genuine drift, not pipeline faults:
- The null share of `passenger_count` and `RatecodeID` (identical in each month) is about 2.6% to 3.1% from 2023-02 to 2023-08, 4.0% to 5.3% from 2023-09 to 2024-01, 6.2% in 2024-02, then 11.9% in 2024-03 and 8.7% to 13.3% for the rest of 2024.
- The negative-fare share rises steadily from 0.5% (2022-01) to 2.1% (2024-12); the non-positive distance share has a 2023 episode; the far-out pickup count falls each year.

Decision: exclude these drifting rate and null-share features from distribution alerts (null shares of `passenger_count` and `RatecodeID`, negative-fare share, non-positive-distance share, far-out pickup count). Distribution checks use within-month shape features (for example hour-of-day and weekday-by-hour profiles, pickup-zone mix, fare-per-mile relation) compared by a trend-robust distance. The feature definitions, the distance function and the alert thresholds are defined and frozen before held-out evaluation (P4); 2022 warm-up data is used for stability checks. Exact reconciliation checks are unaffected, because they compare against independent recomputation from the same file and not against history. Disclosure: this feature policy was informed by previously inspected monthly statistics (the null-share series and aggregate counts); it is not blind and must not be described as blind.

## 3. Consequences for denominators

- Exact-reconciliation controls: 36 months (2023-01 to 2025-12), by D3.
- Distribution-alert eligible months: 24 (2023-01 to 2024-12), by D3 and D5. All 12 months of 2025 are ineligible. Which features can alert is governed by D8.
- Zero alerts in 24 eligible months still leaves a 95% upper bound of about 12 to 14% on the false-alarm rate.

## 4. Outstanding prerequisites

- **P1, P1b (done).** See sections 5 and 6.
- **P2 (column comparison complete with documented limits).** The review is recorded in `docs/m2a-contract-v2-data-dictionary-review.md`, including all 20 audit columns, cohort spellings/types, field meanings and evidence limits.
- **P3.** Start a simple per-task hours log now. Earlier Phase 0 and schema-audit time was not logged and will not be reconstructed. Record hours for remaining work for the November 24 progress review.
- **P4 (draft prepared, not complete).** Proposed features, distance, and 2022-only threshold derivation are documented in `docs/m2a-distribution-checks-p4-draft.md`. Numeric thresholds remain unset until the independent source review classifies eligible 2022 months. Review and hash the calibration artifact before any detector code is run on 2023 or 2024 months.
- **P5.** Record the original source column names and types per file in contract v2 provenance (D1), next to the normalized semantic schema.

## 5. P1 result (months 2022-01 to 2023-01)

- Non-integral values in `passenger_count` and `RatecodeID`: 0 in all 13 months. NaN values: 0 in all 13 months.
- `passenger_count` ranges 0 to 9 and `RatecodeID` ranges 1 to 99 (99 is a documented unknown code); `VendorID` 1 to 6; `PULocationID` and `DOLocationID` 1 to 265. All fit `INTEGER`.
- `passenger_count` and `RatecodeID` have identical null counts in each month (for example 71,503 in 2022-01), so the nulls occur together in the same rows. Null share by month: 2.90%, 3.41%, 3.25%, 3.30%, 3.61%, 3.72%, 3.31%, 2.96%, 3.66%, 3.62%, 3.75%, 3.72%, then 2.34% in 2023-01.
- Conclusion: the C1 to C2 type change is a lossless widening for the values present.

## 6. P1b result (null share of `passenger_count` and `RatecodeID`, months 2023-02 to 2024-12)

The two columns have identical null shares in every month: 2.64%, 2.57%, 2.76%, 2.90%, 3.02%, 2.93%, 3.11% (2023-02 to 2023-08); 4.93%, 4.40%, 3.97%, 5.33% (2023-09 to 2023-12); 4.73%, 6.17%, 11.90%, 11.63%, 10.87%, 11.61%, 9.07%, 8.68%, 13.31%, 10.27%, 10.25%, 8.89% (2024-01 to 2024-12). There is no jump at the C1 to C2 boundary, but the share roughly doubles between 2024-02 and 2024-03 and stays elevated. The paired-null report includes 2025 row-level null and NaN counts, but 2025 remains excluded from D5 distribution-alert scoring.

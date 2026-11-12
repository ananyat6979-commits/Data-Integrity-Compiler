# M2a Contract v2 Decision Note

**Status:** D1, D5, D6 and D8 are decided by the owner (recorded in this PR). D2, D3, D4 and D7 remain proposals. Contract v2 and the M2a protocol are not frozen: section 4 lists what remains, and oracle definitions and implementation details still need their own review.
**Evidence:** `experiments/m2a/audit/schema_audit_2022-01_2025-12.json` (48 monthly Yellow Taxi files, 2022-01 to 2025-12, SHA-256 per file; the 2024-01, 2024-02 and 2025-01 hashes equal those recorded in the M1 evidence).
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

**D1. Schema cohorts (DECIDED: yes).** Treat C1 and C2 as one *semantic* cohort: match column names case-insensitively, canonical `INTEGER` for ID columns, canonical `BIGINT` for `passenger_count` and `RatecodeID`. Normalization is applied when reading; contract v2 provenance preserves each file's original column names and types, so the historical schema differences are never erased. Basis: P1 (section 5) found no non-integral and no NaN values in either `DOUBLE` column across the 13 C1 months and all IDs fit `INTEGER`; P1b (section 6) found no discontinuity at the boundary (null share 2.34% in 2023-01, 2.64% in 2023-02).

**D2. Date coverage.** Boundary spill (pickup within one day of the file's month) is benign: counted and reported, never an alert. Rows more than one day outside the month are `far_out_pickup` source anomalies. Contract v2 adds a cleaning rule that rejects them under its own rule ID, with per-month counts; the v2 retention-completeness check covers it. M1 has no date rule, so these rows currently reach `daily_zone_metrics` as stray dates. The far-out count must not be used as a distribution feature: it falls year over year (612, 323, 49, 8).

**D3. 2025 regime.** 2025 is its own regime (congestion pricing plus a new column). Exact reconciliation checks run; distribution alerts do not. Fare-sign and rejection-rate checks are excluded from any distribution alert, because the negative-fare share drifts within 2025.

**D4. Genuine source anomaly versus false alarm.** An alert counts as a false alarm only when independent recomputation from the source files (Polars) shows no anomaly against the declared rules. If the same surge appears in the source (e.g. the Sept to Nov 2023 distance episode), the alert is a correct source-anomaly detection. Decide this rule now, before any detector output is seen.

**D5. Control-month evaluation (DECIDED: yes).** Score the 24 eligible months (2023-01 to 2024-12) walk-forward. Each scored month uses only its preceding 12 eligible months from the same semantic cohort and operating regime; no later month enters its baseline, and a month with fewer than 12 such predecessors is ineligible. The 2022 months are used only for debugging and warm-up. The detector's rule form and constants are frozen before any further inspection of monthly statistics. The owner has already seen aggregate counts for all 48 months; this is disclosed under threats to validity.

**D6. Fault-hosting month (DECIDED: yes).** Keep 2024-01 as the fixed fault-hosting month for every comparison method, for continuity with M1. Maintain separate clean and fault-injected variants of 2024-01: injected variants never enter baseline construction, threshold selection or clean-control scoring. Limitation: all fault executions share one host month, so results say nothing about month-to-month variation in fault detectability.

**D7. Versioning.** Contract v2 = `contracts/v2/pipeline.yaml` plus `contracts/v2/tlc-yellow-v2.json`, with the existing newline-normalized hash. The v2 checks required by the catalog (cleaning retention completeness; join-key verification) are part of v2 and frozen before detector work.

**D8. Feature policy for distribution checks (DECIDED: yes).** The audit shows many monthly rate features drift inside the eligible range, so a level-based baseline would alert on genuine drift, not pipeline faults:
- The null share of `passenger_count` and `RatecodeID` (identical in each month) is about 2.6% to 3.1% from 2023-02 to 2023-08, 4.0% to 5.3% from 2023-09 to 2024-01, 6.2% in 2024-02, then 11.9% in 2024-03 and 8.7% to 13.3% for the rest of 2024.
- The negative-fare share rises steadily from 0.5% (2022-01) to 2.1% (2024-12); the non-positive distance share has a 2023 episode; the far-out pickup count falls each year.

Decision: exclude these drifting rate and null-share features from distribution alerts (null shares of `passenger_count` and `RatecodeID`, negative-fare share, non-positive-distance share, far-out pickup count). Distribution checks use within-month shape features (for example hour-of-day and weekday-by-hour profiles, pickup-zone mix, fare-per-mile relation) compared by a trend-robust distance. The feature definitions, the distance function and the alert thresholds are defined and frozen before held-out evaluation (P4); 2022 warm-up data is used for stability checks. Exact reconciliation checks are unaffected, because they compare against independent recomputation from the same file and not against history. Disclosure: this feature policy was informed by previously inspected monthly statistics (the null-share series and aggregate counts); it is not blind and must not be described as blind.

## 3. Consequences for denominators

- Exact-reconciliation controls: 36 months (2023 to 2025).
- Distribution-alert eligible months: 24 (2023 and 2024), by D1 and D5. All 12 months of 2025 are ineligible. Which features can alert is governed by D8.
- Zero alerts in 24 eligible months still leaves a 95% upper bound of about 12 to 14% on the false-alarm rate.

## 4. Outstanding prerequisites

- **P1, P1b (done).** See sections 5 and 6.
- **P2.** Review the TLC data dictionary against the audit for the columns contract v2 will declare, and record any column whose meaning changed between cohorts.
- **P3.** Record the hours spent on each Phase 1 task from now on (needed for the November 24 decision).
- **P4.** Define and freeze the within-month shape features, the trend-robust distance function and the alert thresholds, including how the thresholds are derived, using the 2022 warm-up months only for stability checks. This must be written down before any detector code is run on 2023 or 2024 months.
- **P5.** Record the original source column names and types per file in contract v2 provenance (D1), next to the normalized semantic schema.

## 5. P1 result (months 2022-01 to 2023-01)

- Non-integral values in `passenger_count` and `RatecodeID`: 0 in all 13 months. NaN values: 0 in all 13 months.
- `passenger_count` ranges 0 to 9 and `RatecodeID` ranges 1 to 99 (99 is a documented unknown code); `VendorID` 1 to 6; `PULocationID` and `DOLocationID` 1 to 265. All fit `INTEGER`.
- `passenger_count` and `RatecodeID` have identical null counts in each month (for example 71,503 in 2022-01), so the nulls occur together in the same rows. Null share by month: 2.90%, 3.41%, 3.25%, 3.30%, 3.61%, 3.72%, 3.31%, 2.96%, 3.66%, 3.62%, 3.75%, 3.72%, then 2.34% in 2023-01.
- Conclusion: the C1 to C2 type change is a lossless widening for the values present.

## 6. P1b result (null share of `passenger_count` and `RatecodeID`, months 2023-02 to 2024-12)

The two columns have identical null shares in every month: 2.64%, 2.57%, 2.76%, 2.90%, 3.02%, 2.93%, 3.11% (2023-02 to 2023-08); 4.93%, 4.40%, 3.97%, 5.33% (2023-09 to 2023-12); 4.73%, 6.17%, 11.90%, 11.63%, 10.87%, 11.61%, 9.07%, 8.68%, 13.31%, 10.27%, 10.25%, 8.89% (2024-01 to 2024-12). There is no jump at the C1 to C2 boundary, but the share roughly doubles between 2024-02 and 2024-03 and stays elevated. 2025 has not been audited for this feature.

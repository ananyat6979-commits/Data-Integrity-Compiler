# M2a Contract v2 Decision Note

**Status:** Proposed draft for owner review. Nothing here is frozen. Decisions marked OPEN need an explicit choice before contract v2 is written.
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

**D1. Schema cohorts (P1 passed; owner confirmation OPEN).** Treat C1 and C2 as one *semantic* cohort: match column names case-insensitively, canonical `INTEGER` for ID columns, canonical `BIGINT` for `passenger_count` and `RatecodeID`. P1 (section 4) found no non-integral and no NaN values in either `DOUBLE` column across all 13 C1 months, and all ID values fit `INTEGER`, so the conversion is lossless. Remaining caveat (P1b): `passenger_count` and `RatecodeID` are null together in 2.3% to 3.7% of C1 rows; confirm the null share continues across the C1 to C2 boundary before using either column as a distribution feature. If the owner rejects D1, C1 becomes a separate cohort and only 12 months (2023-01 and 2024-02 to 2024-12) are distribution-eligible, not 24.

**D2. Date coverage.** Boundary spill (pickup within one day of the file's month) is benign: counted and reported, never an alert. Rows more than one day outside the month are `far_out_pickup` source anomalies. Contract v2 adds a cleaning rule that rejects them under its own rule ID, with per-month counts; the v2 retention-completeness check covers it. M1 has no date rule, so these rows currently reach `daily_zone_metrics` as stray dates. The far-out count must not be used as a distribution feature: it falls year over year (612, 323, 49, 8).

**D3. 2025 regime.** 2025 is its own regime (congestion pricing plus a new column). Exact reconciliation checks run; distribution alerts do not. Fare-sign and rejection-rate checks are excluded from any distribution alert, because the negative-fare share drifts within 2025.

**D4. Genuine source anomaly versus false alarm.** An alert counts as a false alarm only when independent recomputation from the source files (Polars) shows no anomaly against the declared rules. If the same surge appears in the source (e.g. the Sept to Nov 2023 distance episode), the alert is a correct source-anomaly detection. Decide this rule now, before any detector output is seen.

**D5. Control-month use (OPEN).** Fix the detector's rule form and its constants a priori, before any further inspection of monthly statistics, and score all eligible months walk-forward (each month against its preceding 12 eligible months). Use only the 2022 warm-up months to debug detector code. The author has seen the aggregate counts for all 48 months; disclose this under threats to validity.

**D6. Fault-hosting months (OPEN).** M1 injected into 2024-01. Choose and record the fixed month(s) that host the M2a fault cases before Phase 1 injection work, and keep them identical across methods.

**D7. Versioning.** Contract v2 = `contracts/v2/pipeline.yaml` plus `contracts/v2/tlc-yellow-v2.json`, with the existing newline-normalized hash. The v2 checks required by the catalog (cleaning retention completeness; join-key verification) are part of v2 and frozen before detector work.

## 3. Consequences for denominators

- Exact-reconciliation controls: 36 months (2023 to 2025).
- Distribution-alert eligible months: 24 (2023 and 2024) if D1 holds, 12 if not. All 12 months of 2025 are ineligible.
- Zero alerts in 24 eligible months still leaves a 95% upper bound of about 12 to 14% on the false-alarm rate.

## 4. Prerequisites before contract v2 is written

- **P1 (done).** See section 4.
- **P1b.** Run the P1 query for 2023-02 to 2024-12 and compare the null share of `passenger_count` and `RatecodeID` with C1's 2.3% to 3.7%. Record the result here.
- **P2.** Review the TLC data dictionary against the audit for the columns contract v2 will declare, and record any column whose meaning changed between cohorts.
- **P3.** Record the hours spent on each Phase 1 task from now on (needed for the November 24 decision).

## 4. P1 result (months 2022-01 to 2023-01)

- Non-integral values in `passenger_count` and `RatecodeID`: 0 in all 13 months. NaN values: 0 in all 13 months.
- `passenger_count` ranges 0 to 9 and `RatecodeID` ranges 1 to 99 (99 is a documented unknown code); `VendorID` 1 to 6; `PULocationID` and `DOLocationID` 1 to 265. All fit `INTEGER`.
- `passenger_count` and `RatecodeID` have identical null counts in each month (for example 71,503 in 2022-01), so the nulls occur together in the same rows. Null share by month: 2.90%, 3.41%, 3.25%, 3.30%, 3.61%, 3.72%, 3.31%, 2.96%, 3.66%, 3.62%, 3.75%, 3.72%, then 2.34% in 2023-01.
- Conclusion: the C1 to C2 type change is a lossless widening for the values present.

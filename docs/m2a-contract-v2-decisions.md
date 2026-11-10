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

**D1. Schema cohorts (OPEN, depends on prerequisite P1).** Treat C1 and C2 as one *semantic* cohort: match column names case-insensitively, canonical `INTEGER` for ID columns, canonical `BIGINT` for `passenger_count` and `RatecodeID`. Accept this only if P1 shows the `DOUBLE` columns are integral. If P1 fails, C1 is a separate cohort and only 12 months (2023-01 and 2024-02 to 2024-12) can be distribution-eligible, not 24.

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

- **P1.** For months 2022-01 to 2023-01, verify `passenger_count` and `RatecodeID` contain no non-integral or NaN values, and record the min/max of the ID columns. Record the result here.
- **P2.** Review the TLC data dictionary against the audit for the columns contract v2 will declare, and record any column whose meaning changed between cohorts.
- **P3.** Record the hours spent on each Phase 1 task from now on (needed for the November 24 decision).

# P4 Source-Anomaly Eligibility Rule

**Status:** Proposed Phase 0 decision for review. This document does not freeze P4, classify any month, or authorize scored-period evaluation. Numeric calibration thresholds remain unset until the source review is complete.

## Purpose

This rule determines whether a 2022 source month may be used as a warm-up calibration control and how a source-origin alert is classified. It prevents a detector's own alert, an unusual-looking statistic, or successful recomputation from defining ground truth after the fact.

The TLC trip-record page states that records are collected from authorized technology providers and are not represented by TLC as accurate. Therefore, a checksum and successful read establish file identity and readability, not source truth. Independent recomputation establishes computational consistency, not that every source value is correct.

## Proposed pre-evaluation classification rule

Classify each source-month before computing or reviewing its P4 profile distances. Preserve the evidence and rationale for each classification.

1. **Confirmed source anomaly.** Assign only when either:
   - an authoritative, dated TLC notice, correction, replacement, or documented incident identifies the affected month and data property; or
   - the source violates an explicit, machine-checkable requirement in a dated, applicable TLC specification, data dictionary, or versioned lookup reference. Record the exact source, version/date, field, predicate, and affected count.
2. **No qualifying source anomaly found.** Assign only after the complete review procedure below succeeds, no confirmed criterion is violated, and the review finds no applicable official correction or incident notice. This is an operational calibration classification, not a claim that TLC source data are universally accurate.
3. **Unresolved.** Assign if file identity or schema provenance is incomplete, independent calculations disagree, applicability of a requirement is uncertain, or the official-incident review cannot be completed. Do not promote an unresolved month to eligible based on the detector's result.

Do not define anomaly criteria from observed P4 distances, detector alerts, the relative rank of a month, or a threshold selected to retain at least 10 months. Do not add criteria after viewing calibration outcomes. Any criteria change requires a new version and a fresh calibration review.

## Month review procedure

For every 2022 month, before profile-distance calculation:

1. Verify the source file SHA-256, byte count, row count, original ordered columns, physical types, schema cohort, and schema signature against the pinned audit.
2. Independently recompute the declared exact properties with the pinned second engine: row counts, required null counts, exact fare sums, date-window accepted and rejected row counts, and lookup-key multiplicities. Reconciliation must use the same immutable file hash. A disagreement makes the month unresolved until explained. This step depends on the Polars reference implementation and its hand-computed fixture validation, which are not yet implemented. Do not finalize month classifications until that gate passes.
3. Check each proposed source anomaly only against a cited, dated, applicable external requirement or a specific official TLC incident record. Record negative fares, non-positive distances, and pickup dates outside the file month as observed findings. They are not source anomalies solely because they are unusual. Under D2, pickups outside the one-day-expanded interval are rejected per row and counted; they do not fail the month or alert by themselves.
4. Search the official TLC trip-record page as accessed on the review date and every notice or correction page linked from it that refers to Yellow Taxi trip records. Record the URL, access date, searched page titles and links, query terms, and whether any notice names the month and relevant property. If this complete, recorded search finds no matching notice, the incident-search step is complete with result `none_found_in_reviewed_scope`. Do not claim this establishes that no notice exists outside that reviewed scope. If a linked page cannot be accessed or the review scope cannot be recorded, classify the month unresolved.
5. Store one month record with the class, evidence links and hashes, each predicate and count, reviewer, review date, and a concise rationale. Freeze and hash the complete review before calculating P4 distances.

## Baseline eligibility, denominators, and alert scoring

- Only a 2022 month classified **no qualifying source anomaly found**, with its source identity, schema, independent calculations, and lookup checks passing, may enter the P4 calibration set or a later D5 baseline. A **confirmed source anomaly** or **unresolved** month is excluded from both. Neither status removes a month from the exact-check accounting where the protocol says exact checks apply.
- For 2023-2024 scoring, baseline eligibility is a frozen, month-level table produced from the same pre-registered source review and production-available checks before detector outputs are generated. The exact same eligible-month table and trailing windows are supplied to every detection arm. Do not use method-specific alerts or private evaluator labels to select baselines. Record that the fixed table is additional common experimental configuration and disclose its use as a limitation.
- Construct each baseline from the 12 immediately preceding calendar months in the same contract, semantic schema cohort, and regime. Do not skip an ineligible month and reach farther back. If any of those 12 months is not baseline-eligible, that score month is distribution-ineligible.
- Exact checks retain the protocol denominators: 36 exact-check months from 2023-01 through 2025-12. The distribution denominator is not presumed to be 24. Publish a generated month table with each 2022 classification and baseline-eligibility flag, and each 2023-2024 score-month eligibility flag and reason. Report the resulting distribution denominator from that table. 2025 remains distribution-ineligible under D3.
- An alert on a **confirmed source anomaly** is D4 category 2 only when it correctly identifies the pre-registered anomaly criterion. A source-origin alert on a month classified **no qualifying source anomaly found** is D4 category 3, a false positive, unless independent evidence establishes a pipeline-origin discrepancy, which is D4 category 1. A month's unresolved source-anomaly status is D4 uncertain/abstained only when no pipeline-origin discrepancy can be established independently. A directly established pipeline-origin discrepancy remains D4 category 1 even if another aspect of the source review is unresolved. Incorrect origin attribution is scored separately. Month status alone does not make an alert correct.
- If fewer than 10 eligible 2022 months remain, P4 distribution calibration and distribution-alert evaluation remain blocked. This does not block exact checks, Polars reference validation, contract v2 work, or stage hooks. Do not derive distribution thresholds from scored-period data.

The owner has already seen aggregate audit statistics for the 48-month period before this rule was written, including the 447 pickups more than one day outside the 2022-06 file month. This prior exposure is a limitation and is recorded for disclosure. It does not permit using detector outputs or profile distances to classify months.

The phrase “no qualifying source anomaly found” must not be shortened to “verified clean” in reports. State that the review can identify only anomalies supported by its declared external criteria and that undiscovered source defects remain possible.

## Known limits and reviewed source

The March 18, 2025 Yellow Taxi data dictionary describes column meanings and current codes, but it does not establish historical correctness or validate every observed value in 2022. The current dictionary alone therefore cannot classify a negative fare or unusual distance as a source anomaly. Its applicability and code lists must not be projected backward without dated evidence.

Official references:

- [NYC TLC Yellow Taxi Trip Records data dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf)
- [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)

The official page says the records were collected from authorized technology providers and that TLC makes no representations as to their accuracy. The review therefore uses the bounded label “no qualifying source anomaly found” and does not assert that a source month is verified clean. The official page's notice search is only complete within the explicitly recorded page and linked-notice scope.

## Review gate

Before P4 calibration, review this proposal alongside the P4 feature and threshold draft, validate the Polars reference against hand-computed fixtures, complete and hash the month-by-month records, and confirm that classifications predate all profile-distance outputs. If the review cannot establish at least 10 eligible months, record that distribution calibration is blocked. Exact checks, reference validation, contract v2 work, and hooks may proceed. This rule does not authorize scored-period distribution alerts or detector evaluation by itself.

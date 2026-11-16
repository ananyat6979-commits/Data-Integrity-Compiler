# P4 Source-Anomaly Eligibility Rule

**Status:** Proposed Phase 0 decision for review. This document does not freeze P4, classify any month, or authorize scored-period evaluation. Numeric calibration thresholds remain unset until the source review is complete.

## Purpose

This rule determines whether a 2022 source month may be used as a warm-up calibration control and how a source-origin alert is classified. It prevents a detector's own alert, an unusual-looking statistic, or successful recomputation from defining ground truth after the fact.

The TLC trip-record page states that records are collected from authorized technology providers and are not represented by TLC as accurate. Therefore, a checksum and successful read establish file identity and readability, not source truth. Independent recomputation establishes computational consistency, not that every source value is correct.

## Frozen classification rule

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
2. Independently recompute the declared exact properties with the pinned second engine: row counts, required null counts, exact fare sums, date-window accepted and rejected row counts, and lookup-key multiplicities. Reconciliation must use the same immutable file hash. A disagreement makes the month unresolved until explained.
3. Check each proposed source anomaly only against a cited, dated, applicable external requirement or a specific official TLC incident record. Record negative fares, non-positive distances, and pickup dates outside the file month as observed findings. They are not source anomalies solely because they are unusual. Under D2, pickups outside the one-day-expanded interval are rejected per row and counted; they do not fail the month or alert by themselves.
4. Search the official TLC trip-record page and linked notices for an applicable correction or incident. Save the reviewed URL, access date, search scope, and result. If coverage is ambiguous, classify unresolved.
5. Store one month record with the class, evidence links and hashes, each predicate and count, reviewer, review date, and a concise rationale. Freeze and hash the complete review before calculating P4 distances.

## Calibration eligibility and alert scoring

- A month classified **confirmed source anomaly** is excluded from clean calibration controls and reported separately.
- A month classified **unresolved** is excluded from calibration and cannot be counted as an independently verified non-anomalous clean run.
- A month classified **no qualifying source anomaly found** may enter calibration only if all source identity, schema, independent calculation, and lookup checks above pass.
- A P4 profile alert does not change the source classification. If an alert cannot be attributed using the frozen evidence, retain the unresolved or non-anomalous classification and score it under the pre-registered D4 rule. Do not relabel it because the distance is large.
- The P4 minimum of 10 eligible 2022 months remains mandatory. If fewer than 10 qualify, P4 remains unresolved. Do not derive a numeric threshold from 2023 onward or weaken the eligibility rule.

The phrase “no qualifying source anomaly found” must not be shortened to “verified clean” in reports. State that the review can identify only anomalies supported by its declared external criteria and that undiscovered source defects remain possible.

## Known limits and reviewed source

The March 18, 2025 Yellow Taxi data dictionary describes column meanings and current codes, but it does not establish historical correctness or validate every observed value in 2022. The current dictionary alone therefore cannot classify a negative fare or unusual distance as a source anomaly. Its applicability and code lists must not be projected backward without dated evidence.

Official references:

- [NYC TLC Yellow Taxi Trip Records data dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf)
- [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)

## Review gate

Before P4 calibration, review this rule alongside the P4 feature and threshold draft, complete the month-by-month records, and confirm that the criteria were fixed before distance outputs were computed. If the official incident review or the independent checks cannot establish at least 10 eligible months, record the blocker and leave thresholds unset. This rule does not authorize Phase 1 detector implementation or any 2023–2025 detector run by itself.

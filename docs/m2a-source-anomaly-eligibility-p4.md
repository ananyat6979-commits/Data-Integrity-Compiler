# P4 Source-Anomaly Eligibility Rule

**Status:** Proposed source-review procedure for review. This document does not freeze P4 or classify any month. Under adopted protocol v1.2, distribution alerts are disabled for the current M2a evaluation. These classifications do not open a calibration gate.

## Purpose

This rule records bounded source-origin evidence and supports D4 alert classification. It prevents a detector's own alert, an unusual-looking statistic, or successful recomputation from defining ground truth after the fact. It no longer determines whether a 2022 month can calibrate the current M2a detector because protocol v1.2 has no distribution calibration in this evaluation.

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

## Current use, denominators, and D4 alert scoring

- Under adopted protocol v1.2, current distribution calibration and distribution alerts are disabled. The 2022 classifications are source-review records only. They do not gate exact checks, references, contract v2, or fault injection. The current distribution-alert denominator is zero. Exact checks retain the separate 36-month denominator from 2023-01 through 2025-12.
- For a future protocol that reopens distribution scoring, publish a generated month table with each source class and each score-month eligibility flag and reason. Construct every forecast baseline from the twelve immediately preceding eligible months in the same contract, semantic schema cohort, and regime. Do not skip a month or use method-specific alerts or evaluator-only labels. The future protocol must specify forecast-score counts and alert budgets per feature. A count of ten eligible 2022 months is not a valid forecast calibration gate.
- A confirmed anomaly or unresolved 2022 month does not remove a month from current exact-check accounting. If a future rolling baseline excludes 2022-06, its absence makes 2023-01 through 2023-06 ineligible because each immediately preceding twelve-month window contains 2022-06. Publish the resulting denominator rather than assuming all 24 potential months are scorable.
- An alert on a **confirmed source anomaly** is D4 category 2 only when it correctly identifies the pre-registered anomaly criterion. A source-origin alert on a month classified **no qualifying source anomaly found** is D4 category 3, a false positive, unless independent evidence establishes a pipeline-origin discrepancy, which is D4 category 1. A month's unresolved source-anomaly status is D4 uncertain/abstained only when no pipeline-origin discrepancy can be established independently. A directly established pipeline-origin discrepancy remains D4 category 1 even if another aspect of the source review is unresolved. Incorrect origin attribution is scored separately. Month status alone does not make an alert correct.

The owner is the sole reviewer and has already seen aggregate audit statistics for the 48-month period before this rule was written, including the 447 pickups more than one day outside the 2022-06 file month. This prior exposure is a limitation and is recorded for disclosure. It does not permit using detector outputs or profile distances to classify months.

The phrase “no qualifying source anomaly found” must not be shortened to “verified clean” in reports. State that the review can identify only anomalies supported by its declared external criteria and that undiscovered source defects remain possible.

## Known limits and reviewed source

The March 18, 2025 Yellow Taxi data dictionary describes column meanings and current codes, but it does not establish historical correctness or validate every observed value in 2022. The current dictionary alone therefore cannot classify a negative fare or unusual distance as a source anomaly. Its applicability and code lists must not be projected backward without dated evidence.

Official references:

- [NYC TLC Yellow Taxi Trip Records data dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf)
- [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)

The official page says the records were collected from authorized technology providers and that TLC makes no representations as to their accuracy. The review therefore uses the bounded label “no qualifying source anomaly found” and does not assert that a source month is verified clean. The official page's notice search is only complete within the explicitly recorded page and linked-notice scope.

## Review gate

Before any future P4 distance calculation, review this procedure and the versioned protocol together, validate the Polars reference against hand-computed fixtures, complete and hash the month-by-month records, and confirm that classifications predate all distance outputs. The future evaluation entry point must refuse to calculate distances unless it verifies the reviewed eligibility artifact and its SHA-256. Protocol v1.2 disables distribution alerts regardless of how many 2022 months receive the class “no qualifying source anomaly found.” Exact checks, reference validation, contract v2 work, and hooks proceed independently. This document does not authorize scored-period distribution alerts or detector evaluation by itself.

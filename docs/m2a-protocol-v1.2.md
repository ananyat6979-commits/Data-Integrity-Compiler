# M2a Experimental Protocol v1.2

**Status:** Proposed amendment for review. This version is not frozen and does not authorize detector or held-out evaluation. It consists of protocol v1.1 plus the explicit amendments below. If accepted, v1.2 supersedes v1.1 wherever these amendments conflict. The experimental freeze still occurs only at `m2a-frozen`.

## Version purpose

The 2022-only leave-one-month-out procedure in v1.1 is interpolation, while the proposed scoring rule is one-step-ahead forecasting. They do not estimate the same error distribution. In addition, calendar-month composition changes weekday totals, and a maximum-of-ten calibration threshold has a substantial nominal exceedance rate. V1.2 removes distribution alerts from the current M2a evaluation instead of treating those thresholds as validated.

## Current evaluation scope and denominators

- Distribution checks are disabled. No feature distances or thresholds are fitted for evaluation, and no scored distribution-alert months exist. The distribution denominator is zero.
- This amendment overrides v1.1's instruction to score 24 distribution months and its use of 2022 as a distribution-calibration period. The 24 months remain only the maximum potential future score range.
- The 2022 files are source-review and warm-up material only. They are not a calibration set and cannot be called independently verified clean merely because they have a computed profile.
- Exact reconciliation covers 36 monthly controls from 2023-01 through 2025-12. This denominator is separate from the 24-month maximum potential future distribution range of 2023-01 through 2024-12. Do not call those 24 months scored distribution controls under v1.2.
- Exact reconciliation, independent reference calculations, fault hooks, development cases, detector comparisons, and fault injection proceed without P4 distribution alerts. Their acceptance criteria remain those in v1.1.

## Source eligibility and D4 classification

The source-month eligibility document remains a proposed review artifact. For current v1.2, its classifications do not gate exact checks, reference calculations, or fault injection. They cannot enable distribution calibration. If distribution checks are proposed in a later version, the eligibility table must be frozen before any distance is computed and its hash must be verified by the evaluation entry point. A missing, modified, or unreviewed eligibility artifact must stop that future distribution evaluation.

Use the D4 categories as follows:

1. A pipeline-origin discrepancy exists when independent recomputation from the same source disagrees with the pipeline output. Correctly alerting on this is an integrity detection. Incorrect source attribution is scored separately.
2. A source-origin anomaly requires an independently registered criterion, such as an applicable official TLC notice or a predeclared domain bound. Reproducing a statistic is not sufficient evidence of anomaly.
3. A source-origin alert that does not meet the criterion is a false positive. Unresolved origin or anomaly status is uncertain or abstained and is reported separately.

The current TLC data dictionary does not classify negative fares as anomalies. Category 2 is expected to be empty unless a qualifying official notice or other criterion is recorded before detector output is inspected. Report the observed count rather than assigning labels to fill the category.

For the headline run-level false-positive rate, count alerts from every enabled detector in the full system on independently verified non-anomalous clean runs. If a future protocol enables a distribution detector, its alert contributes to that run-level decision and headline rate. Also publish the distribution-only run-level rate and per-feature numerators and denominators separately. The current distribution-only denominator is zero, so its rate is not estimable.

## Future distribution-check requirements

Any future protocol that re-enables distribution checks must be newly versioned and reviewed before implementation or detector output inspection. It must:

- Use forecast-aligned calibration scores. Each score is predicted from the twelve immediately preceding eligible months in the same contract, source-schema cohort, and operating regime. Do not interpolate by predicting omitted months from both earlier and later profiles, skip ineligible gaps, or use held-out months for tuning.
- State exact calibration and scoring periods, the number of valid forecast scores per feature, a pre-registered alert budget, and the resulting expected alert-rate limitations. A count of ten eligible source months alone is not a sufficient gate.
- Normalize weekday-hour composition for the number of occurrences of each weekday. For weekday `w` and hour `h`, compute `r[w,h] = count(w,h) / occurrences(w)`, then `p[w,h] = r[w,h] / sum_h(r[w,h])`. Preserve raw counts and occurrence counts.
- Mark cells with fewer than 30 observations in the preceding baseline as ineligible at cell level. Do not collapse them into an `other_or_low_support` bin. For zone cells, apply the support threshold using the preceding baseline, retain an eligibility mask, and report excluded mass. Do not silently discard source rows from exact reconciliation.
- Use separate thresholds per feature. Any future score method must retain exact observed and predicted vectors, feature support, eligibility masks, and hashes.
- Make the evaluation script require and verify the reviewed source-eligibility artifact and its recorded SHA-256 before computing any distance.

For a threshold set to the maximum of `m` exchangeable calibration scores, the nominal next-score exceedance is `1/(m+1)`: about 9.1% for 10 scores and 7.7% for 12. For two features combined with OR, the corresponding union-bound values are about 18.2% and 15.4%. A nominal 5% rate needs 19 scores per feature if each is reported separately, or 39 per feature for a 5% two-feature union bound. These calculations are not operational guarantees because monthly scores may be dependent and drift over time. The later protocol must select and justify the budget rather than inherit one implicitly.

## Disclosure and threats to validity

The owner is the sole reviewer and has seen the 48-month audit aggregates before finalizing source eligibility, including the 447 far-out rows in 2022-06 and the monthly negative-fare and distance summaries. The catalog author knows the mechanism split. These are explicit limitations, not claims of independent blinding.

An excluded or unresolved month can make later forecast windows ineligible. Never skip a gap to restore twelve observations. Publish the full month-level eligibility table and actual feature denominators. For example, excluding 2022-06 makes 2023-01 through 2023-06 ineligible under a contiguous twelve-month preceding window. Do not assume that the full set of 24 potential months will be scorable.

Any change to the frozen detector, feature definitions, eligibility labels, scoring, or calibration after evaluation begins requires a new protocol version and a fresh untouched holdout. The same held-out cases cannot be rerun after silent changes and still be described as untouched.

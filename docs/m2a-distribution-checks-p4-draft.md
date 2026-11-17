# M2a Distribution Checks: P4 Draft

**Status:** Proposed future method. Under adopted protocol v1.2, distribution alerts are disabled for the current M2a evaluation. This document does not authorize threshold fitting or detector runs. Re-enabling distribution alerts requires a new protocol version and a fresh review.

## Current M2a decision proposal

The current M2a evaluation uses exact reconciliation and fault injection, with 36 exact monthly controls from 2023-01 through 2025-12. It scores zero distribution-alert months because no forecast-aligned calibration set is available. The 24 months from 2023-01 through 2024-12 are only the maximum potential distribution-score range under the present regime boundary, not scored months in protocol v1.2. The 12 months in 2025 remain outside that potential range.

The 2022 files are warm-up and source-review material only. They do not produce calibration scores. Twelve 2022 profiles can provide history for a later forecast, but cannot themselves produce a one-step-ahead forecast score with twelve preceding same-regime profiles. A count of ten eligible 2022 months is therefore not a valid calibration gate.

If a later protocol reopens distribution checks, each calibration score must be a one-step-ahead forecast made only from the twelve immediately preceding eligible months in the same contract, schema cohort and regime. The calibration set must contain the pre-registered minimum number of valid forecast scores for every feature. Missing or ineligible months are not skipped to extend history. Calibration and scoring periods must be separated as that protocol specifies. No future protocol may reuse held-out results for tuning.

## Candidate features for a future protocol

1. **Pickup weekday-by-hour profile:** 168 weekday and hour cells, computed from local pickup timestamps.
2. **Pickup-zone profile:** one cell for each location ID 1 through 265, plus explicit `null_or_out_of_range` and `unmapped` cells. Compute source pickup IDs and joined zone labels separately when evaluating joins.

The list is provisional. Do not add features without a written domain rationale and a separate stability review.

## Calendar normalization and support

Raw weekday totals are not comparable across months because a weekday occurs four or five times. For each weekday `w` and hour `h`, compute the per-occurrence rate `r[w,h] = count(w,h) / occurrences(w)`. Build the weekday's 24-hour shape as `p[w,h] = r[w,h] / sum_h(r[w,h])`. This conditions on weekday and removes the 4-versus-5 occurrence composition effect. Preserve occurrence counts and raw counts in evidence.

For weekday-hour cells, a baseline count below 30 makes that cell ineligible, following the protocol's cell-level rule. Do not collapse unsupported cells into `other_or_low_support`. Record the eligibility mask and excluded mass. For the zone profile, apply the same 30-observation minimum to each zone using the preceding baseline only. A zone below support is ineligible for that comparison and is not folded into an `other` bin. Keep the full raw zone counts and excluded mass in the record so limited coverage is visible. If no supported cells remain, mark that feature ineligible with a reason.

These support rules and the weekday normalization must be frozen before any calibration distances are computed. The future evaluation script must refuse to run unless it receives the reviewed eligibility artifact and verifies its recorded SHA-256. Classifications must predate distance calculation.

## Candidate distance for a future protocol

Apply the same fixed-bin smoothing to each eligible feature vector: `p[i] = (c[i] + 0.5) / (sum(c) + 0.5 * K)`, where `K` is the number of eligible, declared cells. Fit a Theil-Sen trend per cell from the twelve preceding eligible monthly profiles, predict one month ahead using actual month indices, clamp negative predictions to zero, and renormalize. If prediction is non-finite or has no positive mass, the feature is ineligible.

Compare observed and predicted vectors with Jensen-Shannon divergence using base-2 logarithms. Report the distance in bits and retain both vectors, support counts, eligibility mask, and calculation inputs. A distance is a discrepancy score, not evidence of source anomaly by itself.

Use a separate threshold for each feature. Do not use one shared maximum across weekday-hour and zone profiles. Thresholds remain unset in the current protocol.

## False-alert accounting for any future activation

Distribution alerts are disabled in the current protocol, so there is no distribution-alert rate or threshold claim. In any future protocol that enables them:

- Every distribution alert contributes to the full system's run-level alert decision and therefore to the headline run-level false-positive rate on independently verified non-anomalous clean runs.
- Also report the distribution-only run-level numerator and denominator, with each feature's eligible numerator and denominator. Do not present those as independent of the full-system rate.
- Pre-register the alert budget before detector execution. For a threshold equal to the maximum of `m` exchangeable calibration scores, the nominal next-score exceedance probability is `1/(m+1)`: 9.1% for 10 scores and 7.7% for 12. For two feature alerts combined with OR, the union-bound values are 18.2% and 15.4%, corresponding to roughly 4.4 and 3.7 alerts over 24 eligible runs under those idealized assumptions.
- A nominal 5% bound requires at least 19 calibration scores per feature if each feature is considered separately, and at least 39 per feature for a 5% two-feature union bound. These calculations assume exchangeability and do not establish an operational false-positive guarantee. Monthly dependence and drift weaken that assumption.
- Report the actual eligible denominator and uncertainty. Do not use twelve repeated months as proof of a low operational false-alarm rate.

## Source review and limitations

Source anomaly labels are assigned before distance calculations. A source statistic being reproducible does not make it anomalous. The current TLC data dictionary does not classify negative fares as source anomalies, so D4 category 2 is expected to be empty unless an independently registered official notice or other criterion supports it. Report the actual category counts and do not relabel after detector results.

The owner is the sole reviewer and has already seen the 48-month audit aggregates, including the 447 far-out pickup rows in 2022-06 and the negative-fare and distance summaries. This is a disclosed source of selection bias, not independent blindness. No held-out output may be used to change eligibility labels or methods.

An excluded or unresolved month can make later rolling windows ineligible. Windows never skip a month to recover twelve observations. For example, if 2022-06 is excluded, 2023-01 through 2023-06 each include that month in their immediately preceding twelve-month window and cannot be scored under this rule. Publish the month-level eligibility table and resulting denominator; do not assume all 24 potential months are scorable.

## Reopening gate

P4 remains disabled until a new versioned protocol resolves the forecast-aligned calibration period, minimum forecast-score count, per-feature alert budget, eligibility and support rules, and review artifact. That protocol must state the exact calibration and scoring months, all hashes, expected denominators, alert accounting, and clean-control evidence before any distance is computed. A defect or method change after freeze requires a new version and a fresh untouched evaluation set.

# M2a Distribution Checks: P4 Draft

**Status:** Proposed Phase 0 methods, not frozen. The current 2022-only calibration procedure is invalid for the planned scoring rule and must not be run to set thresholds. This document does not authorize distribution-detector runs on scored months. Exact checks, reference validation, contract v2 work, and stage hooks may proceed while P4 distribution calibration remains unresolved.

## Scope and alert semantics

These checks look for changes in the shape of monthly pickup data that exact reconciliation cannot detect. They are supplementary to exact row, null, fare-sum and join reconciliation. They may emit an alert, but they do not block publication in this version. An alert is not itself evidence of a source anomaly. Apply the D4 source-origin classification and scoring rules separately.

Do not inspect or use 2023-2025 results to choose features, distance functions, smoothing, eligibility rules or thresholds. Preserve source hashes and every calibration input and output hash. Any calibration data must be separate from the final scored months and must be classified under the source-anomaly eligibility rule before profile distances are computed.

## Candidate features

1. **Pickup weekday-by-hour profile:** 168 bins, using local pickup timestamp weekday and hour. Rows with null or invalid timestamps are handled by exact checks and counted in an explicit invalid category, not silently dropped.
2. **Pickup-zone profile:** one bin for each zone ID 1 through 265, plus explicit `null_or_out_of_range` and `unmapped` bins. This is calculated from source pickup IDs and, separately, from joined zone labels where the join is under evaluation.

These features are candidates because they are interpretable and map to distinct evidence: timestamp allocation and geographic lookup behavior. Do not add fare-per-mile or other features without a written rationale and a separate stability review. The feature list is versioned and hashed before any 2023 or later evaluation.

## Profile construction and distance

For each eligible month, convert bin counts to proportions. For weekday-by-hour, use an `other_or_low_support` bin for cells with fewer than 30 observations in the preceding baseline. Keep the raw counts and the resulting eligibility mask in the calibration record. Do not discard rows from exact reconciliation.

Smooth each monthly count vector `c` with the same fixed bin set using `p[i] = (c[i] + 0.5) / (sum(c) + 0.5 * K)`, where `K` is the number of declared bins. This yields a probability vector and avoids zero-probability bins.

For a score month, fit a Theil-Sen line separately to each bin's smoothed monthly proportion across the 12 preceding eligible months from the same contract, schema cohort and operating regime. Predict each bin one month ahead, clamp negative predictions to zero, and renormalize the predicted vector to sum to one. The median pairwise slope limits the effect of one extreme historical month while allowing gradual linear drift. No calendar-month-of-year strata are used. If all predicted mass is zero or non-finite, mark the feature ineligible and report why.

Compare the observed and predicted profile with Jensen-Shannon divergence using base-2 logarithms: `JS(p,q) = 0.5 * KL(p||m) + 0.5 * KL(q||m)`, where `m = (p + q) / 2`. Report divergence in bits, bounded from 0 to 1. Record the observed vector, predicted vector, eligibility mask and computed distance for every run. This distance measures profile difference; it does not establish why the difference occurred.

## Forecast-aligned calibration and threshold semantics

Every calibration target must be predicted using only its 12 immediately preceding eligible monthly profiles, with the same Theil-Sen fitting, horizon, cohort, regime, binning, support and smoothing rules used for a scored month. This is a rolling-origin forecast. Do not predict an omitted month from other months that occur after it. Leave-one-month-out interpolation is not a valid calibration procedure for this detector.

The audited calibration input currently contains 2022-01 through 2022-12 only. It does not contain 12 preceding same-regime audited months for any 2022 target. Therefore it produces zero forecast-aligned calibration scores. The current 2022-only data cannot set the planned forecast threshold. Do not substitute an interpolation score, a 2023-2024 score, or an unreviewed regime. P4 distribution calibration remains unresolved until an adequately sized forecast-calibration period with a validated same-regime 12-month history is specified and reviewed. If such a period cannot be justified, leave distribution thresholds unset and keep distribution alerts disabled. This does not block exact checks, Polars reference validation, contract v2 work, or stage hooks.

Once valid forecast-calibration scores exist, set a separate threshold for each feature: `threshold_j = max(calibration_forecast_scores_j) + 1e-12`. Alert when either feature exceeds its own threshold. Do not compare the two feature scales through one shared maximum. Persist each feature's calibration scores and threshold separately, and retain the per-feature alert indicators and combined OR decision.

The proposed minimum is 10 eligible forecast scores per feature. Its limited rationale is a nominal rank-tail calculation: if calibration and future scores were continuous, exchangeable observations, the chance that one future score exceeds the maximum of `m` calibration scores is `1/(m+1)`. This is 9.1% for `m=10` and 7.7% for `m=12`, per feature only. Monthly scores are serially dependent and may drift, so exchangeability is not established and these are not false-positive guarantees. With two features and an OR alert, a union-bound reference is up to 18.2% at 10 scores or 15.4% at 12 scores, under the same unverified assumptions. Across 24 distribution-eligible months, these correspond to rough alert-count references of up to 4.4 or 3.7, not predictions or acceptance targets. The observed run-level false-positive rate and uncertainty must be reported separately. Do not describe max calibration as conservative or interpret zero calibration exceedances as evidence of zero false alarms.

If fewer than 10 valid forecast scores per feature remain after the source review, do not derive thresholds. Record P4 distribution calibration as unresolved. Store the calibration period, source classifications, per-feature forecast scores, eligibility table, code identity, and hashes in a versioned artifact before any scored-period evaluation.

## Eligibility and limitations

- Exact checks run regardless of distribution-check eligibility.
- Distribution checks require the 12 immediately preceding calendar months to be baseline-eligible under the frozen common month table, from the same contract, semantic schema cohort, and regime. 2023-01 through 2024-12 are a maximum potential scoring set of 24 months, not a guaranteed denominator. Generate and report the actual scorable-month table and denominator. All 2025 months remain distribution-ineligible under D3. Exact checks retain their separate 36-month denominator.
- A month classified as a source anomaly or unresolved/disputed is not a clean calibration control. Record it separately under D4.
- The 2022 data include observed source findings. Until the independent oracle and anomaly criteria classify them, no monthly profile may be called independently verified clean for threshold calibration.
- Thresholds describe stability under this dataset and the declared pipeline only. They do not imply generalization to other years, fleets, or taxi systems.

## Required review before freeze

P4 distribution calibration is complete only after a forecast-aligned calibration period and its 12-month same-regime histories are justified, source eligibility is reviewed before distances are computed, at least 10 eligible forecast scores per feature remain, separate thresholds and the two-feature alert-rate implications are recorded, and the decision note/protocol references the hashed calibration artifact. No 2023-2025 scored-period detector outputs may be inspected to revise the method. Any later change requires a new version and a new untouched evaluation set. While this gate is unresolved, exact checks, reference validation, contract v2 work, and hooks may proceed, but distribution-alert evaluation may not.

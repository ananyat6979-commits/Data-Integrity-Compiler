# M2a Distribution Checks: P4 Draft

**Status:** Proposed Phase 0 methods, not frozen. This document defines a warm-up-only calibration procedure. It does not authorize running a detector on 2023 or later data. Numeric thresholds remain unset until the 2022 months have been classified using the independently registered source-anomaly criteria and the calibration output is reviewed.

## Scope and alert semantics

These checks look for changes in the shape of monthly pickup data that exact reconciliation cannot detect. They are supplementary to exact row, null, fare-sum and join reconciliation. They may emit an alert, but they do not block publication in this version. An alert is not itself evidence of a source anomaly. Apply the D4 source-origin classification and scoring rules separately.

Use only the 2022 source files to assess feature stability and derive calibration thresholds. Do not inspect or use 2023-2025 results to choose features, distance functions, smoothing, eligibility rules or thresholds. Preserve source hashes and every calibration input and output hash.

## Candidate features

1. **Pickup weekday-by-hour profile:** 168 bins, using local pickup timestamp weekday and hour. Rows with null or invalid timestamps are handled by exact checks and counted in an explicit invalid category, not silently dropped.
2. **Pickup-zone profile:** one bin for each zone ID 1 through 265, plus explicit `null_or_out_of_range` and `unmapped` bins. This is calculated from source pickup IDs and, separately, from joined zone labels where the join is under evaluation.

These features are candidates because they are interpretable and map to distinct evidence: timestamp allocation and geographic lookup behavior. Do not add fare-per-mile or other features without a written rationale and a separate stability review. The feature list is versioned and hashed before any 2023 or later evaluation.

## Profile construction and distance

For each eligible month, convert bin counts to proportions. For weekday-by-hour, use an `other_or_low_support` bin for cells with fewer than 30 observations in the preceding baseline. Keep the raw counts and the resulting eligibility mask in the calibration record. Do not discard rows from exact reconciliation.

For a score month, construct the reference profile from the component-wise median of the 12 preceding eligible monthly proportion vectors from the same contract, schema cohort and operating regime, then renormalize the vector to sum to one. This gives each month equal weight and limits the influence of an unusually large month or one extreme historical month. No calendar-month-of-year strata are used.

Use Jensen-Shannon divergence with base-2 logarithms and symmetric Dirichlet smoothing `alpha = 0.5` per declared bin. Report the divergence in bits, bounded from 0 to 1. Record the feature vector, reference vector, eligibility mask and computed distance for every run. This distance measures profile difference; it does not establish why the difference occurred.

## Warm-up calibration procedure

After the independent source review determines which 2022 months are eligible calibration controls:

1. For each eligible 2022 month, form a leave-one-month-out reference from the component-wise median of the other eligible 2022 monthly profiles. Apply the same binning, support and smoothing rules as above.
2. Compute both feature distances for every eligible month. Retain the paired distances so threshold selection accounts for checking two features together.
3. Set one family-wise threshold to the maximum of both feature distances across all eligible 2022 months, plus a fixed numerical tolerance of `1e-12`. A score month alerts if either feature exceeds this frozen threshold. Keep both individual distances in the report.
4. If fewer than 10 of the 12 months are independently eligible, do not derive or freeze a numeric threshold. Record P4 as unresolved and do not substitute a value selected from later months.
5. Store the threshold, eligible-month list, feature and bin definitions, calibration code identity, and hashes of all inputs and outputs in a versioned calibration artifact. Review this artifact before any 2023 or later detector evaluation.

The maximum leave-one-out distance is a conservative warm-up rule, not a statistical guarantee of a low false-positive rate. The 12 monthly calibration units are dependent and cover only one year. Evaluation must report the actual eligible clean-run denominator and uncertainty; zero alerts in warm-up cannot be presented as a validated false-positive rate. If source anomalies are unresolved or calibration coverage is insufficient, thresholds remain unset.

## Eligibility and limitations

- Exact checks run regardless of distribution-check eligibility.
- Distribution checks require 12 preceding months from the same contract, schema cohort and regime. The current owner decision leaves 2023-01 through 2024-12 eligible in principle and excludes all 2025 months.
- A month classified as a source anomaly or unresolved/disputed is not a clean calibration control. Record it separately under D4.
- The 2022 data include observed source findings. Until the independent oracle and anomaly criteria classify them, no monthly profile may be called independently verified clean for threshold calibration.
- Thresholds describe stability under this dataset and the declared pipeline only. They do not imply generalization to other years, fleets, or taxi systems.

## Required review before freeze

P4 is complete only after the anomaly criteria and 2022 control eligibility are independently reviewed, the calibration procedure has run using only eligible 2022 records, the resulting thresholds and hashes are recorded, and the decision note/protocol is updated to reference the calibration artifact. No 2023-2025 detector outputs may be inspected to revise the method. Any later change requires a new version and a new untouched evaluation set.

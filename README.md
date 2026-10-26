# Data Integrity Compiler: Milestone 1

A local, reproducible NYC TLC pipeline demonstrating two distinct kinds of evidence: a lookup uniqueness contract violation and measured downstream impact from an exact duplicated lookup row. This is a plumbing and attribution test, **not** a detection-recall, false-alarm-rate, or root-cause-accuracy benchmark.

## Setup and data

Requires Python 3.10–3.13. From this directory:

```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
```

Acquire official TLC sources (the project does not download them implicitly):

- Yellow taxi trip files: <https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page>
- Zone lookup CSV: <https://www.nyc.gov/assets/tlc/downloads/pdf/taxi_zone_lookup.csv>

Place immutable inputs at `data/raw/yellow_tripdata_YYYY-MM.parquet` and `data/raw/taxi_zone_lookup.csv`. `dic acquire --month YYYY-MM` records retrieval date, exact monthly source URLs, SHA-256 checksums, and schema comparison in `data/source-manifest.json`. It preserves the retrieval date when the month and source checksums are unchanged. The manifest retains separate entries for each month. Raw files are ignored by Git.

`contracts/pipeline.yaml` is loaded for every run and references `tlc-yellow-v1.json`. The combined contract hash covers both files and is recorded in reports and manifests. The JSON defines the January 2024 source schema and required columns. The known `cbd_congestion_fee` addition in 2025 is compatible. Missing required columns are incompatible; unrecognized additions, optional-column removals, and optional type changes require review and are recorded. TLC records can include negative fares, zero or invalid distances, out-of-range timestamps, null location IDs, and evolving fee columns. No source finding is silently repaired.

## Pipeline and semantics

```text
raw_trips → clean_trips → trip_enriched → daily_zone_metrics
```

The contract selects the join key. Daily metrics remain grouped by pickup date and pickup zone. Cleaning rules use structured `id`, `column`, `operator`, and optional `value` fields. Operators are restricted to `not_null`, `parseable_timestamp`, `>=`, and `>`. Column identifiers are checked against the referenced schema, and comparison values are bound as SQL parameters. Rejected rows are attributed to their first failing rule, with counts per rule that reconcile to the rejected total. Record identity is `(source SHA-256, DuckDB file_row_number)` assigned during ingestion of one immutable Parquet file. Never derive identity from unordered query output.

The contract configures join cardinality (`many_to_one` or `many_to_many`), lookup uniqueness severity (`block` or `warn`), and unmatched-key handling (`exclude` or `block`). The diagnostic LEFT JOIN reports matched, unmatched, and multiple-match counts. Counts and row inflation are exact. Fare and revenue use DuckDB DECIMAL arithmetic; JSON encodes money as decimal strings, and stage tables are written as Parquet by DuckDB. Logical fingerprints combine an exact row count with an order-independent sum of DuckDB row hashes. They support repeatability checks with the pinned DuckDB version, not cryptographic proofs. Source artifacts use SHA-256.

## Run the experiment

```powershell
python -m pytest
dic experiment-m1 --month 2024-01 --key 1
```

`experiment-m1` runs each pipeline attempt in its own subprocess, executes the clean run, injects one exact lookup-row copy for the selected key, runs the blocked fault case, evaluates it against separate ground truth, and independently reconciles saved Parquet outputs. The detector subprocess has an audit guard that fails if it opens a `ground_truth*` path. For `N_k` cleaned input trips matching the key, expected row inflation is `N_k × 1`. Duplicating the exact row doubles that zone's trip count and revenue; per-zone average fare stays unchanged because numerator and denominator both double.

## Safe publication and reports

Each run stages all artifacts under a unique run ID, validates contracts, then atomically replaces `data/published/CURRENT` via same-filesystem rename to a complete immutable version manifest. A failed validation publishes nothing. An existing version remains selected after a failed or interrupted attempt; interruption before pointer replacement can leave only an unreferenced staging/version directory, never a partially visible table set. Consumers resolve tables only through `CURRENT`. This prototype assumes a single writer on a local filesystem with atomic same-volume rename; it does not claim multi-writer or network-filesystem guarantees.

Every new report is validated at runtime against `schemas/report-v2.schema.json`; the v1 schema remains available for historical reports. Peak working set is measured in the dedicated experiment process. Linux reports `ru_maxrss` converted from KiB to bytes; macOS reports its native byte value; Windows uses the process peak working set. The report includes status, method, platform, units, conversion, and process scope. If measurement is unavailable, the run continues and records the reason. Reports include per-rule cleaning rejections, contract hash, independent checks, key multiplicities, impact, runtimes, publication decision, and diagnostic limitations. Observed invariant violations are separated from inferred cause.

The M1 defect is intentionally the exact case the uniqueness and row-conservation checks are designed to catch. Two or three clean-month controls are useful smoke tests, but zero alerts there is not a meaningful false-alarm-rate estimate. The join is also a single, obvious suspected transformation; do not claim root-cause accuracy until testing faults across at least three stages. A pre-existing duplicate lookup key is a baseline contract violation, not evidence of the injected fault. Conflicting-attribute duplicates, streaming, ML impact, UI/API, and broader benchmarks are deferred.

## Run the full-data validation on Kaggle

The local Windows environment may not have enough memory for every multi-million-row run. A CPU-only Kaggle Notebook is suitable for the DuckDB workload; the GPU is not used. Kaggle documents a CPU session with 4 CPU cores and 30 GB of RAM, with sessions up to 12 hours, subject to availability.

1. Build the source archive with git archive --format=zip --output=experiments/kaggle_upload/data-integrity-compiler-source.zip main, then upload it as a Kaggle Dataset.
2. Upload `experiments/kaggle_upload/kaggle_m1_validation.ipynb` as a notebook and attach that Dataset as input.
3. Enable Internet in notebook settings, select a CPU runtime, and run all cells. The notebook downloads official TLC sources and verifies the expected SHA-256 checksums before processing.
4. Download `dic-m1-validation-results.zip` from the notebook output and inspect the reports and Parquet reconciliation.

The notebook runs the February 2024 and January 2025 clean controls, two January 2024 clean runs for fingerprint repeatability, and the blocked M1 duplicate-key experiment. It exports the January clean run named by reconciliation, its manifest and contract hash, the repeat run, and the fault evidence. It also exports ground truth separately for evaluation and states that this single fault is not a recall or false-alarm benchmark.

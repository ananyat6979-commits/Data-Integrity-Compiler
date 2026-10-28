# M1 historical evidence

This bundle preserves the January clean controls and injected join-fault reports, manifests, source metadata, contract, report schema, and a compact aggregate witness. It excludes raw TLC inputs and materialized Parquet outputs. The verifier checks checksums, report and manifest consistency, contract identity, publication state, and the recorded aggregate sums. It cannot independently reproduce row-level results without the Parquet files.

The Kaggle platform notebook version was not present in the downloaded export; the notebook content hash is recorded in `provenance.json`.

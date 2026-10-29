# M1 historical evidence

This bundle preserves the January clean controls and injected join-fault reports, manifests, source metadata, contract, report schema, and a compact aggregate witness. It excludes raw TLC inputs and materialized Parquet outputs. The verifier checks checksums, report and manifest consistency, contract identity, publication state, and the recorded aggregate sums. It cannot independently reproduce row-level results without the Parquet files.

`kaggle_run_label` is a human-assigned run label, not a Kaggle platform version. The notebook SHA-256 identifies the exact executed notebook artifact committed at `experiments/kaggle_upload/kaggle_m1_validation.ipynb`. The compact witness establishes internal consistency and recorded aggregate arithmetic, not independent row-level reproduction; that requires the excluded Parquet files.

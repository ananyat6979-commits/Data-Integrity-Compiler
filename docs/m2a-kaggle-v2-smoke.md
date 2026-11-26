# Kaggle contract v2 smoke run

This procedure runs one audited full-size month through the M2a v2 pipeline and independently verifies the materialized outputs. It is a production-scale smoke run, not the M2a fault evaluation.

## Build the source upload

In PowerShell:

```powershell
Set-Location D:\Data\Models\data-integrity-compiler
git switch m2a-contract-v2-foundation
git pull
python experiments\build_source_archive.py --revision HEAD
$sourceDir = Join-Path (Get-Location) 'experiments\kaggle_upload'
$short = (git rev-parse --short HEAD).Trim()
$uploadDir = Join-Path $env:TEMP ("dic-m2a-source-$short-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $uploadDir | Out-Null
Copy-Item (Join-Path $sourceDir 'data-integrity-compiler-source.zip') (Join-Path $uploadDir 'data-integrity-compiler-source.zip.bin')
Copy-Item (Join-Path $sourceDir 'data-integrity-compiler-source.provenance.json') $uploadDir
Get-ChildItem -LiteralPath $uploadDir
```

The source archive builder writes these two files under `experiments\kaggle_upload`:

- `data-integrity-compiler-source.zip`
- `data-integrity-compiler-source.provenance.json`

Upload the two files from the temporary upload directory. The `.bin` suffix keeps the source ZIP bytes available for checksum verification because Kaggle can unpack ZIP files during upload.

## Upload the files to Kaggle

1. Open [Create a Kaggle Dataset](https://www.kaggle.com/datasets/new).
2. Give it a title such as `DIC M2a source <short commit>`. Keep visibility **Private**.
3. Upload both files printed by the PowerShell commands above. Create the dataset and wait for processing to finish.
4. Open [Kaggle Notebooks](https://www.kaggle.com/code) and create a new Python notebook.
5. In the notebook, choose **File**, then **Import Notebook**, and select [kaggle_m2a_v2_smoke.ipynb](../experiments/kaggle_upload/kaggle_m2a_v2_smoke.ipynb) from the project folder.
6. In the notebook's input pane, select **Add Input** and attach the private source dataset you just created.
7. In **Settings**, select a CPU session and enable **Internet**. The notebook downloads the TLC source and installs the pinned project requirements. Kaggle documents the input pane, Internet setting, and notebook output behavior in its [notebook guide](https://www.kaggle.com/docs/notebooks).
8. Run the notebook cells from top to bottom. The notebook checks the archive checksum and embedded revision, extracts into a new directory, creates an isolated environment under `/kaggle/temp`, downloads `yellow_tripdata_2023-01.parquet` and the official zone lookup, runs contract v2, and invokes the independent verifier.

## Retrieve and verify the result

The notebook writes `m2a-v2-smoke-<run_id>.zip` under `/kaggle/working`. Save a notebook version with **Save Version** and **Save & Run All** so Kaggle retains the output files. The ZIP will appear in the notebook's **Output** pane. Download it to the local machine.

The evidence archive contains the run report, manifest, Parquet outputs, publication pointer evidence, v2 contract, pinned source audit, and verification result. It does not include the raw TLC Parquet file. The local project already holds that file, and its hash is recorded in the evidence summary.

To verify the downloaded evidence locally, substitute the actual evidence folder and run ID:

```powershell
$evidence = 'D:\Data\Models\m2a-v2-smoke-evidence'
$summary = Get-Content (Join-Path $evidence 'evidence-summary.json') -Raw | ConvertFrom-Json
Set-Location 'D:\Data\Models\data-integrity-compiler'
& 'D:\Data\Models\data-integrity-compiler\.venv-m2a-verify\Scripts\python.exe' `
  -m experiments.m2a.verify_v2_run `
  --root $evidence `
  --run-dir (Join-Path $evidence ("data\runs\" + $summary.run_id)) `
  --source 'D:\Data\Models\data-integrity-compiler\data\raw\yellow_tripdata_2023-01.parquet' `
  --lookup 'D:\Data\Models\data-integrity-compiler\data\raw\taxi_zone_lookup.csv'
```

Success prints `valid_independent_reconciliation`. A blocked outcome can still verify correctly if the independent checks confirm that publication stayed blocked. Preserve the ZIP and the notebook version as the run evidence. Do not treat this one-month smoke run as M2a acceptance or as a false-alarm evaluation.

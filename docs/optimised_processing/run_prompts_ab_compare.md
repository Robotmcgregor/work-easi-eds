# Run prompts for A/B comparison (EASI)

This page is a copy/paste reference for terminal commands to generate comparable runs.

It assumes you are on EASI (bash shell) and the repo is available at:

- `/home/jovyan/work-easi-eds`

## 0) Common variables

Set these once per session (edit if needed):

```bash
export EASI_REPO="/home/jovyan/work-easi-eds"
export EDS_BUCKET="dcceew-eds-data"
export EDS_PREFIX="AROAZ6PFZYT4B4C7MNRHV:robotmcgregor/eds"

export NDVI_WORK="/home/jovyan/scratch/eds-work-optimised"
export EDS_WORK="/home/jovyan/scratch/eds-work-processing"

cd "$EASI_REPO"
```

## 1) Build NDVI products (required once per tile/date)

This ensures the NDVI scene products exist in S3.

```bash
python "$EASI_REPO/scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py" \
  --tile p089r080 \
  --s3-bucket "$EDS_BUCKET" \
  --s3-prefix "$EDS_PREFIX" \
  --work-dir "$NDVI_WORK" \
  --cloud-max 40 \
  --start-date 2025-06-07 \
  --end-date 2026-01-09
```

Notes:
- You usually do **not** need to rebuild NDVI for each EDS A/B run.
- If you changed NDVI code or want a clean rebuild, add `--rebase` (if supported by that script).

## 2) Run the EDS optimised processing pipeline (A/B variants)

This produces DLL/DLJ + masks/vectors and writes diagnostics CSVs used by the comparison notebook.

Common flags used in all runs:
- `--diagnostics` writes the per-run `*_summary.csv` and `*_sr_scale_verify.csv`
- `--run-id` keeps outputs separated (run scoped)

### Variant A: FORCE no SR scaling (debug baseline)

```bash
python "$EASI_REPO/scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py" \
  --tile p089r080 \
  --start-date 2025-06-07 \
  --end-date 2026-01-09 \
  --s3-bucket "$EDS_BUCKET" \
  --s3-prefix "$EDS_PREFIX" \
  --work-dir "$EDS_WORK" \
  --cloud-max 40 \
  --lookback 10 \
  --copy-to-home \
  --verbose \
  --diagnostics \
  --dlj-troubleshoot \
  --legacy-no-auto-sr-scale \
  --run-id run-no-auto-sr-scale
```

### Variant B: AUTO SR scaling (recommended default)

```bash
python "$EASI_REPO/scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py" \
  --tile p089r080 \
  --start-date 2025-06-07 \
  --end-date 2026-01-09 \
  --s3-bucket "$EDS_BUCKET" \
  --s3-prefix "$EDS_PREFIX" \
  --work-dir "$EDS_WORK" \
  --cloud-max 40 \
  --lookback 10 \
  --copy-to-home \
  --verbose \
  --diagnostics \
  --dlj-troubleshoot \
  --run-id run-auto-scale
```

### Variant C: MANUAL SR scaling factor (force 10000)

```bash
python "$EASI_REPO/scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py" \
  --tile p089r080 \
  --start-date 2025-06-07 \
  --end-date 2026-01-09 \
  --s3-bucket "$EDS_BUCKET" \
  --s3-prefix "$EDS_PREFIX" \
  --work-dir "$EDS_WORK" \
  --cloud-max 40 \
  --lookback 10 \
  --copy-to-home \
  --verbose \
  --diagnostics \
  --dlj-troubleshoot \
  --legacy-sr-scale 10000 \
  --run-id run-forced-10000
```

### Variant D: LEGACY baseline stats (include nodata zeros)

This flag switches the legacy baseline calculation to include nodata zeros in baseline mean/std/slope.
Default (recommended) behavior ignores zeros (treats 0 as nodata).

```bash
python "$EASI_REPO/scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py" \
  --tile p089r080 \
  --start-date 2025-06-07 \
  --end-date 2026-01-09 \
  --s3-bucket "$EDS_BUCKET" \
  --s3-prefix "$EDS_PREFIX" \
  --work-dir "$EDS_WORK" \
  --cloud-max 40 \
  --lookback 10 \
  --copy-to-home \
  --verbose \
  --diagnostics \
  --dlj-troubleshoot \
  --legacy-baseline-include-nodata \
  --run-id run-baseline-include-nodata
```

Notes:
- `--run-id` is an alias for `--run-tag` (they are mutually exclusive).
- You typically do **not** need `--rebase` for A/B runs because each `--run-id` writes to a different run folder.
- If you *do* use `--rebase`, it will overwrite existing derived products (useful when re-running the same run-id).

## 3) Generating per-tile commands from Excel (example)

This is an example pattern for printing commands for many tiles. It is intended to run inside a notebook.

```python
import pandas as pd

# Read Excel (same directory as notebook)
df = pd.read_excel("202602_run_summary 1.xlsx", sheet_name="Sheet1")

# Normalise fields
df["tile"] = df["scene"].astype(str).str.lower().str.strip()
df["start"] = df["startdate_iso"].astype(str).str.strip()  # YYYY-MM-DD
df["end"] = df["enddate_iso"].astype(str).str.strip()      # YYYY-MM-DD

EASI_REPO = "/home/jovyan/work-easi-eds"
EDS_BUCKET = "dcceew-eds-data"
EDS_PREFIX = "AROAZ6PFZYT4B4C7MNRHV:robotmcgregor/eds"
NDVI_WORK = "/home/jovyan/scratch/eds-work-optimised"
EDS_WORK = "/home/jovyan/scratch/eds-work-processing"

NDVI_TEMPLATE = f"""python {EASI_REPO}/scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \\
  --tile {{tile}} \\
  --s3-bucket {EDS_BUCKET} \\
  --s3-prefix '{EDS_PREFIX}' \\
  --work-dir {NDVI_WORK} \\
  --cloud-max 40 \\
  --start-date {{start}} \\
  --end-date {{end}}\
"""

EDS_BASE = f"""python {EASI_REPO}/scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py \\
  --tile {{tile}} \\
  --start-date {{start}} \\
  --end-date {{end}} \\
  --s3-bucket {EDS_BUCKET} \\
  --s3-prefix '{EDS_PREFIX}' \\
  --work-dir {EDS_WORK} \\
  --cloud-max 40 \\
  --lookback 10 \\
  --copy-to-home \\
  --verbose \\
  --diagnostics \\
  --dlj-troubleshoot\
"""

EDS_NO_AUTO = EDS_BASE + """ \\
  --legacy-no-auto-sr-scale \\
  --run-id run-no-auto-sr-scale\
"""

EDS_AUTO = EDS_BASE + """ \\
  --run-id run-auto-scale\
"""

EDS_FORCED_10000 = EDS_BASE + """ \\
  --legacy-sr-scale 10000 \\
  --run-id run-forced-10000\
"""

EDS_BASELINE_INCLUDE_NODATA = EDS_BASE + """ \\
  --legacy-baseline-include-nodata \\
  --run-id run-baseline-include-nodata\
"""

for r in df.itertuples(index=False):
    print("# ====================================================")
    print(f"# TILE: {r.tile}")
    print("# ====================================================\n")

    print("# --- Build NDVI products ---")
    print(NDVI_TEMPLATE.format(tile=r.tile, start=r.start, end=r.end))

    print("# --- Run EDS (Variant A: no auto SR scaling) ---")
    print(EDS_NO_AUTO.format(tile=r.tile, start=r.start, end=r.end))

    print("# --- Run EDS (Variant B: auto SR scaling) ---")
    print(EDS_AUTO.format(tile=r.tile, start=r.start, end=r.end))

    print("# --- Run EDS (Variant C: forced SR scale = 10000) ---")
    print(EDS_FORCED_10000.format(tile=r.tile, start=r.start, end=r.end))

    print("# --- Run EDS (Variant D: baseline include nodata zeros) ---")
    print(EDS_BASELINE_INCLUDE_NODATA.format(tile=r.tile, start=r.start, end=r.end))
    print("\n\n")
```

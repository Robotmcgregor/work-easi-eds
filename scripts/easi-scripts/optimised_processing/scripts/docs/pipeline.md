# Pipeline overview — `eds_master_pipeline_optimised.py`

## Purpose

This pipeline runs an “optimised” version of the EDS seasonal-window change detection using **NDVI** time-series plus a **spectral index** from start/end SR composites.

It is designed to be:

- **Repeatable**: all work is written into a run-scoped folder (`<work-dir>/<tile>/<run-tag>/`).
- **Cloud-friendly**: intermediate products are stored in S3; final outputs are Cloud Optimised GeoTIFFs (COGs).
- **Legacy-compatible**: the core clearing logic is implemented in a legacy-style method that produces DLL/DLJ rasters used by downstream QA tooling.

## Inputs (high level)

- Tile: `p###r###` (e.g. `p115r078`)
- Date range: start/end dates (requested); the pipeline resolves effective SR dates that actually exist.
- Data sources:
  - Datacube products for SR (GA0) and NDVI/FFMASK (GA1/GA2)
  - S3 bucket/prefix for derived products and final outputs

## Outputs (high level)

- GA1 NDVI scenes (float32, nodata = -9999) in S3 under the canonical tile/date layout
- GA0 SR composites (6-band float32, nodata = -9999 for cloud-masked) in S3 + local run folder
- **DLL** (uint8, 1 band) + **DLJ** (uint8, 4 bands) in the run output folder
- Final COG versions of DLL/DLJ uploaded to `.../tiles/<tile>/outputs/<run_tag>/...`
- Threshold masks + polygons/shapefiles derived from DLJ band 4 (`clearingProb`)

## End-to-end steps (what the code does)

The pipeline is intentionally broken into numbered “tasks” (see `tasks/`). The main flow is:

### Step 1 — Resolve effective SR start/end scenes

File: `tasks/task02_resolve_sr_dates.py`

- Searches SR scenes in datacube overlapping the tile.
- Applies `--cloud-max` filter.
- Picks:
  - **start scene** closest on/before the requested start date
  - **end scene** closest on/after the requested end date

This yields the *effective* start/end dates used for the rest of the pipeline.

### Step 2 — Build seasonal NDVI baseline plan

File: `tasks/task03_ensure_seasonal_ndvi.py`

- Builds a **SeasonalWindow** around the effective dates (window is expanded by 2 months).
- Pulls NDVI candidate scenes from datacube, then filters to:
  - years in `[end_year - lookback_years, end_year]`
  - dates inside the seasonal window

The result is a list of (date, platform, epsg, bbox…) rows that should exist in S3.

### Step 3 — Ensure GA1 NDVI exists in S3

Files:
- `tasks/task03_ensure_seasonal_ndvi.py`
- `tasks/task03_process_scene_ndvi.py`

For each planned date:

- Loads `nbart_red`, `nbart_nir`, `oa_fmask` from datacube.
- Masks to clear land (`oa_fmask == 1`) and writes:
  - **NDVI** (`ga1-clr`) as float32 COG (nodata -9999)
  - **FFMASK** (`ga2`) as uint8 COG
- Uploads both to S3.

### Step 4 — Stage (download) GA1 NDVI locally

File: `tasks/task07_stage_ga1_locally.py`

The legacy method reads NDVI scenes from local disk, so the pipeline downloads the required GA1 COGs into the run folder.

### Step 5 — Build GA0 SR composites (start & end)

File: `tasks/task04_build_ga0_sr_composite.py`

For the resolved SR start and end scenes:

- Loads 6 SR bands + `oa_fmask` from datacube.
- Picks the best time slice by maximum clear-land fraction.
- Writes two products:
  - **RAW** GA0 (unmasked)
  - **CLR** GA0 (cloud-masked, nodata -9999)

The pipeline passes the **CLR** GA0 stacks into the legacy method.

### Step 6 — Run legacy seasonal-window method (produces DLL/DLJ)

Files:
- `tasks/task05_run_legacy_method.py`
- `methods/legacy_window_ndvi_envi.py`

- Invokes `methods/legacy_window_ndvi_envi.py` as a subprocess.
- Inputs:
  - Local GA1 NDVI scenes (baseline time-series)
  - GA0 start and GA0 end cloud-masked SR stacks
- Outputs:
  - `*_dll_*.tif` (classification)
  - `*_dlj_*.tif` (interpretation; includes `clearingProb`)

Details are in [DLL/DLJ outputs](outputs_dll_dlj.md).

### Step 7 — Convert outputs to final COGs and upload

File: `tasks/task06_convert_and_upload_outputs.py`

- Ensures the outputs are Cloud Optimised GeoTIFFs.
- Uploads final DLL/DLJ COGs to:

`{s3_prefix}/tiles/{tile}/outputs/{run_tag}/...`

### Step 8 — Create masks and polygons from DLJ

File: `tasks/task08_masks_and_vectors.py`

- Reads **DLJ band 4** (`clearingProb`).
- Produces two masks:
  - **strong**: `clearingProb >= --strong-threshold` (default 60)
  - **clear**:  `clearingProb >= --clear-threshold` (default 80)
- Polygonises masks and writes shapefiles.
- Uploads masks and vectors to S3.

## Local run folder layout

`<work-dir>/<tile>/<run-tag>/`

- `ndvi_work/` — scratch for NDVI computation
- `ga1_stage/` — staged GA1 NDVI COGs downloaded from S3
- `ga0_work/` — GA0 SR composites
- `legacy_outputs/` — DLL/DLJ + log JSON from legacy method
- `outputs_cog/` — final COGs prepared for upload
- `maskvec_work/` — mask rasters and shapefile folders
- `diagnostics/` — optional debug rasters + CSV/JSON/PNG summaries

## Minimal run command (example)

The exact parameters depend on your environment (AWS creds, datacube config, etc.), but conceptually:

```bash
python eds_master_pipeline_optimised.py \
  --tile p115r078 \
  --start-date 2025-06-07 \
  --end-date 2026-01-25 \
  --s3-bucket <bucket> \
  --s3-prefix <prefix> \
  --work-dir <local-work-dir>
```

See `--help` on the script for all flags.

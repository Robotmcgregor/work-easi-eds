# CLI flags reference — `eds_master_pipeline_optimised.py`

This page explains how to run the **EDS (seasonal-window NDVI)** pipeline and what each CLI flag does.

If you just want to run it with defaults, start with the **Minimal run** example and only change:

- `--tile`
- `--start-date`, `--end-date`
- `--s3-bucket`, `--s3-prefix`
- `--work-dir`

---

## Minimal run

```bash
python eds_master_pipeline_optimised.py \
  --tile p115r078 \
  --start-date 2025-06-07 \
  --end-date 2026-01-25 \
  --s3-bucket <bucket> \
  --s3-prefix <prefix> \
  --work-dir <local-work-dir>
```

---

## Required flags

- `--tile`
  - WRS tile in `p###r###` format (example: `p115r078`).
- `--start-date`, `--end-date`
  - Requested date window in `YYYY-MM-DD`.
  - The pipeline will pick *effective* SR dates close to these.
- `--s3-bucket`, `--s3-prefix`
  - Where derived products and run outputs are written.
- `--work-dir`
  - Local workspace for this run.
  - Creates/uses a run-scoped folder: `<work-dir>/<tile>/<run_tag>/...`.

---

## Run recording (manifest + run log)

These are the **authoritative records** for what the EDS run actually used.

- `--run-log-uri`
  - Master parquet log of EDS runs (S3 or local path).
  - Default: `s3://<bucket>/<prefix>/runs/optimised_eds_runs.parquet`.
  - The pipeline appends a new row at the start (status `running`) and finalises it at the end.
- `--run-manifest-uri`
  - Where to write the **run manifest parquet** (S3 or local path).
  - The run manifest contains the seasonal NDVI baseline plan rows plus metadata (run id/tag, requested/effective dates, seasonal window bounds, SR picks, etc.).
  - Default: `s3://<bucket>/<prefix>/runs/manifests/<tile>/<run_tag>_manifest.parquet`.

Notes:
- Writing either parquet **overwrites that parquet object/path** (it does not delete other outputs).
- The run manifest is also written locally to `<run_root>/run_manifest.parquet` as a staging file.

---

## Data selection & quality

- `--tile-shp`
  - Shapefile used to resolve tile bounds/metadata.
  - Default: `/home/jovyan/assets/eds_lsat_grid_min_max.shp`.
- `--cloud-max`
  - Maximum cloud cover (scene metadata) to accept when searching datacube.
  - Default: `40.0`.
- `--sr-products`
  - Datacube product(s) to use for SR (GA0 composites).
  - Default: `ga_ls8c_ard_3 ga_ls9c_ard_3`.
- `--ndvi-products`
  - Datacube product(s) to use for NDVI/FFMASK (GA1/GA2).
  - Default: `ga_ls8c_ard_3 ga_ls9c_ard_3`.
- `--lookback`
  - Number of years for the seasonal NDVI baseline plan.
  - Default: `10`.

---

## CRS & performance

- `--target-epsg`
  - Force the output EPSG used for derived products (NDVI, GA0, outputs).
  - Default `0` means “derive EPSG per scene (UTM) from bbox centre”.
- `--resolution`
  - Output pixel size in metres.
  - Default: `30.0`.
- `--chunk`
  - Dask chunk size used when loading data.
  - Default: `2048`.

---

## Behaviour controls

- `--rebase`
  - Overwrite/rebuild derived products even if they already exist.
- `--dry-run`
  - Plans and prints what it would do, but does not compute/upload.

---

## Diagnostics & debug

- `--verbose`
  - Print additional per-step logs.
- `--diagnostics`
  - Enables extra diagnostic outputs from the legacy method (CSV/JSON and sometimes a PNG).
  - The pipeline stages these under `<run_root>/diagnostics/` and uploads them to the diagnostics S3 prefix.
- `--dlj-troubleshoot`
  - After DLJ is produced, prints basic pixel stats per band.
- `--stop-after-dlj`
  - Exit immediately after DLJ is produced (skip COG conversion, upload, masks/vectors).

---

## Run identity (output folder naming)

- `--run-tag`
  - Explicit run folder name under `<work-dir>/<tile>/...` and `.../tiles/<tile>/outputs/<run_tag>/...`.
- `--run-id`
  - Alias for `--run-tag` (mutually exclusive).

Default run tag:
- `{tile}_d{requested_start_yyyymmdd}{requested_end_yyyymmdd}`

---

## Mask/vector thresholds

- `--strong-threshold`
  - DLJ band 4 (`clearingProb`) threshold for the “strong” mask.
  - Default: `60`.
- `--clear-threshold`
  - DLJ band 4 (`clearingProb`) threshold for the “clear” mask.
  - Default: `80`.
- `--min-area-ha`
  - Minimum polygon area (hectares) when polygonising masks.
  - Default: `10.0`.

---

## Legacy method knobs (A/B testing)

These flags are passed through to the legacy method script.

- `--legacy-sr-scale`
  - Manual override for SR scaling before the legacy method’s `log1p()` spectral index.
- `--legacy-no-auto-sr-scale`
  - Disable SR auto-scaling and force no scaling.
- `--legacy-baseline-include-nodata`
  - Use legacy baseline-stats behaviour (include nodata zeros).

---

## Convenience: copy outputs to home

- `--copy-to-home`
  - Copy key outputs to a folder under `--home-out-dir`.
- `--home-out-dir`
  - Base path for `--copy-to-home`.
  - Default: `/home/jovyan/eds-outputs`.
- `--zip-home`
  - After copying to home, zip the run folder.

---

## Convenience: export raw SR COGs

- `--export-sr-raw-cog`
  - Copy the unmasked (RAW) GA0 SR composites into a run-scoped folder.
- `--export-sr-raw-cog-dirname`
  - Folder name under the run root (default: `sr_raw_cog`).

# Output locations (normal vs `--diagnostics`)

This document lists **every on-disk and S3 output location** produced by the optimised EDS pipeline.

It’s written to answer two practical questions:

1. **Where did my files go?** (especially when `--diagnostics` was enabled)
2. **Which step created this file?**

---

## Placeholders used

These templates use the following placeholders:

- `{work_dir}`: the local `--work-dir` passed to the pipeline
- `{tile}`: WRS tile, e.g. `p115r078`
- `{run_tag}`: run folder name
  - default: `{tile}_d{start_yyyymmdd}{end_yyyymmdd}` (based on *effective* start/end)
  - can be overridden with `--run-tag` / `--run-id`
- `{start_yyyymmdd}`, `{end_yyyymmdd}`: effective SR dates chosen by the pipeline (format `YYYYMMDD`)
- `{yyyymmdd}`: a scene date in `YYYYMMDD`
- `{yyyymm}`: month bucket derived from `{yyyymmdd}` (format `YYYYMM`)
- `{epsg}`: output EPSG code used in filenames
- `{platform}`: `sl8`, `sl9`, etc.
- `{s3_bucket}`, `{s3_prefix}`: S3 destination configured on the CLI

### Example values

Example “friendly” run:

- `{tile}` = `p115r078`
- requested `--start-date` = `2025-06-07`
- requested `--end-date` = `2026-01-09`
- example effective dates (chosen by datacube + cloud filtering):
  - `{start_yyyymmdd}` = `20250607`
  - `{end_yyyymmdd}` = `20260109`
- default `{run_tag}` = `p115r078_d2025060720260109`

---

## Local run folder layout (pipeline entrypoint)

When you run the pipeline entrypoint, outputs are run-scoped under:

- `{run_root}` = `{work_dir}/{tile}/{run_tag}/`

Subfolders (created every run):

- `{run_root}/ndvi_work/` (scratch)
- `{run_root}/ga1_stage/` (local NDVI inputs used by legacy)
- `{run_root}/ga0_work/` (local GA0 SR composites)
- `{run_root}/legacy_outputs/` (legacy outputs written by the legacy method)
- `{run_root}/outputs_cog/` (final DLL/DLJ COG outputs)
- `{run_root}/maskvec_work/` (masks + vectors)
- `{run_root}/diagnostics/` (diagnostics files; also used as legacy `--diagnostics-dir`)

Run-scoped parquet written by the pipeline (authoritative record of what the run used):

- `{run_root}/run_manifest.parquet`

Optional subfolder (only if `--export-sr-raw-cog`):

- `{run_root}/sr_raw_cog/` (or whatever `--export-sr-raw-cog-dirname` is set to)

---

## Normal outputs (always produced)

### 0) Run recording outputs (authoritative)

These are the “recorded” artefacts that describe **exactly** what the run used.

Master run log parquet:

- Default location (if `--run-log-uri` is omitted):
  - `s3://{s3_bucket}/{s3_prefix}/runs/optimised_eds_runs.parquet`
- If `--run-log-uri` is provided, it can be either:
  - `s3://...` (uploaded)
  - a local file path (written locally)

Run manifest parquet (baseline plan + SR picks):

- Local staging file (always written best-effort):
  - `{run_root}/run_manifest.parquet`
- Default destination (if `--run-manifest-uri` is omitted):
  - `s3://{s3_bucket}/{s3_prefix}/runs/manifests/{tile}/{run_tag}_manifest.parquet`
- If `--run-manifest-uri` is provided, it can be either:
  - `s3://...` (uploaded)
  - a local file path (moved/written locally)

### 1) GA1 NDVI scenes in S3 (baseline time-series)

These are *canonical per-date* outputs. They are created if missing (or if `--rebase`).

S3 keys:

- `{s3_prefix}/tiles/{tile}/{YYYY}/{yyyymm}/{platform}olre_{tile}_{yyyymmdd}_ga1-clr_e{epsg}.tif`
  - NDVI (float32 COG), masked to clear land, NoData = `-9999`
- `{s3_prefix}/tiles/{tile}/{YYYY}/{yyyymm}/{platform}olre_{tile}_{yyyymmdd}_ga2_e{epsg}.tif`
  - “ffmask” / keep-mask (uint8 COG), NoData = `0`

Local scratch during creation (usually **deleted** after upload unless `rebase=True` in the NDVI task):

- `{run_root}/ndvi_work/{platform}olre_{tile}_{yyyymmdd}_ga1-clr_e{epsg}.tif`
- `{run_root}/ndvi_work/{platform}olre_{tile}_{yyyymmdd}_ga2_e{epsg}.tif`

### 2) GA1 staging (download NDVI COGs locally for legacy)

Local files (downloaded and **kept**) under:

- `{run_root}/ga1_stage/{platform}olre_{tile}_{yyyymmdd}_ga1-clr_e{epsg}.tif`

Note: staging currently downloads NDVI (`ga1-clr`) only.

### 3) GA0 SR composites (start + end)

These are per-date SR composites in S3 and local copies for the run.

S3 keys:

- `{s3_prefix}/tiles/{tile}/{YYYY}/{yyyymm}/{platform}olre_{tile}_{yyyymmdd}_ga0_e{epsg}.tif`
  - RAW (unmasked) SR composite (float32 COG)
- `{s3_prefix}/tiles/{tile}/{YYYY}/{yyyymm}/{platform}olre_{tile}_{yyyymmdd}_ga0-clr_e{epsg}.tif`
  - CLR (cloud/land-clear masked) SR composite (float32 COG), NoData = `-9999`

Local files (kept) under:

- `{run_root}/ga0_work/{platform}olre_{tile}_{yyyymmdd}_ga0_e{epsg}.tif`
- `{run_root}/ga0_work/{platform}olre_{tile}_{yyyymmdd}_ga0-clr_e{epsg}.tif`

### 4) Legacy method outputs (DLL/DLJ)

Local files written by the legacy method under:

- `{run_root}/legacy_outputs/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dll_e{epsg}.tif`
- `{run_root}/legacy_outputs/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dlj_e{epsg}.tif`

Optional (only if the legacy method emits it):

- `{run_root}/legacy_outputs/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dll_log_e{epsg}.json`

Important defaulting behavior (when running the legacy script *standalone*):

- If `--output-dir` is omitted, it writes into your **current working directory**.
- If `--diagnostics-dir` is omitted, it defaults to `{output_dir}/diagnostics/`.

### 5) Final run outputs (DLL/DLJ as COGs) uploaded to S3

Local COGs (kept) under:

- `{run_root}/outputs_cog/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dll_e{epsg}.tif`
- `{run_root}/outputs_cog/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dlj_e{epsg}.tif`

S3 keys:

- `{s3_prefix}/tiles/{tile}/outputs/{run_tag}/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dll_e{epsg}.tif`
- `{s3_prefix}/tiles/{tile}/outputs/{run_tag}/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dlj_e{epsg}.tif`

### 6) Masks (GeoTIFF COGs) and vectors (Shapefile set)

Local mask rasters (kept) under:

- `{run_root}/maskvec_work/masks/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dlj-strong-ge{strong}_e{epsg}.tif`
- `{run_root}/maskvec_work/masks/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dlj-clear-ge{clear}_e{epsg}.tif`

S3 keys:

- `{s3_prefix}/tiles/{tile}/outputs/{run_tag}/masks/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dlj-strong-ge{strong}_e{epsg}.tif`
- `{s3_prefix}/tiles/{tile}/outputs/{run_tag}/masks/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_dlj-clear-ge{clear}_e{epsg}.tif`

Local vector folders (kept) under:

- `{run_root}/maskvec_work/vectors/strong/`
- `{run_root}/maskvec_work/vectors/clear/`

Each folder contains a standard ESRI Shapefile set (sidecars vary by environment, but typically):

- `*.shp`, `*.shx`, `*.dbf`, `*.prj` (and sometimes `*.cpg`)

And also a single-file GeoPackage:

- `*.gpkg`

S3 prefixes (folders):

- `{s3_prefix}/tiles/{tile}/outputs/{run_tag}/vectors/strong_ge{strong}/`
- `{s3_prefix}/tiles/{tile}/outputs/{run_tag}/vectors/clear_ge{clear}/`

---

## `--diagnostics` outputs (only when enabled)

When you pass `--diagnostics` to the pipeline, it passes `--diagnostics` through to the legacy method and sets:

- legacy `--diagnostics-dir` = `{run_root}/diagnostics/`

The pipeline also uploads the resulting diagnostics artefacts to S3 under a dedicated prefix (kept separate from the main run outputs):

- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/...`

### Legacy diagnostic rasters

- `{run_root}/diagnostics/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_combined_raw_e{epsg}.tif`
  - float32, NoData = `-9999` (masked pixels)

S3 key (uploaded by the pipeline):

- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/{platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_combined_raw_e{epsg}.tif`

### Legacy diagnostic CSV/JSON/PNG files

All names below share a base:

- `diag_name_base = {platform}olre_{tile}_d{start_yyyymmdd}{end_yyyymmdd}_{vi_tag}_e{epsg}`
- plus a suffix derived from settings (e.g. SR scaling mode)

Files written into `{run_root}/diagnostics/`:

- `{diag_name}_ndviDiffStdErr_stats.csv`
- `{diag_name}_ndviDiffStdErr_bins.csv`
- `{diag_name}_runmeta.json`
- `{diag_name}_summary.csv`
- `{diag_name}_sr_scale_verify.csv`
- `{diag_name}_ndviDiffStdErr.png` (only if `matplotlib` is available and diagnostics dir is local)

S3 keys (uploaded by the pipeline):

- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/{diag_name}_ndviDiffStdErr_stats.csv`
- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/{diag_name}_ndviDiffStdErr_bins.csv`
- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/{diag_name}_runmeta.json`
- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/{diag_name}_summary.csv`
- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/{diag_name}_sr_scale_verify.csv`
- `{s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/{diag_name}_ndviDiffStdErr.png`

---

## Optional outputs (extra flags)

### `--export-sr-raw-cog`

Copies the *raw* GA0 SR composites into a dedicated subfolder under the run root:

- `{run_root}/sr_raw_cog/{platform}olre_{tile}_{start_yyyymmdd}_ga0_e{epsg}.tif`
- `{run_root}/sr_raw_cog/{platform}olre_{tile}_{end_yyyymmdd}_ga0_e{epsg}.tif`

(Note: this is a copy of the GA0 RAW products already present in `{run_root}/ga0_work/`.)

### `--copy-to-home` (and optional `--zip-home`)

Copies key artefacts into a single “user-friendly” folder:

- `{home_out_dir}/{run_tag}/`

Subfolders created:

- `sr_ga0/` (GA0 raw + clr for start/end)
- `legacy_outputs/` (legacy DLL/DLJ and sidecars)
- `cog_outputs/` (final DLL/DLJ COGs)
- `masks/` (strong/clear masks)
- `vectors/` (all vector sidecars from both strong/clear)

If `--zip-home` is set:

- `{home_out_dir}/{run_tag}.zip`

---

## Quick troubleshooting: “Why did diagnostics go to my home directory?”

That happens when the legacy method is run with default directories:

- `output_dir` defaults to the **current working directory** (`os.getcwd()`)
- `diagnostics_dir` defaults to `{output_dir}/diagnostics/`

To force outputs into a known run folder, always set both:

- `--output-dir <somewhere>/legacy_outputs`
- `--diagnostics-dir <somewhere>/diagnostics`

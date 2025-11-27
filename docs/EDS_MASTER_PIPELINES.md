# EDS Master Pipelines

This document explains the two top‑level EDS master scripts, how to run them, what they call under the hood, and where to find the outputs.

- Data acquisition and preparation: `scripts/eds_master_data_pipeline.py`
- Processing/orchestration: `scripts/eds_master_processing_pipeline.py`

Both are designed for Windows PowerShell on a GDAL‑enabled Python (Conda env recommended).

---

## 1) EDS Master Data Pipeline (`scripts/eds_master_data_pipeline.py`)

Purpose: Download and prepare all source data needed for EDS processing for a given Landsat WRS2 tile and date window.

### What it does (high level)
1. Optional fast‑path: pulls FC products from an S3 mirror (if available).
2. Ensures SR composites exist near your start and end dates (±search tolerance), restricted to Landsat 8/9 only.
3. Downloads seasonal FC from GA/DEA with platform restriction to Landsat 8/9.
3. Downloads seasonal FC for multiple years/months to build a robust baseline.
4. Downloads FMASK products and applies clear masks to produce `*_fc3ms_clr.tif`.
5. Prints an inventory and validates that you have at least two SRs and some clear‑masked FC.

### Scripts it calls
- `scripts/download_fc_from_s3.py` — optional, quick FC sync from S3.
- `scripts/ensure_sr_dates_for_eds.py` — finds/ensures SR for the requested start/end.
- `scripts/download_seasonal_fc_from_ga.py` — comprehensive FC download from GA/DEA (platform-filtered to LS8/9).
- `scripts/download_fmask_for_fc.py` — fetches FMASK products for FC.
- One of:
  - `scripts/mask_lsat.py`, or
  - `scripts/derive_fc_clr.py`, or
  - `scripts/qv_applystdmasks.py` — applies the clear mask to FC to create `*_fc3ms_clr.tif`.

### Key inputs
- `--tile` (required): Landsat WRS2 tile, e.g. `089_078`.
- `--start-date` / `--end-date` (required): `YYYYMMDD`.
- `--dest`: root folder for all data, default `D:\data\lsat`.

Optional:
- `--span-years` (default 10): how many years to include for the FC baseline.
- `--cloud-cover` (default 50): maximum % cloud for downloads.
- `--search-days` (default 7): SR search tolerance around target dates.
- `--skip-s3`, `--skip-sr`, `--skip-fc`, `--skip-masking`: turn off steps.
- `--sr-root`, `--fc-root`: accepted as aliases for `--dest` (for compatibility).
- `--fc-end-year`: override the computed FC end year (default is `min(current_year, end_year+1)`).
- `--dry-run`: print steps without executing.

### Output layout (by tile)
Under `--dest`, e.g. `D:\data\lsat\089_078\...` you’ll have a mixture of:
- SR composites (Landsat 8/9 only) such as `ga_ls9c_ard_089078_YYYYMMDD_srb6/7.tif` or `ga_ls8c_ard_089078_YYYYMMDD_srb6/7.tif` (or per‑band files).
- FC raw (`*_fc3ms.tif`) and clear‑masked (`*_fc3ms_clr.tif`).
- FMASK products (`*_fmask.tif`).

### Example (PowerShell)
```powershell
C:\ProgramData\anaconda3\envs\slats\python.exe scripts\eds_master_data_pipeline.py `
  --tile 089_078 `
  --start-date 20230720 `
  --end-date 20240831 `
  --span-years 10 `
  --dest D:\data\lsat
```

Tips:
- Add `--dry-run` first to verify the plan.
- If you already have SR and FC, keep this step for validation and masking.
- For strict LS8/9-only FC provenance, prefer the GA download path (step 3) or run with `--skip-s3` to avoid hydrating from S3 keys that cannot be platform-filtered.

---

## 2) EDS Master Processing Pipeline (`scripts/eds_master_processing_pipeline.py`)

Purpose: Orchestrate the full SLATS‑style processing using already‑downloaded data to produce EDS change rasters and polygons.

### What it does (high level)
1. Build “compat” inputs (db8 reflectance stacks + dc4 FPC timeseries) or reuse existing.
2. Run the legacy seasonal change method to produce DLL (classes) and DLJ (interpretation).
3. Apply styling to DLL/DLJ.
4. Polygonize DLL into thresholded merged shapefiles (classes ≥34).
5. Post‑process vectors (dissolve, skinny filter) and optionally clip by FC coverage masks.

### Scripts it calls
- `scripts/slats_compat_builder.py` — builds db8/dc4 + footprint in a QLD‑compatible layout.
- `scripts/eds_legacy_method_window.py` — computes DLL (`*_dllmz.img`) and DLJ (`*_dljmz.img`).
- `scripts/style_dll_dlj.py` — sets palette/band names on DLL/DLJ.
- `scripts/polygonize_merged_thresholds.py` — polygons for thresholds 34..39 with min area.
- `scripts/vector_postprocess.py` — dissolve/skinny filtering.
- `scripts/fc_coverage_extent.py` — builds union and presence masks over the FC stack.
- `scripts/clip_vectors.py` — optional: clips cleaned polygons to FC masks.

### Key inputs
- `--tile` (required): `PPP_RRR`, e.g. `094_076`.
- `--start-date` / `--end-date` (required): requested dates; the script will resolve effective dates with nearest SR composite when exact isn’t present.
- `--sr-dir-start` / `--sr-dir-end` (required): directory or composite file for SR start/end (accepts `*_srb6/7.tif` or a folder containing per‑band files).

Optional:
- `--sr-root`, `--fc-root`: roots for discovery/fallback of SR/FC.
- `--out-root`: where to write compat and results (default `data/compat/files`).
- `--season-window`: e.g. `0701 1031`.
- `--span-years`: baseline years (lookback) for the legacy method (default 2, cap 10).
- `--fc-only-clr`: use only `*_fc3ms_clr.tif` for dc4; default prefers clr when both exist.
- `--thresholds`: default `34 35 36 37 38 39`.
- `--min-ha`: min area filter for polygons (default 1 ha).
- `--skinny-pixels`: skinny filter for vector post‑process (default 3).
- `--ratio-presence`: one or more ratios (e.g., `0.95 0.90`) to generate FC presence masks.
- `--python-exe`: force a GDAL-enabled interpreter for all subprocesses.
- `--force-compat`: rebuild compat even when products already exist.
- `--dry-run`: print the plan.

### Output layout (by scene)
Under `--out-root/<scene>`, e.g. `data/compat/files/p094r076/`:
- `lztmre_<scene>_<YYYYMMDD>_db8mz.img` — SR reflectance stack (start/end).
- `lztmre_<scene>_<YYYYMMDD>_dc4mz.img` — FC green (FPC) timeseries images.
- `lztmna_<scene>_eall_dw1mz.img` — footprint mask (1 inside, 0 NoData).
- `lztmre_<scene>_d<start><end>_dllmz.img` — change classes (10=no clearing, 3=flag, 34..39=clearing).
- `lztmre_<scene>_d<start><end>_dljmz.img` — interpretation stack.
- `shp_d<start>_<end>_merged_min<ha>` — thresholded merged polygons (34..39).
- `shp_d<start>_<end>_merged_min<ha>_clean` — dissolved + skinny‑filtered polygons.
- `fc_coverage/` — union and presence masks; optional clip outputs in `..._clean_clip_*`.

### Example (PowerShell)
```powershell
C:\ProgramData\anaconda3\envs\slats\python.exe scripts\eds_master_processing_pipeline.py `
  --tile 094_076 `
  --start-date 20230724 `
  --end-date 20240831 `
  --sr-dir-start D:\data\lsat\094_076\2023\202307\ga_ls9c_ard_094076_20230724_srb7.tif `
  --sr-dir-end   D:\data\lsat\094_076\2024\202408\ga_ls8c_ard_094076_20240831_srb7.tif `
  --sr-root D:\data\lsat `
  --fc-root D:\data\lsat `
  --out-root data\compat\files `
  --season-window 0701 1031 `
  --fc-only-clr `
  --ratio-presence 0.95 0.90 `
  --min-ha 1 `
  --skinny-pixels 3 `
  --python-exe C:\ProgramData\anaconda3\envs\slats\python.exe
```


```
C:\ProgramData\anaconda3\envs\slats\python.exe scripts\eds_master_processing_pipeline.py `
  --tile 094_076 `
  --start-date 20230724 `
  --end-date 20240831 `
  --sr-dir-start D:\data\lsat\094_076\2023\202307\ga_ls9c_ard_094076_20230724_srb7.tif `
  --sr-dir-end   D:\data\lsat\094_076\2024\202408\ga_ls8c_ard_094076_20240831_srb7.tif `
  --sr-root D:\data\lsat `
  --fc-root D:\data\lsat `
  --out-root data\compat\files `
  --season-window 0701 1031 `
  --span-years 2 `
  --fc-only-clr `
  --fc-convert-to-fpc ` # converting green band to fpc
  --fc-k 0.000435 `
  --fc-n 1.909 `
  --ratio-presence 0.95 0.90 `
  --min-ha 1 `
  --skinny-pixels 3 `
  --python-exe C:\ProgramData\anaconda3\envs\slats\python.exe
  ```

### Notes & troubleshooting
- If GDAL imports fail in subprocesses, always pass `--python-exe` with your GDAL‑enabled Conda env.
- If exact end date SR doesn’t exist, the pipeline chooses the nearest composite and prints the effective end date.
- If DLL only contains classes [3,10], polygonization of thresholds 34..39 will produce no shapefiles (expected).
- Rebuild compat with `--force-compat` if underlying SR/FC inputs were updated.
- FC coverage: presence masks and union footprints are re‑used on subsequent runs.

---

## Environment & prerequisites
- Windows PowerShell, Python 3.x, Conda environment recommended (e.g., `slats`).
- Packages: GDAL/OGR, NumPy, SQLAlchemy, python‑dotenv (for the data pipeline’s DB check).
- Access/credentials for GA/DEA where required; optional S3 mirror access.

## Quick start
1) Run the data pipeline to hydrate SR/FC/FMASK and create clear masks. Use `--dry-run` first.
2) Run the processing pipeline on the hydrated data to produce DLL/DLJ and polygons.

If you’d like, we can add a minimal Makefile/Tasks JSON to wire these as repeatable tasks in VS Code.

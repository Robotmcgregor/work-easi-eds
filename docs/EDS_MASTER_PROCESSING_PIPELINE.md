# EDS Master Processing Pipeline

Script: `scripts/eds_master_processing_pipeline.py`

This pipeline orchestrates the SLATS‑style EDS workflow end‑to‑end using already downloaded inputs. It builds compatibility layers, runs the legacy seasonal change method, styles rasters, polygonizes results, post‑processes vectors, and optionally clips outputs by FC presence masks.

- Works best on Windows with a GDAL‑enabled Conda environment.
- See also: `docs/EDS_MASTER_PIPELINES.md` for a combined overview of data + processing pipelines.

---

## What it does
1. Build compat products (db8 reflectance stacks and dc4 FPC timeseries) or reuse existing
2. Run legacy seasonal change method (DLL change classes and DLJ interpretation)
3. Style DLL/DLJ rasters
4. Polygonize DLL into merged threshold shapefiles (classes ≥ 34)
5. Post‑process vectors (dissolve + skinny filter)
6. Build FC coverage products (union + presence ratio masks)
7. Optionally clip cleaned vectors by FC coverage masks

## Scripts called
- [scripts/slats_compat_builder.md](scripts/slats_compat_builder.md) — builds db8/dc4 (+ footprint) using GA SR and FC (optionally converts FC→FPC)
- [scripts/eds_legacy_method_window.py](scripts/eds_legacy_method_window.md) — computes change classes (DLL) and interpretation (DLJ)
- [scripts/style_dll_dlj.py](scripts/style_dll_dlj.md) — sets colors/bands on DLL/DLJ
- [scripts/polygonize_merged_thresholds.py](scripts/polygonize_merged_thresholds.md) — makes polygons for thresholds 34..39
- [scripts/vector_postprocess.py](scripts/vector_postprocess.md) — dissolve and skinny‑pixel filtering
- [scripts/fc_coverage_extent.py](scripts/fc_coverage_extent.md) — presence masks over dc4 image stack
- [scripts/clip_vectors.py](scripts/clip_vectors.md) — clips vectors by strict/ratio FC masks

## Inputs
Required:
- `--tile PPP_RRR` e.g. `094_076`
- `--start-date YYYYMMDD` and `--end-date YYYYMMDD`
- `--sr-dir-start` and `--sr-dir-end`: folder or composite file path for SR start/end

Optional:
- `--sr-root`, `--fc-root`: roots to help discover inputs or resolve nearest dates
- `--out-root` (default `data/compat/files`)
- `--season-window MMDD_START MMDD_END` e.g. `0701 1031`
- `--span-years` (lookback for baseline, default 2; cap 10)
- `--fc-only-clr` (prefer just `*_fc3ms_clr.tif`)
- FC→FPC options (forwarded to compat builder):
  - `--fc-convert-to-fpc` (apply FPC = 100*(1 - exp(-k*FC^n)) during dc4 build)
  - `--fc-k` and `--fc-n` (defaults `0.000435` and `1.909`)
  - `--fc-nodata` (override FC nodata; defaults to band nodata if set)
- `--thresholds` (defaults `34 35 36 37 38 39`)
- `--min-ha` (polygon area filter, default 1)
- `--skinny-pixels` (vector post‑process)
- `--ratio-presence` (one or more presence thresholds, e.g. `0.95 0.90`)
- `--python-exe` (force GDAL‑enabled Python for subprocesses)
- `--force-compat` (rebuild db8/dc4 even if present)
- `--dry-run` (print commands only)

## Outputs
Under `--out-root/<scene>` (e.g. `data/compat/files/p094r076`) you’ll find:
- `lztmre_<scene>_<YYYYMMDD>_db8mz.img`: SR stacks (start, end)
- `lztmre_<scene>_<YYYYMMDD>_dc4mz.img`: FPC images across the timeseries
  - By default this is the FC green input; if `--fc-convert-to-fpc` is set, values are converted via FPC = 100*(1 - exp(-k*FC^n)).
- `lztmna_<scene>_eall_dw1mz.img`: footprint mask
- `lztmre_<scene>_d<start><end>_dllmz.img`: change classes (10=no‑clearing, 3=flag, 34..39=clearing)
- `lztmre_<scene>_d<start><end>_dljmz.img`: interpretation stack
- `shp_d<start>_<end>_merged_min<ha>`: merged polygons per threshold (34..39)
- `shp_d<start>_<end>_merged_min<ha>_clean`: dissolved + skinny‑filtered
- `fc_coverage/`: union and presence masks, plus optional `..._clean_clip_*` outputs

## Usage (PowerShell)
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
  --fc-convert-to-fpc `
  --fc-k 0.000435 `
  --fc-n 1.909 `
  --ratio-presence 0.95 0.90 `
  --min-ha 1 `
  --skinny-pixels 3 `
  --python-exe C:\ProgramData\anaconda3\envs\slats\python.exe
```

## Tips & troubleshooting
- If subprocesses fail to import `osgeo`, pass `--python-exe` with your GDAL‑enabled Conda env.
- If the exact end SR date is missing, the script resolves to the nearest available composite and uses that as the effective end date.
- If DLL has only classes [3,10], polygonization for thresholds 34–39 will produce no shapefiles (expected behavior).
- Use `--force-compat` to rebuild compat products when SR/FC inputs change.
- If you enable `--fc-convert-to-fpc`, dc4 is written as uint8 FPC in [0,100], with nodata preserved as 0 for downstream normalization.
- FC coverage outputs are re‑used; only new ratios will trigger new products.

## Versioning & provenance
The script appends step results (last 4000 chars of stdout/stderr) to an in‑memory results structure and prints a JSON summary at the end for simple provenance tracking.

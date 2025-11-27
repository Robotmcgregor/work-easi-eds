# EDS Workflow: Legacy SLATS-style Clearing Detection

This guide documents the end-to-end workflow we used to run the legacy Queensland SLATS clearing detection on a custom scene, export vectors, clean them, and remove edge effects caused by inconsistent FC coverage.

Tested on Windows PowerShell with a conda env containing GDAL/OGR.

## 0. Environment

- Activate your conda env (example shown uses `C:\Users\DCCEEW\mmroot\envs\slats`).
- Run commands from the repo root: `C:\Users\DCCEEW\code\eds`.

## 1. Acquire inputs

Surface Reflectance (SR) composites for start/end dates, and Fractional Cover (FC) seasonal series.

```powershell
# SR composites (DEA fallback)
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/ensure_sr_from_s3_or_ga.py \
    --scene p089r080 --dates 20231024 20240831 --out D:\data\lsat

# FC seasonal timeseries (July–Oct, ~10-year window)
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/download_fc_from_s3.py \
    --tile 089_080 --months 7 8 9 10 --years-back 10 --end-year 2024 --out D:\data\lsat

    
C:\ProgramData\anaconda3\envs\slats\python.exe scripts/eds_master_data_pipeline.py --tile 094_076 --start-date 20230720 --end-date 20240831 --span-years 2 --cloud-cover 50 --search-days 7

```

## 2. Build SLATS-compat layer

Create `db8` (SR) and `dc4` (FC) compatible images. Use masked FC only to avoid unintended unmasked inputs.

```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/slats_compat_builder.py \
    --scene p089r080 \
    --sr-root D:\data\lsat \
    --fc-root D:\data\lsat \
    --out data\compat\files\p089r080 \
    --fc-only-clr
```

## 3. Run the legacy method (seasonal window)

```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/eds_legacy_method_window.py \
    --scene p089r080 --start 20231024 --end 20240831 --window 0701 1031 \
    --compat-dir data\compat\files\p089r080 --omit-fpc-start-threshold
```

Outputs:
- `lztmre_p089r080_d2023102420240831_dllmz.img` (classification)
- `lztmre_p089r080_d2023102420240831_dljmz.img` (interpretation)

## 4. Style rasters (palette, band names)

```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/style_dll_dlj.py data\compat\files\p089r080
```

## 5. Vectorize classifications

Per-class shapefiles (unfiltered):
```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/polygonize_per_class.py \
    --dll data\compat\files\p089r080\lztmre_p089r080_d2023102420240831_dllmz.img \
    --classes 3 34 35 36 37 38 39 \
    --out-dir data\compat\files\p089r080\shp_d20231024_20240831
```

Merged (>= threshold) with min-area filter:
```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/polygonize_merged_thresholds.py \
    --dll data\compat\files\p089r080\lztmre_p089r080_d2023102420240831_dllmz.img \
    --thresholds 34 35 36 37 38 39 \
    --min-ha 1 \
    --out-dir data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha
```

## 6. Post-process vectors (optional but recommended)

Dissolve + remove skinny artifacts (< N-pixel core). Set `--from-raster` to pick up pixel size.
```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/vector_postprocess.py \
    --input-dir data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha \
    --out-dir   data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha_clean \
    --dissolve --skinny-pixels 3 \
    --from-raster data\compat\files\p089r080\lztmre_p089r080_d2023102420240831_dllmz.img
```

## 7. Build FC coverage masks to remove edge effects

Union of inputs and consistent coverage (strict or ratio):
```powershell
# Strict intersection (every FC image overlaps)
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/fc_coverage_extent.py \
    --fc-dir data\compat\files\p089r080 \
    --scene p089r080 \
    --pattern *dc4mz.img \
    --out-dir data\compat\files\p089r080\fc_coverage

# Ratio-based (e.g., 95% and 90% presence across FC stack)
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/fc_coverage_extent.py \
    --fc-dir data\compat\files\p089r080 \
    --scene p089r080 \
    --pattern *dc4mz.img \
    --out-dir data\compat\files\p089r080\fc_coverage \
    --ratios 0.95 0.90 \
    --save-per-input-masks
```

Outputs:
- `fc_coverage/p089r080_fc_inputs_union.shp` (union of FC inputs)
- `fc_coverage/p089r080_fc_consistent.shp` (strict intersection) or
- `fc_coverage/p089r080_fc_consistent_r095.tif/.shp`, `..._r090.tif/.shp` (ratio-based)
- `fc_coverage/masks/*_valid_mask.tif` (optional) per-input valid-data masks aligned to the reference grid

Use the consistent coverage polygon to clip all vector outputs and eliminate edge artifacts.

## 8. Clip cleaned outputs by FC coverage

Strict clip (most conservative) and ratio-based clip (recovers near-edge areas with high FC presence):

```powershell
# Optional: dissolve the ratio mask to speed up clipping
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/vector_postprocess.py \
    --input-file data\compat\files\p089r080\fc_coverage\p089r080_fc_consistent_mask.shp \
    --out-dir    data\compat\files\p089r080\fc_coverage_diss \
    --dissolve

# Strict intersection clip
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/clip_vectors.py \
    --input-dir data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha_clean \
    --clip      data\compat\files\p089r080\fc_coverage\p089r080_fc_consistent.shp \
    --out-dir   data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha_clean_clip_strict

# Ratio-based (e.g., 0.95) clip
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/clip_vectors.py \
    --input-dir data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha_clean \
    --clip      data\compat\files\p089r080\fc_coverage_diss\p089r080_fc_consistent_mask.shp \
    --out-dir   data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha_clean_clip_ratio95
```

Notes:
- Strict keeps only areas common to all FC images (fewest edge effects, most conservative).
- Ratio 0.95 keeps areas present in at least 95% of FC images (slightly larger coverage, still robust).

## 9. Inspect utilities

```powershell
C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/inspect_outputs.py data\compat\files\p089r080

C:\ProgramData\anaconda3\Scripts\conda.exe run -p C:\Users\DCCEEW\mmroot\envs\slats \
  python scripts/inspect_vector.py data\compat\files\p089r080\shp_d20231024_20240831_merged_min1ha_clean
```

## 10. Notes
- If you only want class 39: use thr_39. If you want 37, use thr_37 (includes 37–39). If you want 34, use thr_34 (includes 34–39).
- Min-area filtering is available in both polygonizers; post-processing adds dissolve + skinny-core filtering.
- Clip outputs by `fc_coverage/p089r080_fc_consistent_mask.shp` (or strict `p089r080_fc_consistent.shp`) to remove edge effects.

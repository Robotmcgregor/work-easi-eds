# Troubleshooting & diagnostics

This pipeline includes a few switches and artefacts that make debugging DLL/DLJ runs much easier.

## Useful runtime flags

In `eds_master_pipeline_optimised.py`:

- `--verbose`
  - prints extra information in most steps
- `--diagnostics`
  - enables diagnostic CSV/JSON outputs and a raw combined-index GeoTIFF from the legacy method
- `--dlj-troubleshoot`
  - after DLJ is produced (legacy + final COG), prints per-band stats and band descriptions using rasterio
- `--stop-after-dlj`
  - stops the pipeline immediately after the legacy method outputs are produced

Legacy-method controls (passed through by the pipeline):

- `--legacy-sr-scale <float>`
  - manually override SR scaling before `log1p()` (e.g. `10000` for reflectance×10000 products)
- `--legacy-no-auto-sr-scale`
  - disable auto-detection and force no scaling (`sr_scale_factor=1`)
- `--legacy-baseline-include-nodata`
  - revert to legacy baseline statistics behaviour (includes zeros as data)

### What “auto-scaling” does (default; usually best)

If you do **not** pass any `--legacy-*` flags, the legacy method uses its defaults:

- **SR scale is auto-detected** (source=`auto`).
- **Baseline stats are nodata-aware** (zeros are treated as nodata and ignored).

#### SR auto-scaling (spectral index)

The legacy method computes a spectral index using `log1p()` on start/end SR bands. The coefficients assume SR is in **reflectance-scale magnitudes** (roughly 0..1).

However, many GA0 SR products store reflectance as **reflectance×10000** (0..10000). If you feed those values directly into `log1p()`, the spectral term becomes numerically very different and can dominate the combined index.

Auto-scaling fixes that by estimating a scale factor from the SR stack:

- It looks at the **median of nonzero NIR (band 5)** values.
- If that median is `> ~2`, it assumes the stack is reflectance×10000 and uses `sr_scale_factor = 10000`.
- It then applies scaling as:
  - `ref_start /= sr_scale_factor`
  - `ref_end   /= sr_scale_factor`
  before computing `log1p()`.

Why it improves results:

- Keeps `spectral_index` in the regime the legacy coefficients were designed for.
- Prevents extreme `combined_index` values that can saturate `clearingProb` (and make thresholds behave strangely).
- Makes the 60/80 `clearingProb` thresholds more stable across tiles and dates.

When to use overrides:

- Use `--legacy-sr-scale 10000` only if you *know* the SR encoding and want to force it.
- Use `--legacy-no-auto-sr-scale` mainly for debugging/A-B testing; it often performs worse when SR is reflectance×10000.

#### Baseline nodata handling (NDVI time-series)

By default, baseline mean/std/stderr and regression ignore zeros (treat 0 as nodata). This usually improves runs because masked pixels (cloud/water/outside coverage) don’t artificially drag baseline statistics toward 0.

`--legacy-baseline-include-nodata` forces the older behaviour (zeros counted as data), which can:

- reduce baseline mean
- inflate or distort std/stderr
- change `t_test`/`s_test` and therefore change `combined_index` and `clearingProb`

## Common issues and what to check

### 1) DLJ/DLL all zeros (or almost all nodata)

Check:

- GA1 NDVI inputs exist locally (run folder `ga1_stage/`) and are readable
- GA0 cloud-masked SR stacks exist (`ga0_work/`) and have reasonable non-nodata pixels
- In the legacy method, nodata is treated as:
  - NDVI: `-9999` is masked out; for legacy 0..200 NDVI encoding, 0 is treated as nodata
  - SR: masked pixels are expected to be nodata and handled as 0 internally

If you ran with `--dlj-troubleshoot`, the pipeline prints band stats that usually reveal whether the raster is genuinely empty vs just low-signal.

### 2) Too much clearing / too little clearing

Enable `--diagnostics` and inspect:

- `diagnostics/*combined_raw*.tif` (float32 raw combined index)
- diagnostics CSV/JSON summaries (percentiles, class counts)

Often issues come down to:

- SR scaling mismatch (reflectance vs reflectance×10000)
- baseline stats being dominated by nodata zeros (consider leaving `--legacy-baseline-include-nodata` off)
- insufficient baseline observations (too few good NDVI dates in window)

### 3) EPSG / grid alignment mismatch

The method crops inputs to the minimal common intersection of array shapes, but if you see weird spatial shifts you should verify:

- GA1 NDVI and GA0 SR are produced in the same target EPSG for a run
- The staging step is pulling GA1 scenes matching the plan’s `target_epsg`

## Where to find diagnostics outputs

- Run folder: `<work-dir>/<tile>/<run-tag>/diagnostics/`
- Legacy method also writes a small JSON log next to DLL/DLJ in `legacy_outputs/`:
  - `*_dll_log_*.json`

## Quick “what band is clearingProb?” reminder

- DLJ band 4 is `clearingProb`.
- Downstream masks/vectors threshold on that band.

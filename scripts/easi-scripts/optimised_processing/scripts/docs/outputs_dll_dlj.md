# DLL & DLJ outputs — production, naming, and derivation

This document focuses on the two core rasters produced by the legacy seasonal-window method:

- **DLL**: 1‑band classification (change “class”)
- **DLJ**: 4‑band interpretation (stretched indices + clearing probability)

These are created by `methods/legacy_window_ndvi_envi.py` and orchestrated by the pipeline step in `eds_master_pipeline_optimised.py`.

## Where DLL/DLJ are produced in the pipeline

- Step 6 runs the legacy method as a subprocess:
  - Wrapper: `tasks/task05_run_legacy_method.py`
  - Implementation: `methods/legacy_window_ndvi_envi.py`
- Step 7 makes sure they are COG GeoTIFFs and uploads them:
  - `tasks/task06_convert_and_upload_outputs.py`

## File format

### Local legacy outputs

- **GeoTIFF** (`.tif`) written directly by the legacy method via GDAL.
- `dtype`: `uint8`
- `nodata`: `0`

### Final “COG” outputs

- Also GeoTIFF, but rewritten/validated as tiled + compressed + with overviews.
- Stored under the run’s `outputs_cog/` directory and uploaded to S3.

## Naming convention

The legacy method derives platform and EPSG from the **end GA0 filename** (the cloud-masked SR composite you pass as `--end-db8`).

Output names are:

- DLL: `{platform}olre_{tile}_d{start}{end}_dll_e{epsg}.tif`
- DLJ: `{platform}olre_{tile}_d{start}{end}_dlj_e{epsg}.tif`
- Provenance log (JSON): `{platform}olre_{tile}_d{start}{end}_dll_log_e{epsg}.json`

Where:

- `platform` is like `sl8` / `sl9`
- `tile` is like `p115r078`
- `start`/`end` are `YYYYMMDD` (effective dates after SR resolution)
- `epsg` is the output CRS EPSG code (e.g. `32756`)

## Inputs used to derive DLL/DLJ

The legacy method consumes two input families:

### 1) GA1 NDVI time-series (baseline + start + end)

- A set of per-date NDVI rasters staged locally (the pipeline downloads them from S3).
- Each NDVI raster is typically:
  - float32 NDVI in ~[-1, 1]
  - `nodata = -9999`
  - clear-land masked using `oa_fmask == 1`

The method:

- selects a seasonal-window baseline (up to `--lookback` years)
- chooses start and end NDVI scenes close to requested start/end dates
- normalises NDVI to an 8-bit “legacy style” scale before statistics

### 2) GA0 SR composites for start & end

- 6‑band SR stacks (blue/green/red/nir/swir1/swir2)
- the pipeline passes the **cloud-masked** GA0 files (`*_ga0-clr_*.tif`) into the method
- SR nodata is typically `-9999` for masked pixels

The method uses these SR stacks for a weighted **spectral index** comparing start vs end.

#### SR auto-scaling (default behavior; usually best)

The spectral index uses `log1p()` of SR band values with legacy coefficients. Those coefficients assume SR is close to **reflectance-scale** (roughly 0..1).

Because GA0 SR is sometimes stored as **reflectance×10000**, the legacy method includes SR scale handling:

- If you do not pass any legacy SR flags, it **auto-detects** whether SR appears to be reflectance×10000.
- Heuristic: if the median nonzero NIR (band 5) value is `> ~2`, it assumes `sr_scale_factor = 10000`.
- It then applies scaling as `ref_start /= sr_scale_factor` and `ref_end /= sr_scale_factor` before computing `log1p()`.

Why this matters:

- SR scaling has a large effect on `spectral_index`.
- `spectral_index` feeds into `combined_index`.
- `combined_index` feeds into DLJ band 4 (`clearingProb`).

In other words, SR auto-scaling often makes the resulting DLL/DLJ more stable and the `clearingProb` thresholds more meaningful.

## High-level derivation

The method computes:

1) **NDVI normalisation** per image to legacy-style `uint8` (1..255, 0=nodata)
2) **baseline statistics** and per-pixel regression over time (mean/std/stderr/slope/intercept)
3) **spectral index** from start/end SR stacks using a legacy weighted `log1p()` combination of bands 2,3,5,6
4) statistical tests against the NDVI baseline/regression:
   - `s_test`: residual from regression in stderr units
   - `t_test`: deviation from baseline mean in std units
5) a **combined index** that fuses spectral + NDVI change signals
6) **DLL class assignment** by applying legacy threshold rules to the combined index (and associated tests)
7) **DLJ interpretation**: stretch indices into uint8 plus compute a `clearingProb` band

The detailed equations and band meanings are in [DLJ bands](dlj_bands.md).

## DLL: class codes

DLL is a single-band uint8 raster. It starts as “no clearing” everywhere, and then certain conditions promote pixels into higher confidence clearing classes.

Current codes used by the NDVI legacy method:

- `0` — null/unused (defined but not normally emitted)
- `10` — **NO_CLEARING** (default)
- `3` — **NDVI-only** detection (a strong NDVI signal, but not meeting the full clearing threshold rules)
- `34..39` — increasing clearing strength (39 strongest)

The exact threshold rules are implemented in `methods/legacy_window_ndvi_envi.py` and are essentially:

- set `34` when `combined_index` exceeds a base threshold
- set `35..39` when `combined_index` is higher and `s_test` and `spectral_index` are sufficiently negative

## DLJ: interpretation layers

DLJ is a 4-band uint8 raster. The method writes band descriptions:

1. `spectralIndex`
2. `ndviTrend`
3. `combinedIndex`
4. `clearingProb`

Important detail:

- Band 2 is written with the description `ndviTrend`, but in the current implementation it is actually a **stretch of `s_test`** (the regression residual test), not a stretch of the raw `ndvi_trend = norm_end - norm_start` difference.

The practical “takeaway” is:

- DLJ bands 1–3 are **stretched visualisation layers**, not the raw float indices.
- DLJ band 4 (`clearingProb`) is the main quantitative layer used for thresholding.

## Downstream products derived from DLJ

`tasks/task08_masks_and_vectors.py`:

- reads **band 4** (`clearingProb`)
- creates two masks:
  - strong: `>= 60` (default)
  - clear: `>= 80` (default)
- polygonises masks to shapefiles and uploads masks/vectors to S3

## Diagnostics that help explain a run

If you run the pipeline with `--diagnostics`, the legacy method also writes:

- a float32 GeoTIFF of the raw (unstretched) `combined_index`:
  - `.../diagnostics/{platform}olre_{tile}_d{start}{end}_combined_raw_e{epsg}.tif`
- various CSV/JSON summaries (histograms, percentiles, class counts)

These are extremely useful when comparing runs or understanding why a tile produced too much/too little clearing.

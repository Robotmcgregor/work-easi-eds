# eds_legacy_method_window.py

Legacy seasonal-window change detection producing DLL (classes) and DLJ (interpretation) rasters.

- Inputs: db8 start/end reflectance stacks, dc4 FPC time series, seasonal window, lookback years
- Outputs: lztmre_<scene>_d<start><end>_dllmz.img and lztmre_<scene>_d<start><end>_dljmz.img
- Dependencies: GDAL, NumPy; compat-style filenames; pre-masked FC preferred ("*_fc3ms_clr.tif")

## What it does
- Selects a seasonal baseline: up to N years lookback, one FPC per year within the MMDD window and <= start-date; falls back to all-available within-window if needed.
- Normalizes each baseline FPC: valid>0 mapped to uint8 with mean ~125 and scale ~15, nodata=0.
- Computes time-series stats over the normalized baseline: mean, std, stderr, and a linear trend (slope/intercept) in decimal-year time.
- Picks FPC start/end images nearest to requested dates within the window (exact match if present).
- Computes:
  - fpcDiff (end-start in normalized FPC)
  - sTest = (observedEnd - predictedEnd) / stderr
  - tTest = (observedEnd - mean) / std
  - spectralIndex from start/end reflectance using log1p and fixed weights
  - combinedIndex = w0*spectral + w1*fpcDiff + w2*tTest + w3*sTest (legacy weights)
- Assigns change classes:
  - 10 = no clearing (default)
  - 3 = FPC-only change when (tTest > -1.70) AND (fpcDiff*stderr_neg > 740)
  - 34..39 = increasing clearing severity based on combinedIndex thresholds with sTest/spectral gates
- Optional rule (enabled by default): if raw FPC start < 108, force class 10 (no clearing)
- Writes DLJ interpretation as 4 bands: spectralIndex, sTest, combinedIndex, clearingProb (stretched to uint8)

## Key formulas
- Normalization: norm = clip(125 + 15*(fpc - mean)/std, 1..255); nodata=0
- Decimal year t = year + doy/daysInYear
- sTest: (F_end_obs - (intercept + slope*t_end)) / stderr
- tTest: (F_end_obs - mean) / std
- Combined: c = -11.972499*spectral - 0.40357223*fpcDiff - 5.2609715*tTest - 4.3794265*sTest
- Clearing probability: P = 200*(1 - exp(-(0.01227*c)^3.18975)); clipped to [0..255]

## Inputs and flags
- --scene pXXXrYYY
- --start-date YYYYMMDD
- --end-date YYYYMMDD
- --dc4-glob "path\to\lztmre_<scene>_*_dc4mz.img" (passed by master; autodiscovers otherwise)
- --start-db8 / --end-db8 (optional overrides)
- --window-start MMDD / --window-end MMDD (defaults to the MMDD of start/end dates)
- --lookback N (default 10)
- --omit-fpc-start-threshold (disables fpcStart<108 => class 10 rule)
- --verbose (prints baseline dates and output paths)

## Output naming
- DLL: lztmre_<scene>_d<start><end>_dllmz.img (uint8, 0 nodata; 10 no-clearing; 3 FPC-only; 34..39 clearing)
- DLJ: lztmre_<scene>_d<start><end>_dljmz.img (uint8 x4 bands)

## Edge cases and safeguards
- Requires >=2 baseline images after seasonal filtering; otherwise exits with a clear message.
- Crops all inputs to the minimal common array shape to protect against slight size differences.
- Zeros in reflectance start/end trigger DLL=0 (NULL_CLEARING) for those pixels.
- If no classes 34..39 are present (e.g., only 3 and 10), downstream polygonization for thresholds 34..39 will produce no polygons (expected).

## Example (PowerShell)
```
C:\ProgramData\anaconda3\envs\slats\python.exe scripts\eds_legacy_method_window.py `
  --scene p094r076 `
  --start-date 20230724 `
  --end-date 20240831 `
  --dc4-glob "data\compat\files\p094r076\lztmre_p094r076_*_dc4mz.img" `
  --start-db8 data\compat\files\p094r076\lztmre_p094r076_20230724_db8mz.img `
  --end-db8   data\compat\files\p094r076\lztmre_p094r076_20240831_db8mz.img `
  --lookback 10 `
  --verbose
```

## Interpretation tips
- Class 3 (FPC-only) indicates strong FPC change without spectral confirmation; it won’t appear in merged threshold polygons.
- DLJ band 4 (clearingProb) is heuristic and scaled to 0..200 before clipping to uint8 — use comparatively.
- For consistent seasonal comparison, keep window bounds stable across years (e.g., 01 Jul–31 Oct).

# A/B testing flags (legacy method controls)

The pipeline supports a small set of “A/B knobs” so you can compare behaviour across runs.

Important: use `--run-tag run1`, `--run-tag run2`, etc so outputs don’t overwrite.

## 1) SR scaling (reflectance scaling)

Why this exists:
- Some SR inputs are stored as reflectance × 10000 (integers like 0..10000).
- Other inputs are stored as reflectance 0..1 (floats).
- The legacy method’s spectral index expects consistent scaling.

Pipeline flags:

- `--legacy-sr-scale <float>`
  - Manually forces an SR scale factor.
  - Example: `--legacy-sr-scale 10000`.

- `--legacy-no-auto-sr-scale`
  - Disables SR scale auto-detection inside the legacy method.
  - Useful as a debugging baseline if you want to see the “raw” behaviour.

Default behaviour:
- If you do not set `--legacy-sr-scale`, the legacy method will try to auto-detect an appropriate scale unless `--legacy-no-auto-sr-scale` is set.

## 2) Baseline stats mode (NDVI nodata handling)

Why this exists:
- The seasonal baseline is a time-series of NDVI images.
- NDVI images include nodata (missing pixels) which can be encoded as 0.
- Including nodata as if it were real NDVI can distort the baseline mean/std/slope.

Pipeline flag:

- `--legacy-baseline-include-nodata`
  - Switches back to the legacy baseline behaviour (includes nodata zeros in baseline stats).
  - The default behaviour is the improved mode (ignore nodata zeros when computing baseline stats).

## 3) Recommended “run pairs”

A simple and effective comparison pair:

- Run A (default improved behaviour):
  - no extra flags

- Run B (force a specific SR scale):
  - `--legacy-sr-scale 10000`

If you are investigating an unexpected behaviour, a third run can help:
- Run C (disable SR auto scale):
  - `--legacy-no-auto-sr-scale`

Keep only one change per run when possible.

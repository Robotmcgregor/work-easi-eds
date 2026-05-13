# DLJ bands reference — what each band represents

DLJ is the “interpretation” raster produced by the legacy NDVI seasonal-window method (`methods/legacy_window_ndvi_envi.py`).

It is written as a **4‑band uint8 GeoTIFF** with `nodata = 0` and with per-band descriptions.

## Quick summary

- DLJ is *not* the raw physics/statistics output; it’s mostly a **stretched** (visualisation-friendly) encoding.
- Band 4 (`clearingProb`) is the key band used for thresholding into masks/vectors.

## Shared conventions

### Nodata

- Output nodata is `0`.
- For bands produced by stretching, the stretch function forces pixels equal to `ignoreVal` (0) to remain `0` in output.

### Stretching

For an input metric image $x$ with global (run-wide) mean $\mu$ and std $\sigma$, the legacy stretch maps approximately:

- $x = \mu - k\sigma \to 1$
- $x = \mu + k\sigma \to 255$

with linear interpolation between those bounds and clipping outside.

The implementation uses:

- band 1: $k = 2$
- bands 2 and 3: $k = 10$

and computes $\mu,\sigma$ from finite, nonzero pixels only.

## Band 1 — `spectralIndex`

### What it is

A weighted combination of start/end SR reflectance values using `log1p()`.

It is intended to detect spectral shifts consistent with clearing.

### Inputs

- Start GA0 SR stack (cloud-masked): bands 2,3,5,6
- End GA0 SR stack (cloud-masked): bands 2,3,5,6

### Computation

Let $S_b$ be start reflectance band $b$ and $E_b$ be end reflectance band $b$.

The raw (float32) spectral index is:

$$
\text{spectral\_index} =
 0.77801094\,\log(1+S_2)
+1.7713253\,\log(1+S_3)
+2.0714311\,\log(1+S_5)
+2.5403550\,\log(1+S_6)
-0.2996241\,\log(1+E_2)
-0.5447928\,\log(1+E_3)
-2.2842536\,\log(1+E_5)
-4.0177752\,\log(1+E_6)
$$

Notes:

- The SR stacks may be scaled (e.g. reflectance×10000). The method can auto-detect scaling and divide by a scale factor before `log1p()`.
- Masked pixels become 0 in the processing arrays and remain 0 (nodata) in outputs.

### Stored in DLJ

Band 1 stores **`spectral_index` stretched to uint8** (not the raw float index).

## Band 2 — `ndviTrend` (actually `s_test` stretch)

### Important naming caveat

Although the band description is written as **`ndviTrend`**, the pixel values in band 2 are actually a **stretch of `s_test`**, not a stretch of the raw NDVI delta.

- `ndvi_trend` exists in the code as $\Delta NDVI$ on the **normalised** NDVI scale:
  - $\Delta = \text{normEnd} - \text{normStart}$ (with nodata handled)
- But the DLJ band 2 uses:

- `trend_stretch = stretch(s_test, ...)`

So: treat DLJ band 2 as a **standardised regression residual indicator**.

### What `s_test` means

The method builds a baseline time-series of **normalised NDVI** (8-bit legacy style) and fits a per-pixel linear regression over decimal year.

At the end date, it predicts expected NDVI and compares observed end NDVI:

- predicted: $\hat{y} = intercept + slope \cdot t_{end}$
- observed: $y = normEnd$

Then:

$$
 s\_test = \frac{y - \hat{y}}{stderr}
$$

Only pixels with `base_stderr >= 0.2` and valid start/end NDVI are considered; others are 0.

### Stored in DLJ

Band 2 stores **`s_test` stretched to uint8**.

Interpretation hint:

- large negative values (in raw `s_test`) indicate end NDVI is much lower than the predicted seasonal baseline (potential clearing)

## Band 3 — `combinedIndex`

### What it is

A weighted fusion of:

- `spectral_index`
- NDVI change (raw `ndvi_trend` between normalised start/end)
- `t_test` (deviation from baseline mean in std units)
- `s_test` (regression residual in stderr units)

### Computation

$$
\text{combined\_index} =
-11.972499\,\text{spectral\_index}
-0.40357223\,\Delta NDVI
-5.2609715\,t\_test
-4.3794265\,s\_test
$$

where:

$$
\Delta NDVI = normEnd - normStart
$$

and:

$$
 t\_test = \frac{normEnd - baseMean}{baseStd}
$$

(with validity guards).

### Stored in DLJ

Band 3 stores **`combined_index` stretched to uint8**.

If `--diagnostics` is enabled, the method also writes a float32 GeoTIFF of the raw `combined_index` to the diagnostics folder.

## Band 4 — `clearingProb`

### What it is

A probability-like transformation of the raw `combined_index` designed to map “more clearing-like” combined index values into an interpretable 0..200-ish range.

### Computation

$$
\text{clearingProb} = 200\left(1 - \exp\left(-\left(0.01227\,\text{combined\_index}\right)^{3.18975}\right)\right)
$$

Then:

- rounded to uint8
- forced to 0 where `combined_index <= 0`

### Stored in DLJ

Band 4 stores `clearingProb` as uint8.

This is the band used by `tasks/task08_masks_and_vectors.py`:

- strong mask: `clearingProb >= 60`
- clear mask:  `clearingProb >= 80`

## How DLL relates to DLJ

- DLL is derived from **threshold rules** on the raw indices (`combined_index`, `s_test`, `spectral_index`, plus an NDVI-only diagnostic).
- DLJ provides supporting “layers” and the probability-like band used for downstream thresholding.

So:

- DLL is closer to a *categorical decision*
- DLJ is closer to *continuous evidence / interpretation*

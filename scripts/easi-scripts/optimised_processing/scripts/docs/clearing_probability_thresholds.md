# Clearing probability (`clearingProb`) and thresholds (strong/clear)

This document explains:

- how the **`clearingProb`** band is computed
- how it relates to the clearing decision outputs (DLL/DLJ)
- how the **threshold masks** (`>= 60` strong, `>= 80` clear by default) are produced
- what those thresholds *mean* operationally (and what they do **not** mean)

## Where `clearingProb` is produced

- `clearingProb` is **band 4** of the DLJ raster produced by:
  - `methods/legacy_window_ndvi_envi.py`
- Threshold masks/vectors are produced by:
  - `tasks/task08_masks_and_vectors.py`

In the top-level pipeline (`eds_master_pipeline_optimised.py`):

- Step 6 produces DLJ (including `clearingProb`).
- Step 8 thresholds DLJ band 4 to create masks and shapefiles.

## What `clearingProb` is

`clearingProb` is a **probability-like score** derived from the raw (float32) `combined_index` computed by the legacy method.

Key properties:

- Stored as **uint8** (0..255) with `nodata = 0`.
- In practice the method computes a value in approximately **0..200**, then stores it as uint8.
- It is monotonically increasing with `combined_index` for `combined_index > 0`.
- It is **not** a formally calibrated probability of clearing in the statistical sense; it is a legacy-style nonlinear mapping designed to produce a stable, interpretable “strength” metric.

## How `clearingProb` is derived

### Step 1 — Build raw indices and tests

The legacy NDVI method builds the following key raw float metrics per pixel:

- `spectral_index` — from start/end SR (weighted `log1p` combination)
- `ndvi_trend` — change in normalised NDVI between start and end
- `t_test` — deviation from baseline mean in std units
- `s_test` — deviation from baseline regression in stderr units

Then it combines them into:

$$
\text{combined\_index} =
-11.972499\,\text{spectral\_index}
-0.40357223\,\Delta NDVI
-5.2609715\,t\_test
-4.3794265\,s\_test
$$

### Step 2 — Map `combined_index` into `clearingProb`

The method applies a nonlinear transform:

$$
\text{clearingProb} = 200\left(1 - \exp\left(-\left(0.01227\,\text{combined\_index}\right)^{3.18975}\right)\right)
$$

Then:

- rounds to nearest integer
- casts to `uint8`
- sets `clearingProb = 0` where `combined_index <= 0`

Operationally:

- small positive `combined_index` yields low `clearingProb`
- large `combined_index` asymptotically approaches ~200

This mapping is used because:

- it compresses a wide-ranging `combined_index` into a bounded scale
- it produces a consistent “strength” band that downstream steps can threshold

## Why SR auto-scaling improves threshold behavior

`clearingProb` depends directly on `combined_index`, which depends (in part) on the **spectral index** computed from GA0 SR.

Many SR products are encoded as reflectance×10000. If that encoding is not accounted for, the `log1p()` spectral term can shift a lot, which shifts `combined_index`, which in turn shifts `clearingProb`.

By default (no `--legacy-*` flags), the legacy method **auto-detects SR scaling** and rescales reflectance×10000 inputs back to reflectance-scale before computing the spectral index. In practice this often:

- reduces run-to-run sensitivity caused by SR encoding
- makes the default 60/80 thresholds behave more consistently

## Relationship to DLL and why thresholds are applied to DLJ

- **DLL** is a categorical “decision/class” raster derived from threshold rules on the raw indices/tests.
- **DLJ** is a multi-band “interpretation” raster. Band 4 (`clearingProb`) is the primary continuous score used for:
  - mask rasters
  - polygonization to shapefiles
  - QA/area calculations

The pipeline’s mask/vector step thresholds **DLJ band 4**, not DLL.

## How threshold masks are produced

File: `tasks/task08_masks_and_vectors.py`

1) Read DLJ band 4:

- nominally `clearingProb`

2) Create two boolean masks (default thresholds):

- **strong mask**: `clearingProb >= 60`
- **clear mask**:  `clearingProb >= 80`

3) Convert booleans to uint8 mask rasters:

- 1 = detected
- 0 = background/nodata

4) Convert masks to COG GeoTIFFs and upload to S3.

5) Polygonize mask pixels == 1 and write shapefiles (with optional `--min-area-ha` filtering), then upload shapefile component files to S3.

## What the thresholds mean (and what they don’t)

### Meaning in practice

Think of `clearingProb` thresholds as **confidence/strength cutoffs** for *this particular method configuration*, not as universal probabilities.

- `>= 60` (**strong**) is intended to be a more conservative detection set than “everything above zero”.
- `>= 80` (**clear**) is intended to be an even more confident subset.

The practical effect:

- increasing the threshold reduces detected area (fewer pixels become 1)
- decreasing the threshold increases detected area (more pixels become 1)

### Not a calibrated probability

Even though it is named `clearingProb`, the value:

- is derived from a deterministic transform of a combined index
- has no explicit calibration step against labelled truth in this codebase

So you should interpret it as:

- “clearing-likeness score scaled to 0..200”

rather than:

- “80% probability of clearing”

## How to choose / tune thresholds

The defaults (`60` and `80`) are operational heuristics.

If you need to tune thresholds for a region or program:

1) Run with `--diagnostics` and review:

- class counts
- histograms / percentiles for `combined_index` and NDVI diagnostic metrics

2) Compare masks at several thresholds (e.g. 40, 60, 80, 100) against QA imagery.

3) Adjust `--min-area-ha` if you need to suppress small noisy polygons.

## Common pitfalls

- If DLJ is all zeros/nodata, threshold masks will be empty regardless of the threshold.
- If SR scaling is wrong (reflectance vs reflectance×10000), `combined_index` can shift dramatically, which will shift `clearingProb` and make thresholds behave unexpectedly.
- If baseline NDVI is sparse or dominated by nodata, the `t_test`/`s_test` terms may be unreliable and push `combined_index` high or low in unexpected ways.

## Quick reference

- DLJ band 4: `clearingProb`
- strong mask: `clearingProb >= --strong-threshold` (default 60)
- clear mask:  `clearingProb >= --clear-threshold`  (default 80)

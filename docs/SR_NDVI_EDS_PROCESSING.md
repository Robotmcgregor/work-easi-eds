# SR-NDVI EDS Processing Pipeline Documentation

## Overview

Two new scripts have been created that adapt the legacy EDS seasonal-window workflow to use **Sentinel-2 / Landsat Surface Reflectance (SR) timeseries with NDVI** instead of Fractional Cover (FC) conversion to FPC.

### Key Changes from FC-Based Workflow

| Aspect | FC-Based | SR-NDVI Based |
|--------|----------|---------------|
| **Input Data** | Fractional Cover green band | Surface Reflectance 6 bands (B2–B7) |
| **Vegetation Index** | FPC (direct from FC) | NDVI = (NIR − RED) / (NIR + RED) |
| **Band Usage** | FC green as 1-band dc4 | SR bands: RED=B4, NIR=B5 for NDVI; B2,B3,B5,B6 for spectral index |
| **dc4 Output** | FPC uint8: 0–255 | NDVI uint8: 0–200 (representing [-1, 1] NDVI) |
| **Normalization** | FPC normalized to [1, 255] | NDVI normalized to [1, 255] using same mean/std approach |
| **Threshold Check** | `if fpcStart < 108 → class 10` | `if ndviStart < 108 → class 10` |
| **Output Bands (DLJ)** | [spectral, sTest, combined, clearingProb] | [spectral, ndviTrend, combined, clearingProb] |

---

## New Scripts

### 1. `easi_slats_compat_builder_sr_ndvi.py`

**Purpose**: Build SLATS-compatible compat files (db8 + dc4) from SR timeseries, computing NDVI instead of reading FC.

#### Key Functions

- **`_stack_sr()`**: Stacks SR bands into 8-band db8 image (unchanged from FC version).
- **`_compute_ndvi_from_sr()`** *(NEW)*: 
  - Extracts RED (B4, index 2) and NIR (B5, index 3) from db8 stack.
  - Computes NDVI = (NIR − RED) / (NIR + RED).
  - Scales to [0, 200] uint8: `output = uint8(100 + 100 * NDVI)`.
  - Sets nodata (0) where denominator ≈ 0 or inputs are invalid.
- **`_write_ndvi_dc4()`** *(NEW)*: 
  - Calls `_compute_ndvi_from_sr()` on a db8 file.
  - Writes NDVI as a single-band dc4 ENVI file with georeferencing.
- **`main()`**: 
  - Accepts `--sr-date` and `--sr-dir` (same as FC version).
  - Builds db8 for each SR date.
  - **Instead of reading FC files**, computes NDVI from each db8 and writes dc4.

#### Usage

```bash
python easi_slats_compat_builder_sr_ndvi.py \
    --tile p104r072 \
    --out-root /path/to/compat \
    --sr-dir /path/to/sr/2020/202006 --sr-date 20200611 \
    --sr-dir /path/to/sr/2023/202306 --sr-date 20230611
```

#### Outputs

- `lztmre_<scene>_<date>_db8mz.img` – 8-band SR stack (as before).
- `lztmre_<scene>_<date>_dc4mz.img` – Single-band NDVI image (0–200 uint8).
- `lztmna_<scene>_eall_dw1mz.img` – Footprint mask.

---

### 2. `easi_eds_legacy_method_window_sr_ndvi.py`

**Purpose**: Perform legacy seasonal-window change detection using NDVI timeseries instead of FPC.

#### Key Functions

- **`normalise_ndvi()`** *(ADAPTED)*:
  - Treats 0 as nodata (same as FPC normalization).
  - Centers NDVI around 125 with scale ~= 15 (output range [1, 255]).
  - Accounts for NDVI expected range [0, 200] from dc4.

- **`timeseries_stats()`**: 
  - Computes mean, std, stderr, slope, intercept on normalized NDVI stack.
  - (Unchanged logic; input is NDVI instead of FPC.)

- **`main()`**:
  - Reads start/end db8 (SR reflectance) and NDVI dc4 timeseries.
  - Builds seasonal baseline: selects ≤1 NDVI image per year within window, up to `--lookback` years (default 10).
  - Computes baseline statistics.
  - Calculates:
    - **ndviTrend**: change in NDVI from start to end date.
    - **spectralIndex**: from SR bands 2,3,5,6 (same as FC version).
    - **combinedIndex**: `ndviTrend + 0.5 × spectralIndex`.
    - **clearingProb**: weighted sum of indices.
  - Generates change classes:
    - `10` – No clearing (if `ndviStart < 108` and threshold not omitted).
    - `3` – NDVI-only change.
    - `34–39` – Increasing clearing probability.

#### Usage

```bash
python easi_eds_legacy_method_window_sr_ndvi.py \
    --scene p104r072 \
    --start-date 20200611 \
    --end-date 20240831 \
    --dc4-glob "/path/to/compat/p104r072/lztmre_p104r072_*_dc4mz.img" \
    --start-db8 /path/to/compat/p104r072/lztmre_p104r072_20200611_db8mz.img \
    --end-db8 /path/to/compat/p104r072/lztmre_p104r072_20240831_db8mz.img \
    --window-start 0701 --window-end 1031 \
    --lookback 10 \
    --verbose
```

#### Outputs

- `lztmre_<scene>_d<start><end>_dllmz.img` – Change class map (uint8).
- `lztmre_<scene>_d<start><end>_dljmz.img` – Interpretation (4 bands: spectral, ndviTrend, combined, clearingProb).

---

## Integration with Master Pipeline

To use the SR-NDVI workflow in the master processing pipeline (`easi_eds_master_processing_pipeline.py`), update the orchestration to:

1. **Run the compat builder** with SR inputs only:
   ```bash
   python easi_slats_compat_builder_sr_ndvi.py \
       --tile <tile> \
       --out-root <out-root> \
       --sr-dir <start-sr-dir> --sr-date <start-date> \
       --sr-dir <end-sr-dir> --sr-date <end-date>
   ```

2. **Run the window method** using the generated dc4 NDVI files:
   ```bash
   python easi_eds_legacy_method_window_sr_ndvi.py \
       --scene <scene> \
       --start-date <start-date> \
       --end-date <end-date> \
       --dc4-glob "<compat-path>/<scene>/lztmre_*_dc4mz.img" \
       --start-db8 <compat-path>/<scene>/lztmre_<scene>_<start-date>_db8mz.img \
       --end-db8 <compat-path>/<scene>/lztmre_<scene>_<end-date>_db8mz.img \
       --window-start <ws> --window-end <we> \
       --lookback <lookback>
   ```

3. Continue with styling, polygonization, and post-processing as before (these scripts are unchanged).

---

## NDVI Calculation Details

### Formula
```
NDVI = (NIR − RED) / (NIR + RED)
where:
  RED  = SR Band 4 (B4) — index 2 in db8 stack
  NIR  = SR Band 5 (B5) — index 3 in db8 stack
```

### Scaling to uint8
```
dc4 value = uint8(100 + 100 × NDVI)
Range: 0 = no data, 100 = NDVI = 0, 200 = NDVI ≈ 1
```

### Handling Nodata
- Pixels where RED + NIR ≈ 0 are set to 0 (nodata).
- Pixels where either RED or NIR is marked as nodata are set to 0.

---

## Key Methodological Notes

1. **Normalization**:
   - Both FPC and NDVI use the same normalization logic: `normalized = 125 + 15 × (value − mean) / std`.
   - This centers typical values around 125 and spreads them over roughly ±15 units.

2. **Threshold Check**:
   - Original rule: `if fpcStart < 108 → class 10 (no clearing)`.
   - Adapted rule: `if ndviStart < 108 → class 10 (no clearing)`.
   - This can be disabled with `--omit-ndvi-start-threshold`.

3. **Baseline Selection**:
   - Selects up to one NDVI image per year within the seasonal window (MMDD range).
   - Looks back up to `--lookback` years (default 10).
   - Falls back to all available images within the window if not enough per-year picks.

4. **Spectral Index**:
   - Unchanged from FC version: uses SR bands 2, 3, 5, 6.
   - Weighted log-ratio combination.
   - Combined with NDVI trend to form the final clearing probability index.

---

## Files Affected

### New Files
- `easi_slats_compat_builder_sr_ndvi.py`
- `easi_eds_legacy_method_window_sr_ndvi.py`

### Existing Files (No Changes Needed)
- `easi_slats_compat_builder_fc.py` (FC-based builder — retained for backward compatibility)
- `easi_eds_legacy_method_window_fc.py` (FC-based window method — retained for backward compatibility)
- `easi_eds_master_processing_pipeline.py` (Can be extended to support `--sr-mode=ndvi`)

---

## Testing & Validation

### Quick Syntax Check
```bash
python -m py_compile easi_slats_compat_builder_sr_ndvi.py easi_eds_legacy_method_window_sr_ndvi.py
```

### Functional Testing
1. Run the compat builder on a test tile with a few SR dates.
2. Verify db8 stacks are created with 8 bands.
3. Verify dc4 images contain NDVI values in [0, 200] range.
4. Run the window method and verify DLL/DLJ outputs are produced.

---

## Future Enhancements

1. **Support for other vegetation indices**: Easily swap NDVI for GNDVI, EVI, etc. by changing band combinations in `_compute_ndvi_from_sr()`.
2. **Adaptive weighting**: Make spectral index weight in combined index configurable.
3. **Multi-index fusion**: Combine NDVI with other indices (e.g., moisture index from B5, B6).
4. **Per-pixel error bars**: Use stderr from baseline statistics to compute confidence intervals on change maps.

---

## References

- NDVI formula: Rouse et al. (1974), *Monitoring vegetation systems in the Great Plains with ERTS*
- Seasonal window approach: Legacy SLATS methodology
- SR bands: USGS Landsat 8 and Sentinel-2 band definitions

# SR-NDVI EDS Pipeline: Quick Reference

## Files Created

### 1. Compat Builder (SR-NDVI)
**File**: `easi_slats_compat_builder_sr_ndvi.py`

**What it does**:
- Reads SR multi-band composites (8 bands: B2–B7)
- Computes NDVI from RED (B4) and NIR (B5)
- Outputs:
  - `db8mz.img` – 8-band SR reflectance (unchanged from FC version)
  - `dc4mz.img` – NDVI single-band (uint8: 0–200, where 100=NDVI 0)

**Key function**: `_compute_ndvi_from_sr(sr_file)`
```
NDVI = (B5 - B4) / (B5 + B4)
Output: uint8(100 + 100 * NDVI)  → range [0, 200]
```

**Usage**:
```bash
python easi_slats_compat_builder_sr_ndvi.py \
    --tile p104r072 \
    --out-root /compat \
    --sr-dir /sr/2020/202006 --sr-date 20200611 \
    --sr-dir /sr/2024/202408 --sr-date 20240831
```

---

### 2. Window Method (SR-NDVI)
**File**: `easi_eds_legacy_method_window_sr_ndvi.py`

**What it does**:
- Reads NDVI timeseries from dc4 files
- Reads start/end SR reflectance from db8 files
- Selects seasonal baseline (≤1 image per year, up to 10 years back)
- Computes:
  - **NDVI trend**: `(ndvi_end − ndvi_start)` normalized
  - **Spectral index**: from SR bands 2,3,5,6 (log-ratio weighted)
  - **Combined index**: `ndvi_trend + 0.5 × spectral_index`
  - **Clearing probability**: weighted sum of indices
- Outputs:
  - `dllmz.img` – Change class (uint8): 10=no-clear, 3=NDVI-only, 34–39=increasing clearing
  - `dljmz.img` – Interpretation (4 bands): [spectral, ndviTrend, combined, clearingProb]

**Key steps in main()**:
1. Load SR and NDVI data.
2. Crop to common shape.
3. Build seasonal baseline from NDVI timeseries.
4. Normalize NDVI (same as FPC: center at 125, scale ±15).
5. Compute change indices.
6. Apply threshold checks (NDVI < 108 → no clearing).
7. Generate and write output rasters.

**Usage**:
```bash
python easi_eds_legacy_method_window_sr_ndvi.py \
    --scene p104r072 \
    --start-date 20200611 \
    --end-date 20240831 \
    --start-db8 /compat/p104r072/lztmre_p104r072_20200611_db8mz.img \
    --end-db8 /compat/p104r072/lztmre_p104r072_20240831_db8mz.img \
    --dc4-glob "/compat/p104r072/lztmre_p104r072_*_dc4mz.img" \
    --window-start 0701 --window-end 1031 \
    --lookback 10 \
    --verbose
```

---

## Workflow Example

### Step 1: Build Compat Files
```bash
python easi_slats_compat_builder_sr_ndvi.py \
    --tile 104_072 \
    --out-root data/compat \
    --sr-dir sr_data/20200611 --sr-date 20200611 \
    --sr-dir sr_data/20240831 --sr-date 20240831
```

**Output**:
- `data/compat/p104r072/lztmre_p104r072_20200611_db8mz.img`
- `data/compat/p104r072/lztmre_p104r072_20200611_dc4mz.img` ← NDVI
- `data/compat/p104r072/lztmre_p104r072_20240831_db8mz.img`
- `data/compat/p104r072/lztmre_p104r072_20240831_dc4mz.img` ← NDVI
- `data/compat/p104r072/lztmna_p104r072_eall_dw1mz.img` ← Footprint

### Step 2: Run Change Detection
```bash
python easi_eds_legacy_method_window_sr_ndvi.py \
    --scene p104r072 \
    --start-date 20200611 \
    --end-date 20240831 \
    --start-db8 data/compat/p104r072/lztmre_p104r072_20200611_db8mz.img \
    --end-db8 data/compat/p104r072/lztmre_p104r072_20240831_db8mz.img \
    --dc4-glob "data/compat/p104r072/lztmre_p104r072_*_dc4mz.img" \
    --window-start 0701 --window-end 1031 \
    --lookback 10
```

**Output**:
- `lztmre_p104r072_d20200611_20240831_dllmz.img` ← Change class
- `lztmre_p104r072_d20200611_20240831_dljmz.img` ← Interpretation (4 bands)

### Step 3: Continue with Styling & Polygonization
(Use existing scripts; no changes needed)

---

## Key Differences: FC vs. SR-NDVI

| Feature | FC Version | SR-NDVI Version |
|---------|-----------|----------------|
| Input | FC single-band green | SR 6 bands (B2–B7) |
| Intermediate index | FPC (read from file) | NDVI (computed) |
| dc4 range | 0–255 (FPC) | 0–200 (NDVI: −1 to +1) |
| Normalization | FPC: 0–255 input | NDVI: 0–200 input |
| Threshold rule | `if fpcStart < 108` | `if ndviStart < 108` |
| Scripts | `*_fc.py` | `*_sr_ndvi.py` |

---

## NDVI Interpretation

| NDVI Range | dc4 Value | Meaning |
|-----------|----------|---------|
| −1.0 | 0 | Water / clouds |
| −0.5 to 0.0 | 50–100 | Bare soil / rocks |
| 0.0 | 100 | Vegetation threshold |
| 0.3–0.5 | 130–150 | Sparse vegetation |
| 0.6–0.8 | 160–180 | Dense vegetation |
| 0.9–1.0 | 190–200 | Very dense vegetation |

---

## Troubleshooting

### "Cannot open SR file" / "Cannot parse date"
- **Cause**: File path invalid or date not in filename.
- **Fix**: Ensure `--sr-dir` points to a valid directory/file and filename contains YYYYMMDD date.

### "Insufficient baseline NDVI images"
- **Cause**: Not enough NDVI data within the seasonal window.
- **Fix**: 
  - Provide more SR dates.
  - Loosen the window (expand `--window-start` and `--window-end`).
  - Reduce `--lookback` if targeting very recent data.

### dc4 values all 0
- **Cause**: NDVI calculation failed (possibly nodata propagation).
- **Fix**: 
  - Check SR input files (valid bands, no widespread masked areas).
  - Verify `_compute_ndvi_from_sr()` is handling nodata correctly.

### Output images are black / all zeros
- **Cause**: Change indices are too small or all set to no-clearing (class 10).
- **Fix**: 
  - Check threshold rule: use `--omit-ndvi-start-threshold` if needed.
  - Review weighting in combined index calculation.

---

## Performance Notes

- **Memory**: Each dc4 file ≈ (height × width × 1 byte). Baseline images stack in memory during stats computation.
- **Speed**: Baseline stats computation is O(n × height × width) where n = number of baseline images.
- **I/O**: GDAL reads entire bands into memory; ensure sufficient RAM for large tiles.

---

## Next Steps

1. **Test** both scripts on a small tile.
2. **Validate** dc4 NDVI values are in expected [0, 200] range.
3. **Compare** DLL/DLJ outputs to FC-based results (if running side-by-side).
4. **Integrate** into master pipeline by adding `--sr-mode=ndvi` flag.
5. **Document** any customizations (e.g., different vegetation index, weighting scheme).

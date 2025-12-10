# Integration Guide: SR-NDVI into Master Pipeline

## Summary of Changes

Two new SR-NDVI-based scripts have been created to complement the existing FC-based EDS processing workflow. These scripts compute **NDVI from Surface Reflectance** instead of reading Fractional Cover data.

### Files Created

| File | Location | Purpose |
|------|----------|---------|
| `easi_slats_compat_builder_sr_ndvi.py` | `scripts/easi-scripts/eds-processing/` | Build db8+dc4 from SR, computing NDVI for dc4 |
| `easi_eds_legacy_method_window_sr_ndvi.py` | `scripts/easi-scripts/eds-processing/` | Run seasonal-window change detection using NDVI |
| `SR_NDVI_EDS_PROCESSING.md` | `docs/` | Detailed technical documentation |
| `SR_NDVI_QUICK_REFERENCE.md` | `docs/` | Quick reference and troubleshooting |

### Complementary (Unchanged)

The following scripts remain the same and can be used after SR-NDVI change detection:
- `easi_style_dll_dlj.py` – Styling the DLL/DLJ outputs
- `easi_polygonize_merged_thresholds.py` – Vectorizing change classes
- `vector_postprocess.py` – Post-processing polygons (dissolve, skinny filter)
- `fc_coverage_extent.py` – FC coverage computation
- `clip_vectors.py` – Clipping with masks

---

## Step-by-Step Integration

### Option A: Direct Script Calls (Manual)

```bash
# Step 1: Build compat files from SR timeseries with NDVI
python scripts/easi-scripts/eds-processing/easi_slats_compat_builder_sr_ndvi.py \
    --tile p104r072 \
    --out-root data/compat \
    --sr-dir sr_data/2020/202006 --sr-date 20200611 \
    --sr-dir sr_data/2024/202408 --sr-date 20240831

# Step 2: Run change detection (seasonal window method)
python scripts/easi-scripts/eds-processing/easi_eds_legacy_method_window_sr_ndvi.py \
    --scene p104r072 \
    --start-date 20200611 \
    --end-date 20240831 \
    --start-db8 data/compat/p104r072/lztmre_p104r072_20200611_db8mz.img \
    --end-db8 data/compat/p104r072/lztmre_p104r072_20240831_db8mz.img \
    --dc4-glob "data/compat/p104r072/lztmre_p104r072_*_dc4mz.img" \
    --window-start 0701 --window-end 1031 \
    --lookback 10 \
    --verbose

# Step 3: Style outputs (unchanged)
python scripts/easi-scripts/eds-processing/easi_style_dll_dlj.py \
    --dll lztmre_p104r072_d20200611_20240831_dllmz.img \
    --dlj lztmre_p104r072_d20200611_20240831_dljmz.img \
    --out-root output/

# Step 4: Polygonize (unchanged)
python scripts/easi-scripts/eds-processing/easi_polygonize_merged_thresholds.py \
    --input output/lztmre_p104r072_d20200611_20240831_styled_dll.tif \
    --output output/polygons_raw.shp \
    --thresholds 34 35 36 37 38 39

# Step 5: Post-process (unchanged)
python scripts/easi-scripts/eds-processing/vector_postprocess.py \
    --input output/polygons_raw.shp \
    --output output/polygons_clean.shp \
    --min-area 1.0 \
    --skinny-pixels 3
```

---

### Option B: Modify Master Pipeline (Recommended)

To integrate into `easi_eds_master_processing_pipeline.py`, add a new `--sr-mode` flag:

**Add to argparse in `main()`:**
```python
ap.add_argument(
    "--sr-mode",
    choices=["fc", "ndvi"],
    default="fc",
    help="Processing mode: fc=use FC inputs, ndvi=compute NDVI from SR"
)
```

**Add conditional workflow:**
```python
if args.sr_mode == "ndvi":
    # Use SR-NDVI scripts
    compat_script = "easi_slats_compat_builder_sr_ndvi.py"
    window_script = "easi_eds_legacy_method_window_sr_ndvi.py"
else:
    # Use FC scripts (existing)
    compat_script = "easi_slats_compat_builder_fc.py"
    window_script = "easi_eds_legacy_method_window_fc.py"

# Run compat builder
compat_cmd = [
    args.python_exe or "python",
    os.path.join(ROOT, "scripts", "easi-scripts", "eds-processing", compat_script),
    "--tile", scene,
    "--out-root", args.out_root,
]

if args.sr_mode == "ndvi":
    # SR dates and directories
    for sr_date, sr_dir in zip(args.sr_date, [args.sr_dir_start, args.sr_dir_end]):
        compat_cmd.extend(["--sr-date", sr_date, "--sr-dir", sr_dir])
else:
    # FC inputs (existing logic)
    for sr_date, sr_dir in zip(args.sr_date, [args.sr_dir_start, args.sr_dir_end]):
        compat_cmd.extend(["--sr-date", sr_date, "--sr-dir", sr_dir])
    # Add --fc, --fc-glob, --fc-only-clr, etc. (existing logic)

run_cmd(compat_cmd, args.dry_run, "Compat (SR-NDVI)" if args.sr_mode == "ndvi" else "Compat (FC)", results)

# Run window method
window_cmd = [
    args.python_exe or "python",
    os.path.join(ROOT, "scripts", "easi-scripts", "eds-processing", window_script),
    "--scene", scene,
    "--start-date", args.start_date,
    "--end-date", args.end_date,
    "--dc4-glob", str(compat_out_dir / f"lztmre_{scene}_*_dc4mz.img"),
    "--start-db8", str(compat_out_dir / f"lztmre_{scene}_{args.start_date}_db8mz.img"),
    "--end-db8", str(compat_out_dir / f"lztmre_{scene}_{args.end_date}_db8mz.img"),
]

if args.window_start:
    window_cmd.extend(["--window-start", args.window_start[0], "--window-end", args.window_start[1]])
if args.lookback:
    window_cmd.extend(["--lookback", str(args.lookback)])

run_cmd(window_cmd, args.dry_run, "Window Method (SR-NDVI)" if args.sr_mode == "ndvi" else "Window Method (FC)", results)

# Continue with styling, polygonization, post-processing (unchanged)
```

**Usage with master pipeline:**
```bash
python scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py \
    --tile 104_072 \
    --start-date 20200611 \
    --end-date 20240831 \
    --sr-mode ndvi \
    --sr-dir-start sr_data/2020/202006 \
    --sr-dir-end sr_data/2024/202408 \
    --out-root data/compat \
    --season-window 0701 1031 \
    --lookback 10 \
    --dry-run  # Remove to actually run
```

---

## Key Comparisons: FC vs. SR-NDVI

### Inputs
- **FC**: Single-band Fractional Cover green (0–100 scale)
- **SR-NDVI**: 6-band Surface Reflectance (B2–B7), NDVI computed from RED (B4) and NIR (B5)

### Intermediate Processing
- **FC**: FPC = 100 × (1 − exp(−k × FC^n)) [empirical formula]
- **SR-NDVI**: NDVI = (NIR − RED) / (NIR + RED) [vegetation index]

### dc4 Output
- **FC**: 0–255 uint8 (raw FPC values)
- **SR-NDVI**: 0–200 uint8 (NDVI: −1 to +1 mapped to 0–200)

### Change Detection
- **FC**: Baseline FPC normalization + FPC trend
- **SR-NDVI**: Baseline NDVI normalization + NDVI trend

### Advantages of SR-NDVI
✓ Direct from SR (no intermediate FC product needed)
✓ NDVI is well-established vegetation index
✓ Can leverage SR timeseries (more images available)
✓ Combines spectral information (bands 2,3,5,6) + NDVI trend
✓ Faster data pipeline if FC products not already available

### Advantages of FC-Based
✓ Includes sub-pixel vegetation breakdown (green, bare soil, non-photosynthetic veg)
✓ More direct representation of canopy structure
✓ Longer historical archive (if available)

---

## Testing Checklist

After implementing SR-NDVI integration:

- [ ] **Syntax check**: `python -m py_compile easi_slats_compat_builder_sr_ndvi.py easi_eds_legacy_method_window_sr_ndvi.py`
- [ ] **Single tile test**: Run both scripts on a test tile with 2–3 SR dates
- [ ] **Verify db8**: Check 8-band stacks are created and contain valid reflectance
- [ ] **Verify dc4**: Check NDVI values are in [0, 200] range
- [ ] **Verify DLL/DLJ**: Check outputs have expected classes and interpretation bands
- [ ] **Compare with FC**: If available, run FC-based workflow on same tile and compare results
- [ ] **Performance**: Monitor memory and runtime on larger tiles
- [ ] **Error handling**: Test with invalid inputs, missing files, etc.

---

## Rollout Strategy

### Phase 1: Validation
1. Run SR-NDVI and FC-based workflows side-by-side on a test tile.
2. Compare outputs (DLL/DLJ) visually and numerically.
3. Validate downstream products (polygons, styling, etc.) match expectations.

### Phase 2: Selective Deployment
1. Switch specific tiles to SR-NDVI if results are satisfactory.
2. Document any differences and performance characteristics.
3. Gather feedback from users/analysts.

### Phase 3: Production
1. Fully integrate `--sr-mode` into master pipeline.
2. Default to FC (backward compatibility).
3. Document recommendation for when to use SR-NDVI vs. FC.

---

## Support & Troubleshooting

### Common Issues

**Issue**: `Cannot open SR file`
- **Cause**: File path invalid
- **Fix**: Ensure `--sr-dir` points to a valid directory and files exist

**Issue**: `dc4 values all 0`
- **Cause**: NDVI computation failed
- **Fix**: Check SR input quality; verify bands are valid

**Issue**: `Insufficient baseline NDVI images`
- **Cause**: Not enough data in window
- **Fix**: Expand window range or reduce lookback

### Getting Help

1. **Check documentation**: See `SR_NDVI_QUICK_REFERENCE.md` for troubleshooting
2. **Review logs**: Run with `--verbose` for detailed debug output
3. **Validate inputs**: Use GDAL tools to inspect intermediate rasters
4. **Compare with FC**: Run FC workflow to ensure master pipeline is functional

---

## References

- **NDVI Formula**: Rouse et al. (1974)
- **EDS Methodology**: Legacy SLATS seasonal-window approach
- **SR Bands**: USGS Landsat 8 / ESA Sentinel-2 specifications
- **Implementation Details**: See `SR_NDVI_EDS_PROCESSING.md`

---

## Contact & Updates

For questions, feedback, or enhancements related to the SR-NDVI workflow, refer to the main project documentation and team.

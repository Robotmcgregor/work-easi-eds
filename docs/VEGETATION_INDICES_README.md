# Vegetation Indices (SR-based) — Quick Reference

This guide lists the vegetation indices supported by the SR seasonal-window scripts and explains what they measure in plain language. All indices are computed from surface reflectance (SR) bands and then normalized and analyzed using the legacy EDS change-detection method.

## Supported indices

- NDVI (Normalized Difference Vegetation Index)
  - Formula: NDVI = (NIR − RED) / (NIR + RED)
  - Measures: Green vegetation vigor; higher means more healthy foliage.
  - Notes: Sensitive to chlorophyll; widely used baseline index.

- EVI (Enhanced Vegetation Index)
  - Formula: EVI = 2.5 × (NIR − RED) / (NIR + 6×RED − 7.5×BLUE + 1)
  - Measures: Vegetation vigor with improved correction for atmospheric effects and soil.
  - Notes: Useful in dense canopies; reduces saturation compared to NDVI.

- SAVI (Soil-Adjusted Vegetation Index)
  - Formula: SAVI = (1 + L) × (NIR − RED) / (NIR + RED + L)
  - Parameter: L (soil brightness correction), typically 0.0–1.0; default 0.5.
  - Guidance:
    - L ≈ 0.0: little/no soil correction (NDVI-like)
    - L ≈ 0.3: moderate soil correction (some exposed soil)
    - L ≈ 0.5: common default
    - L ≈ 1.0: strong soil correction (sparse vegetation, bright soils)

- NDMI (Normalized Difference Moisture Index)
  - Formula: NDMI = (NIR − SWIR1) / (NIR + SWIR1)
  - Measures: Vegetation/canopy moisture; higher means wetter foliage/canopy.
  - Notes: Useful for detecting drying or moisture-related change.

## How the method works (non-technical)

1. Seasonal baseline: We collect one index image per year in your chosen window (e.g., dry season), looking back up to N years, and only up to the requested start date.
2. Normalize: Each image is "standardized" to a familiar 0–255 scale where 125 is typical and 0 means "no data".
3. Trend and tests:
   - sTest: compares the end image to the predicted value from the baseline trend (how unusual is it, in standard-error units).
   - tTest: compares the end image to the baseline average (how different is it, in standard-deviation units).
4. Spectral index: We also analyze start vs end SR bands (2,3,5,6) with a legacy weighted combination that captures spectral change.
5. Combined index: We mix spectral change, index change, tTest, and sTest with legacy coefficients.
6. Outputs:
   - DLL: change class (10 = no clearing, 3 = index-only signal, 34..39 = increasing clearing confidence).
   - DLJ: interpretation bands (spectral, sTest, combined, clearing probability) for visualization.

## Output naming

To make it clear which tile and process were used, outputs include the scene (tile), date range, and the vegetation index:

- DLL: `lztmre_<scene>_d<start><end>_vi-<index>_dllmz.img`
- DLJ: `lztmre_<scene>_d<start><end>_vi-<index>_dljmz.img`

Examples:
- NDVI: `lztmre_p104r072_d2020061120220812_vi-ndvi_dllmz.img`
- SAVI (L=0.3): `lztmre_p104r072_d2020061120220812_vi-savi_dllmz.img` (L value is a processing parameter; the filename records the index type; detailed parameters are logged)

## Choosing an index

- NDVI: general vegetation health; good all-rounder.
- EVI: better in dense canopies; less saturation.
- SAVI: adjust for soil brightness; pick L based on expected soil exposure.
- NDMI: focus on moisture-related change.

## Parameters and flags

- `--veg-index {ndvi,evi,savi,ndmi}`: select the index.
- `--savi-L <float>`: soil brightness term for SAVI (default 0.5). Only used when `--veg-index savi`.
- `--omit-start-threshold`: skip the rule that forces no-clearing where the starting index image < 108.
- `--window-start MMDD`, `--window-end MMDD`: seasonal window.
- `--lookback N`: years to include in the baseline.

## Validation and provenance

- Filenames encode tile and index type; logs record parameters and chosen baseline dates.
- Interpretation layers and probabilities use the same legacy method as the FC workflow for consistency.

## Troubleshooting

- Empty/no-data areas: SR zeros translate to index nodata (0); these are excluded and appear dark.
- Baseline too small: Ensure enough historical images exist in the chosen seasonal window before the start date.
- Saturation or sensitivity: Try EVI for dense vegetation; adjust SAVI’s L for bright soils.

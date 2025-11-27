# fc_coverage_extent.py

Derive FC input coverage: union footprint, strict intersection, and optional presence-ratio masks.

Outputs:
- <scene>_fc_inputs_union.shp — union of all FC footprints
- <scene>_fc_consistent.shp — strict intersection (when no ratios provided)
- <scene>_fc_consistent_r095.tif/.shp — presence>=95% mask (for --ratios)
- masks/ — optional per-input valid masks aligned to a reference grid

Key options:
- --fc-dir, --scene, --pattern (default *_dc4mz.img)
- --out-dir
- --ratios 0.95 0.90 (preferred) or --min-presence-ratio 0.9 (deprecated)
- --save-per-input-masks [--per-input-dir]
- --force to overwrite ratio outputs

Notes:
- If CRS is geographic, areas are computed in EPSG:3577 when needed.
- Warps on-the-fly to align inputs when sizes/transforms differ.

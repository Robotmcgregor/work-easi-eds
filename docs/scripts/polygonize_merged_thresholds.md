# polygonize_merged_thresholds.py

Polygonize DLL into merged-threshold shapefiles with a minimum area filter.

- Threshold semantics: "≥ t" where t ∈ {34..39}
  - t=34 keeps classes {34,35,36,37,38,39}
  - t=39 keeps class {39} only
- Outputs: one shapefile per threshold with attributes: thr, area_m2, area_ha

Key options:
- --dll <classification raster>
- --thresholds 34 35 36 37 38 39 (defaults)
- --min-ha <min area in hectares> (default 1.0)
- --out-dir <output directory>

Notes:
- If DLL contains only classes {3,10}, thresholds 34..39 will produce no output (expected).
- If CRS is geographic, areas are computed in EPSG:3577.

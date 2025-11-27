# Create and Import WRS-2 Tile Bounding Boxes

This guide shows how to generate per-tile bounding boxes for Landsat WRS-2 tiles and import them into the app database.

The workflow is two steps:

1) Build a CSV (and optional SQLite) of per-tile bounding boxes from a WRS-2 GeoJSON
2) Import those bboxes into the `landsat_tiles` table (`bounds_geojson`, plus optional center lat/lon)

## Prerequisites

- Python 3.12
- A WRS-2 GeoJSON file with per-tile polygons and properties for path/row.
  - Expected property names include any of: `PATH`/`ROW`, `WRS_PATH`/`WRS_ROW`, `path`/`row`, or a fallback `PR` string like `089078`.
- Database connection set via `DATABASE_URL` environment variable (e.g. `postgresql://eds_user:eds_password@localhost:5432/eds_database`).

## 1) Generate the per-tile bounding boxes

You can pass either a WRS-2 GeoJSON or a Shapefile directly. Examples:

```powershell
# From the repo root

# Option A: Using a GeoJSON
py scripts/wrs2_tile_bounds.py data/WRS2.geojson --csv data/wrs2_tile_bounds.csv --sqlite data/wrs2.sqlite

# Option B: Using an existing Shapefile directly (no GDAL needed)
py scripts/wrs2_tile_bounds.py assets\aus_lsat.shp --csv data/wrs2_tile_bounds.csv --sqlite data/wrs2.sqlite
```

Outputs:
- `data/wrs2_tile_bounds.csv` with columns: `tile_id,path,row,min_lon,min_lat,max_lon,max_lat`
- `data/wrs2.sqlite` (optional) with table `wrs2_tile_bounds` containing the same columns

Notes:
- The script uses plain JSON parsing (no heavy GIS dependencies).
- It supports `Polygon` and `MultiPolygon` geometries in the GeoJSON.

### Where to get WRS-2 and how to export GeoJSON

You need a WRS-2 vector layer (descending orbit) with per-tile polygons. Common sources:

- USGS EROS resources (search for "USGS WRS-2 shapefile")
- EarthExplorer/EE Help pages sometimes link to WRS-2 shapefiles

If your source is a Shapefile (.shp/.dbf/.shx/.prj), you can either:
1) Pass the .shp directly to `wrs2_tile_bounds.py` (as shown above), or
2) Convert it to GeoJSON first:

- Using QGIS (Windows-friendly):
  1. Open the WRS-2 layer in QGIS
  2. Right click layer → Export → Save Features As…
  3. Format: GeoJSON; File name: `data/WRS2.geojson`; CRS: EPSG:4326 (WGS84)
  4. Ensure properties include path/row (e.g. PATH/ROW)

- Using GDAL/ogr2ogr (if installed):
  ```powershell
  # Example: convert shapefile to GeoJSON with WGS84 CRS
  ogr2ogr -f GeoJSON -t_srs EPSG:4326 data/WRS2.geojson path\to\WRS2.shp
  ```

- Using the lightweight converter script (no GDAL):
  ```powershell
  # Install a small pure-Python dependency once
  py -m pip install pyshp

  # Convert Shapefile to GeoJSON (keeps source CRS; ensure it's WGS84 or reproject via QGIS first)
  py scripts/convert_wrs2_shp_to_geojson.py path\to\WRS2.shp --out data/WRS2.geojson
  ```

Property names expected in the GeoJSON features:
- Any of: `PATH`/`ROW`, `WRS_PATH`/`WRS_ROW`, `path`/`row`, or a `PR` string like `089078`.
  The script tries these variants automatically.

## 2) Import bboxes into the application database

Use the import script to update the `landsat_tiles` table with the bounding boxes (stored in `bounds_geojson`) and optionally update the tile center coordinates from the bbox center.

```powershell
# Ensure DATABASE_URL is set in your environment
# Example: $env:DATABASE_URL = "postgresql://eds_user:eds_password@localhost:5432/eds_database"

# Import bounding boxes from the CSV
py scripts/import_wrs2_bounds_to_db.py --csv data/wrs2_tile_bounds.csv --only-missing --update-center
```

Flags:
- `--only-missing`: Only update rows where `bounds_geojson` is NULL/empty.
- `--update-center`: Also update `center_lat` and `center_lon` using the bbox center.

What it does:
- Looks up each row by `tile_id` (e.g., `089078`) in the `landsat_tiles` table.
- Writes a GeoJSON `Polygon` representing the bbox to `bounds_geojson`.
- Optionally computes `center_lon=(min_lon+max_lon)/2` and `center_lat=(min_lat+max_lat)/2`.

## Verifying the import

- You can query your DB to check updated tiles. For example, in psql:

```sql
SELECT tile_id, SUBSTRING(bounds_geojson, 1, 80) || '…' AS preview
FROM landsat_tiles
WHERE bounds_geojson IS NOT NULL
ORDER BY tile_id
LIMIT 10;
```

- Or run a quick Python snippet to read one tile via the existing DB layer.

## Troubleshooting

- If the import reports many `missing_tile`, your `landsat_tiles` may not be populated yet, or `tile_id` formats may differ. Ensure your tiles exist and the `tile_id` matches the WRS-2 format (e.g., `089078`).
- If your WRS-2 GeoJSON uses different property names for path/row, adjust the file or extend `wrs2_tile_bounds.py` to recognize those fields.
- If you need actual polygons (not just bboxes), you can extend `wrs2_tile_bounds.py` to store full geometry instead of bounding boxes.

## Re-running

You can re-run both scripts at any time. Bbox generation is deterministic. Use `--only-missing` during import to avoid overwriting existing geometries unless you intend to refresh them.

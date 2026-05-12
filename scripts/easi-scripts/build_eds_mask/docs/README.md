# build_eds_mask

Create a raster mask per Landsat tile by rasterizing clearing polygons onto a Landsat GA0 grid.

## What it does

- Recursively scans a folder for Shapefiles (`.shp`).
- Filters features where `IsClearing == "y"` (case-insensitive; configurable).
- Validates that selected geometries are polygonal (Polygon/MultiPolygon). Errors otherwise.
- Groups polygons by Landsat tile id (`p###r###`).
- For each tile, finds a GA0 GeoTIFF for that tile, reads its grid/CRS, and rasterizes polygons into a 1-band Byte GeoTIFF mask.

## Output

One GeoTIFF per tile in `--out-dir`:

- `eds_mask_<tile>_e<epsg>.tif` (NoData=0, burn value=1)

## Usage

Dry-run (default):

```bash
python scripts/easi-scripts/build_eds_mask/scripts/build_eds_mask.py \
  --input-data /path/to/clearing_shapefiles \
  --ga0-root /path/to/ga0_tifs \
  --out-dir /path/to/output_masks \
  --dry-run
```

Apply (writes outputs):

```bash
python scripts/easi-scripts/build_eds_mask/scripts/build_eds_mask.py \
  --input-data /path/to/clearing_shapefiles \
  --ga0-root /path/to/ga0_tifs \
  --out-dir /path/to/output_masks \
  --apply
```

Common options:

- `--tile-field <field>`: if tile id is stored as an attribute (recommended when multiple tiles exist in one file)
- `--clearing-field` / `--clearing-value`: adjust filtering
- `--ga0-pattern`: tighten GA0 discovery if you have multiple matching rasters
- `--all-touched`: rasterize with `ALL_TOUCHED=TRUE`

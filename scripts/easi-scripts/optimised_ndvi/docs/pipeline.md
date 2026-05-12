# Pipeline walkthrough (optimised_ndvi)

Entry point: `scripts/ndvi_master_pipeline.py`.

## High-level flow

1. **Parse CLI args** (tile, S3 destination, local work dir, optional filtering).
2. **Inventory existing outputs** in S3 (best-effort) so resume is faster.
3. **Load/build a scene manifest** (Parquet) for the tile.
4. **For each manifest row (scene)**:
   - Build the S3 output keys (NDVI + ffmask).
   - If not `--rebase`, skip if both keys already exist in S3.
   - Load the scene from datacube, compute NDVI + mask, write COGs locally.
   - Upload both COGs to S3.

## Step details

### 1) Inventory (resume support)
Code: `tasks/task01_inventory_s3.py`.

- Lists keys under a prefix in S3 and returns a list for reporting.
- Resume/skip behaviour in practice is controlled by the per-scene `head_object` checks (`lib/s3_io.py:s3_key_exists`).

Note: the inventory prefix in `inventory_existing_outputs()` is currently different from the per-scene output key structure produced by the master pipeline. Treat the inventory count as informational; the definitive skip check is `s3_key_exists()` for the exact keys.

### 2) Build/load manifest (Parquet)
Code: `tasks/task02_build_scene_manifest.py`.

- The manifest is cached locally at:
  - `--work-dir/<tile>/manifests/<tile>_manifest.parquet` (the pipeline uses `Path(--work-dir) / <tile>`)
- If `--manifest-uri` is an S3 URI and it exists, it is downloaded and used.
- Otherwise it is built by querying datacube datasets intersecting the tile bbox.

Filtering rules:

- **Strict** scene-level cloud filter: only scenes with cloud metadata and `cloud <= --cloud-max` are included.
- Optional date window: `--start-date` / `--end-date` are applied after loading/building.

Tile bounds source:

- The tile bbox is read from `--tile-shp` using `lib/tile_grid.py:load_tile_bbox_wgs84()`.
- The shapefile must contain `path`, `row`, `lon_min`, `lon_max`, `lat_min`, `lat_max`.

### 3) Process each scene to NDVI + ffmask
Code: `tasks/task03_process_scene_ndvi.py`.

S3 layout used by the master pipeline:

- `.../tiles/<tile>/<YYYY>/<YYYYMM>/...` (month bucket, not per-day folder)

For each scene:

- Loads `nbart_red`, `nbart_nir`, `oa_fmask` via datacube.
- Picks the **best time slice** (if multiple) by maximising land-clear fraction.
- Defines land-clear as `oa_fmask == 1` and not nodata.
- Computes NDVI and sets nodata to `-9999` outside land-clear.
- Writes two outputs as COGs via `lib/cog.py`:
  - NDVI (`float32`, nodata `-9999`)
  - FFMASK (`uint8`, nodata `0`)
- Uploads both files to S3.

Local cleanup:

- If `--rebase` is **not** set, the per-scene local `.tif` files are deleted after upload.

## CRS / EPSG selection

- `ndvi_master_pipeline.py` resolves an output EPSG per scene.
- If `--target-epsg` is provided (> 0), it forces that EPSG.
- Otherwise, it derives a **WGS84 UTM** EPSG (326xx/327xx) from the tile bbox centre.

Outputs include the EPSG in the filename as `_e{epsg}`.

# CLI usage

Entrypoint: `scripts/ndvi_master_pipeline.py`

## How to run

Basic usage:

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py --help
```

## Minimal run

You must provide:

- `--tile` (e.g. `p089r084`)
- `--s3-bucket`
- `--s3-prefix`
- `--work-dir`

Example (adjust paths for your environment):

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
  --tile p089r084 \
  --s3-bucket <your-bucket> \
  --s3-prefix <your-prefix> \
  --work-dir <local-work-dir> \
  --tile-shp <path-to-tile-grid-shapefile>
```

## Flag reference

### Required

- `--tile`
  - WRS tile id like `p089r084` (the code lowercases it).

- `--s3-bucket`
  - Destination bucket for outputs.

- `--s3-prefix`
  - Prefix under the bucket. NDVI outputs land under `${prefix}/tiles/...`.

- `--work-dir`
  - Base local work directory.
  - The pipeline creates a tile subfolder: `<work-dir>/<tile>/`.

### Geometry / tile bounds

- `--tile-shp`
  - Tile grid shapefile used to derive bbox/geom for `--tile`.
  - Default: `/home/jovyan/assets/eds_lsat_grid_min_max.shp`.
  - Must contain `path`, `row`, `lon_min`, `lon_max`, `lat_min`, `lat_max`.

### Dates (window selection)

- `--start-date` (optional, `YYYY-MM-DD`)
  - If provided, forces the run start date.
  - If omitted, the pipeline auto-resumes from the next available scene date after the last **successful** run for the tile (from the run log).

- `--end-date` (optional, `YYYY-MM-DD`)
  - If provided, forces the run end date.
  - If omitted, the pipeline runs up to the latest available scene date found in the datacube query.

Notes:

- If the effective window would be invalid (end earlier than start), the pipeline raises an error.
- If both dates are omitted and there is nothing new to do, the pipeline exits early as "Up to date".

### Scene list (in-memory)

The NDVI pipeline builds the scene list in-memory each run by querying datacube.

If you need a persistent, auditable manifest parquet, use the EDS pipeline: it writes a per-run manifest parquet and records it in the EDS run log.

### Run log (master parquet)

- `--run-log-uri` (optional)
  - S3 or local path to the master run-log parquet.
  - Default (if omitted): `s3://<bucket>/<prefix>/runs/optimised_ndvi_runs.parquet`.
  - Only `status == "success"` entries are used for auto-resume.

### Datacube query / filtering

- `--products` (optional)
  - Datacube products to query.
  - Default: `ga_ls8c_ard_3 ga_ls9c_ard_3`.

- `--cloud-max` (optional)
  - Max cloud cover percent threshold.
  - Default: `40.0`.

### Output grid

- `--resolution` (optional)
  - Output pixel size in metres.
  - Default: `30.0`.

- `--target-epsg` (optional)
  - Force output EPSG code.
  - Default: `0` (auto-derive a WGS84 UTM EPSG from tile centroid).

### Resume / overwrite behavior

- `--rebase`
  - Overwrite existing outputs in S3.
  - Default behavior is resume: if both scene outputs exist in S3, that scene is skipped.

- `--dry-run`
  - Prints what would be processed (and target S3 keys) but does not process or write.

- `--limit` (optional)
  - Process only the first N manifest rows.
  - Default: `0` (no limit).

### Performance tuning

- `--chunk` (optional)
  - Dask chunk size for `x/y`.
  - Default: `2048`.

## Optional: run EDS after NDVI

If you want to run the downstream EDS processing pipeline immediately after NDVI finishes, use:

- `--run-eds-after`
  - Runs `scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py` after NDVI completes.
  - Uses the NDVI pipeline effective window for `--start-date/--end-date` passed to EDS.
  - If the effective window collapses to a single date (nothing new), EDS is skipped.

- `--eds-script` (optional)
  - Override the EDS entrypoint script path if you need a custom location.

## Expected environment

This pipeline assumes:

- ODC Datacube is installed and configured for the DEA products you are querying.
- AWS credentials are available for S3 read/write.
- GDAL/rasterio dependencies are available (COG writing uses `rasterio`).

If you see Parquet-related errors, they will come from the run log writer (install `pyarrow` in the environment).

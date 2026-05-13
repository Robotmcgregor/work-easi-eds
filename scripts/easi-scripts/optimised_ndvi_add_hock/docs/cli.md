# CLI usage

Entrypoint: `scripts/ndvi_master_pipeline.py`

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

## Common options

- `--start-date YYYY-MM-DD` / `--end-date YYYY-MM-DD`
- `--cloud-max 40` (scene metadata cloud cover threshold)
- `--products ga_ls8c_ard_3 ga_ls9c_ard_3` (defaults are LS8+LS9 ARD)
- `--resolution 30` (output pixel size in metres)
- `--target-epsg 32755` (force output CRS)
- `--manifest-uri s3://.../manifests/<tile>_manifest.parquet` (optional)
- `--limit N` (process only first N manifest rows)
- `--dry-run` (show what would be processed / written)
- `--rebase` (overwrite existing outputs; also prevents local cleanup)
- `--chunk 2048` (dask chunk size for `x`/`y`)

## Expected environment

This pipeline assumes:

- ODC Datacube is installed and configured for the DEA products you are querying.
- AWS credentials are available for S3 read/write.
- GDAL/rasterio dependencies are available (COG writing uses `rasterio`).

If you see Parquet-related errors when building the manifest, install `pyarrow` in the environment (the code fails fast with a helpful message).

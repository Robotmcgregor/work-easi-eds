# Optimised NDVI pipeline docs

This folder documents the **optimised NDVI** pipeline in `scripts/easi-scripts/optimised_ndvi/scripts/`.

## What this pipeline does

- Builds an in-memory **scene list** for a WRS tile and date window.
- For each scene, loads DEA ARD measurements via **ODC Datacube**.
- Computes **NDVI** and a **land-clear mask** (from `oa_fmask`).
- Writes outputs as **COGs** and uploads them to **S3**.

Note: the authoritative per-run manifest parquet is written by the EDS pipeline.

## Where to start

- `pipeline.md` – step-by-step explanation of how the code flows.
- `cli.md` – how to run the entrypoint + full flag reference.
- `outputs.md` – all outputs and the exact paths/patterns the code writes.

## How to run (quickstart)

Entrypoint:

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
	--tile p089r084 \
	--s3-bucket <bucket> \
	--s3-prefix <prefix> \
	--work-dir <local-work-dir> \
	--tile-shp <path-to-tile-grid-shapefile>
```

Notes:

- The pipeline creates a per-tile working folder under `--work-dir` (e.g. `<work-dir>/p089r084/`).
- Outputs are written to S3 under `${prefix}/tiles/${tile}/${YYYY}/${YYYYMM}/...` (month bucket).

### Common run patterns

1) First-ever run (or explicit backfill window):

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
	--tile p089r084 \
	--s3-bucket <bucket> \
	--s3-prefix <prefix> \
	--work-dir <local-work-dir> \
	--tile-shp <tile-shp> \
	--start-date 2013-01-01 \
	--end-date 2014-12-31
```

2) Scheduled/incremental run (recommended): omit dates

- Uses the run log to resume from the next available date after the last successful run.
- Runs up to the latest available scene found in the datacube query.

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
	--tile p089r084 \
	--s3-bucket <bucket> \
	--s3-prefix <prefix> \
	--work-dir <local-work-dir> \
	--tile-shp <tile-shp>
```

3) Dry-run (show what would run, no processing/writes):

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
	--tile p089r084 \
	--s3-bucket <bucket> \
	--s3-prefix <prefix> \
	--work-dir <local-work-dir> \
	--tile-shp <tile-shp> \
	--dry-run \
	--limit 5
```

4) Reprocess everything in a window (overwrite existing outputs):

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
	--tile p089r084 \
	--s3-bucket <bucket> \
	--s3-prefix <prefix> \
	--work-dir <local-work-dir> \
	--tile-shp <tile-shp> \
	--start-date 2022-01-01 \
	--end-date 2022-12-31 \
	--rebase
```

5) Run EDS after NDVI completes (optional chaining):

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
	--tile p089r084 \
	--s3-bucket <bucket> \
	--s3-prefix <prefix> \
	--work-dir <local-work-dir> \
	--tile-shp <tile-shp> \
	--run-eds-after
```

What this does:

- Runs the NDVI pipeline normally (writes GA1 NDVI + GA2 FFMASK COGs to S3).
- Then invokes the optimised EDS entrypoint script for the same tile and the *effective* date window used by this NDVI run.
- The EDS pipeline records the run (run log parquet + per-run manifest parquet). See the EDS docs: [`optimised_processing/scripts/docs/README.md`](../../optimised_processing/scripts/docs/README.md)

What gets forwarded into EDS when using `--run-eds-after`:

- `--tile`, `--start-date`, `--end-date` (effective window), `--s3-bucket`, `--s3-prefix`, `--work-dir`, `--tile-shp`
- Processing parameters: `--cloud-max`, `--ndvi-products` (from this pipeline's `--products`), `--target-epsg`, `--resolution`, `--chunk`
- If set on NDVI, also forwards: `--rebase`, `--dry-run`
- If set on NDVI, also forwards: `--lookback`, `--verbose`, `--copy-to-home`

Notes:

- You can override which EDS script gets called using `--eds-script <path>`.
- Chaining is a convenience: EDS will still ensure all required baseline NDVI scenes exist in S3 for its seasonal plan (and will compute any missing GA1/GA2 scenes itself).

# work-easi-eds

This repository is the working codebase for **EDS (Early Detection System) development**.

EDS is a data-processing + review workflow focused on detecting and validating land-cover/clearing signals from satellite imagery. In practice, this repo contains:

- Pipeline code that computes products like NDVI and masks, writes cloud-optimized outputs, and records run manifests/logs.
- Scripts and utilities used during development (local runs, debugging, inspection, and dashboards).
- Documentation in `docs/` describing the EDS workflow and dashboards.

## Where the EDS development code lives

- `src/`
  - Core Python modules (database models, settings, shared utilities).
- `scripts/`
  - Developer-facing scripts.
  - `scripts/desktop/` includes local/desktop utilities.
- `scripts/easi-scripts/`
  - The EASI-oriented processing pipelines (including the optimised NDVI pipeline).
  - Start here if you are running the tile-based pipelines.

## EASI scripts entrypoint directory

See: `scripts/easi-scripts/`

It contains multiple pipelines, including:

- `scripts/easi-scripts/optimised_ndvi/` (NDVI + land-clear mask pipeline)
- `scripts/easi-scripts/optimised_processing/` (optimised EDS processing pipeline)

## The two main pipeline buckets

Most day-to-day EDS pipeline work in this repo falls into two buckets under `scripts/easi-scripts/`:

### 1) Optimised NDVI

Location:

- `scripts/easi-scripts/optimised_ndvi/`

What it does:

- Builds a scene list for a WRS tile and date window (from ODC Datacube).
- Computes per-scene NDVI and a land-clear/cloud mask (from `oa_fmask`).
- Writes outputs as Cloud Optimised GeoTIFFs (COGs) and uploads them to S3.
- Maintains a run log for resume/incremental processing.

Docs:

- `scripts/easi-scripts/optimised_ndvi/docs/README.md`

### 2) Optimised processing (EDS)

Location:

- `scripts/easi-scripts/optimised_processing/`
- Docs: `scripts/easi-scripts/optimised_processing/scripts/docs/`

What it does:

- Runs the EDS seasonal-window change detection using an NDVI time-series baseline plus start/end SR composites.
- Ensures required NDVI scenes exist in S3 for the seasonal baseline plan (computes any missing scenes).
- Produces the core EDS rasters:
  - DLL (classification) and DLJ (interpretation incl. clearing probability)
- Derives threshold masks and polygons/vectors used by QA tooling.
- Records each run (run log parquet + per-run manifest parquet).

Docs:

- `scripts/easi-scripts/optimised_processing/scripts/docs/README.md`

### Running both: `--run-eds-after`

If you want a single command that runs both pipelines, run the **optimised NDVI** entrypoint with `--run-eds-after`.

Behavior:

- NDVI runs first (writes GA1 NDVI + GA2 FFMASK COGs to S3).
- Then EDS is invoked for the same tile using the **effective** start/end dates resolved by the NDVI run.
- EDS still builds its own seasonal baseline plan and ensures all required inputs exist in S3.

## Current status / gaps (development notes)

- All-tiles automation is not set up yet. The intended source-of-truth tile list is the shapefile in `assets/eds-lsat-tiles.shp`.
- Current runs are effectively limited by a data download / staging bottleneck and are typically constrained to running about 3 tiles at a time.
- Additional exclusion masking has not been wired in yet (for example, masking out areas already identified/handled so they do not re-trigger downstream logic).
- Run tracking is currently written to `.parquet` run logs/manifests; longer-term this would likely be better stored in a database for easier querying, concurrency control, and operational visibility.

## How to run: optimised NDVI

Authoritative docs live here:

- `scripts/easi-scripts/optimised_ndvi/docs/README.md`
- `scripts/easi-scripts/optimised_ndvi/docs/cli.md`
- `scripts/easi-scripts/optimised_ndvi/docs/pipeline.md`

### Quickstart

Entrypoint script:

- `scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py`

Example (single command):

```powershell
# If `python` is not found on Windows, use: py -3
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py `
  --tile p089r084 `
  --s3-bucket <bucket> `
  --s3-prefix <prefix> `
  --work-dir <local-work-dir> `
  --tile-shp <path-to-tile-grid-shapefile>
```

Notes:

- The pipeline creates a per-tile working folder under `--work-dir` (for example `<work-dir>/p089r084/`).
- Outputs are written to S3 under `${prefix}/tiles/${tile}/${YYYY}/${YYYYMM}/...`.

### Common patterns

- Backfill a fixed window:

```powershell
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py `
  --tile p089r084 `
  --s3-bucket <bucket> `
  --s3-prefix <prefix> `
  --work-dir <local-work-dir> `
  --tile-shp <tile-shp> `
  --start-date 2013-01-01 `
  --end-date 2014-12-31
```

- Incremental run (recommended): omit dates.

```powershell
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py `
  --tile p089r084 `
  --s3-bucket <bucket> `
  --s3-prefix <prefix> `
  --work-dir <local-work-dir> `
  --tile-shp <tile-shp>
```

- Dry-run:

```powershell
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py `
  --tile p089r084 `
  --s3-bucket <bucket> `
  --s3-prefix <prefix> `
  --work-dir <local-work-dir> `
  --tile-shp <tile-shp> `
  --dry-run `
  --limit 5
```

- Optional chaining: run EDS after NDVI completes:

```powershell
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py `
  --tile p089r084 `
  --s3-bucket <bucket> `
  --s3-prefix <prefix> `
  --work-dir <local-work-dir> `
  --tile-shp <tile-shp> `
  --run-eds-after
```

Chaining details and what gets forwarded into EDS are documented in:

- `scripts/easi-scripts/optimised_ndvi/docs/README.md`
- `scripts/easi-scripts/optimised_processing/scripts/docs/`
- `scripts/easi-scripts/optimised_processing/scripts/docs/README.md`

## Batch/Chunked Orchestration (All Tiles, Batching, Resume)

Both the NDVI and EDS pipelines support robust batch processing over all tiles in a shapefile, with chunking and resume support:

### Run NDVI and EDS for the first 10 tiles, starting from 2026-01-01

```bash
python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
  --run-all-tiles \
  --tile-shp /home/jovyan/assets/eds_lsat_grid_min_max.shp \
  --s3-bucket <bucket> \
  --s3-prefix <prefix> \
  --work-dir <local-work-dir> \
  --max-tiles 10 \
  --start-date 2026-01-01 \
  --run-eds-after
```

- `--max-tiles 10` processes only the first 10 tiles.
- `--start-date 2026-01-01` sets the default window for new tiles.
- `--run-eds-after` will automatically run EDS for each tile after NDVI completes.

### Run EDS only (if running EDS separately)

```bash
python scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py \
  --run-all-tiles \
  --tile-shp /home/jovyan/assets/eds_lsat_grid_min_max.shp \
  --s3-bucket <bucket> \
  --s3-prefix <prefix> \
  --work-dir <local-work-dir> \
  --max-tiles 10 \
  --start-date 2026-01-01
```

- The pipeline will resume incomplete tiles using the CSV log.
- Combine with `--tile-offset` to split work into manageable chunks.
- The persistent CSV log ensures failed tiles can be retried without reprocessing successful ones.

### Notes
- If there is no previous run for a tile, the pipeline uses the earliest available scene (or your `--start-date`) as the window start.
- To force a specific default start date for all tiles, always provide `--start-date`.
- If you want to process a different chunk, use `--tile-offset` and `--max-tiles` together.

See the NDVI and EDS pipeline docs for more details and advanced options.

### Running in the Background with nohup

To run the batch process in the background and capture all output to a log file, use `nohup`:

```bash
nohup python scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
  --run-all-tiles \
  --tile-shp /home/jovyan/assets/eds_lsat_grid_min_max.shp \
  --s3-bucket <bucket> \
  --s3-prefix <prefix> \
  --work-dir <local-work-dir> \
  --max-tiles 10 \
  --start-date 2026-01-01 \
  --run-eds-after > my_batch_run.log 2>&1 &
```

- This will process the first 10 tiles sequentially, running NDVI and then EDS for each tile.
- All output (including errors) will be written to `my_batch_run.log`.
- You can safely disconnect from your session; the process will continue running in the background.
- To check progress, use `tail -f my_batch_run.log`.
- To stop the process, use `kill <pid>` (find the PID with `ps` or `jobs -l`).

**Note:**
- Each tile is processed one after the other (not in parallel).
- The persistent CSV log ensures that failed or incomplete tiles can be retried by rerunning the same command.
- You can adjust `--max-tiles` and `--tile-offset` to process different chunks in separate background jobs if needed.

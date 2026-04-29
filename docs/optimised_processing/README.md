# Optimised processing pipeline (tile run)

This folder documents the *optimised_processing* pipeline scripts under:

- `scripts/easi-scripts/optimised_processing/scripts/`

It is written for non-coders who want to:
- run a tile end-to-end
- understand what each step is doing
- know where outputs land (local + S3)
- do repeatable A/B comparisons using `--run-tag`

## What this pipeline does (high level)

For a single tile and a requested start/end date range, the pipeline:

1. Chooses the “best” start and end Landsat SR scenes (typically low cloud).
2. Builds a seasonal NDVI baseline plan (a set of historical NDVI scenes).
3. Ensures those NDVI scenes exist in S3 (builds any missing ones).
4. Downloads (stages) the NDVI scenes locally.
5. Builds SR composites (GA0) for the chosen start and end dates.
6. Runs the legacy seasonal-window method to produce DLL and DLJ.
7. Converts outputs to Cloud Optimised GeoTIFFs (COGs) and uploads them.
8. Builds strong/clear masks and shapefiles from DLJ.

## Start here

- Quickstart commands: see [quickstart.md](quickstart.md)
- Outputs and naming: see [outputs.md](outputs.md)
- A/B flags (SR scaling + baseline stats): see [ab_testing_flags.md](ab_testing_flags.md)
- Diagnostics (CSV/JSON) and how to compare runs: see [diagnostics.md](diagnostics.md)
- Common problems: see [troubleshooting.md](troubleshooting.md)

## One sentence mental model

This pipeline produces a run-scoped “bundle” of raster and vector outputs for one tile and one date range, so you can safely rerun it with different settings and compare the results.

# Quickstart

This is the minimal “run one tile” flow.

## 1) Run the pipeline

From the repo root:

```bash
python scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py \
  --tile p089r080 \
  --start 2025-06-07 \
  --end   2026-01-09 \
  --run-tag run1
```

Notes:
- `--run-tag` is strongly recommended. Use `run1`, `run2`, etc.
- `--run-id` is an alias for `--run-tag`.

## 2) Run again (A/B comparison)

Example: keep everything the same, but change the run tag.

```bash
python scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py \
  --tile p089r080 \
  --start 2025-06-07 \
  --end   2026-01-09 \
  --run-tag run2
```

Now you can compare:
- S3: `.../tiles/<tile>/outputs/run1/` vs `.../tiles/<tile>/outputs/run2/`
- Local: `<work-dir>/<tile>/run1/` vs `<work-dir>/<tile>/run2/`

## 3) Where do I set the S3 location and local work dir?

Use the CLI flags on the pipeline (run `--help` to see them). The two main concepts are:
- S3 bucket/prefix: where scene products and run outputs are stored
- local work directory: where intermediate processing happens for this run

## 4) Most useful day-to-day outputs

- `*_dll_*.tif` and `*_dlj_*.tif` (the main method outputs)
- `masks/*.tif` (strong/clear masks)
- `vectors/*/*.shp` (polygon shapefiles)

Tip (ArcGIS + S3): if you need a simple local folder to download vectors from, run EDS with `--export-vectors-to-work-dir`. This copies vectors to `<work-dir>/vectors/<tile>/<run-tag>/...`.

See [outputs.md](outputs.md) for details.

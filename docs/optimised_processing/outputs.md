# Outputs and naming

This pipeline writes outputs in two places:

1) Local run folder (for repeatable, debuggable processing)
2) S3 run outputs folder (for sharing/analysis)

## Local outputs

Local outputs live under a run-scoped folder:

- `<work-dir>/<tile>/<run-tag>/...`

Common subfolders:
- `ga1_stage/` – locally staged NDVI files (downloaded from S3)
- `ga0_work/` – temporary files produced while building SR composites
- `legacy_outputs/` – DLL/DLJ (and sometimes intermediate files)
- `outputs_cog/` – final COG GeoTIFFs (the ones uploaded)
- `maskvec_work/` – masks + vectors (shapefiles)
- `diagnostics/` – per-run JSON/CSV diagnostics (if enabled)

## S3 outputs

There are two separate S3 layouts:

### A) Scene-date products (canonical)

These are stored under a tile/year/date layout:

- `{s3_prefix}/tiles/{tile}/{YYYY}/{YYYYMMDD}/...`

Examples:
- `*_ga0_*.tif` and `*_ga0-clr_*.tif` (SR composites)
- `*_ga1-clr_*.tif` (NDVI)

### B) Run outputs (run-scoped)

The final run outputs are stored here:

- `{s3_prefix}/tiles/{tile}/outputs/{run_tag}/...`

This contains:
- `*_dll_*.tif` – main class raster
- `*_dll_*.clr` – optional ArcGIS colormap sidecar for the DLL raster
- `*_dlj_*.tif` – interpretation raster (multiple bands)
- `masks/` – strong/clear mask rasters
- `vectors/` – shapefiles (and a `.gpkg`) created from those masks (also a `.zip` bundle per vector dataset)

Note for ArcGIS Pro + Cloud Storage Connections (S3): ArcGIS may show a red exclamation mark for `.gpkg` sources when browsing directly from S3. This usually indicates ArcGIS can't open SQLite-based formats “in place” over the cloud connection. The common workflow is to download/copy the `.gpkg` locally (or use Import/Copy Features, which copies it into a local geodatabase).

## What are DLL and DLJ?

- **DLL** (“class” raster): integer codes that represent “no clearing / possible clearing / strong clearing”.
- **DLJ** (“interpretation” raster): multiple bands that help explain *why* a pixel was classified.

The pipeline also creates user-friendly derivative products:
- “strong” and “clear” masks from DLJ thresholds
- shapefiles (polygons) from those masks

## What files should I compare between runs?

Start with:
- the final uploaded `*_dll_*.tif` and `*_dlj_*.tif`
- the strong/clear masks and shapefiles

Diagnostics files (CSV/JSON) are described in [diagnostics.md](diagnostics.md).

# Outputs and locations (optimised_ndvi)

This file lists **all outputs that the current pipeline code writes**, and their paths/patterns.

Variables used below:

- `${bucket}` = `--s3-bucket`
- `${prefix}` = `--s3-prefix`
- `${tile}` = `--tile` (lowercased)
- `${work_dir_base}` = `--work-dir` (base directory)
- `${tile_work_dir}` = `${work_dir_base}/${tile}` (the pipeline creates a tile-scoped subfolder)
- `${date}` = scene date in `YYYYMMDD`
- `${year}` = `YYYY` from `${date}`
- `${yyyymm}` = `YYYYMM` from `${date}` (i.e. first 6 chars)
- `${platform}` = `L8` / `L9`
- `${p}` = platform digit (`8` or `9`), i.e. `${p} = ${platform[1:]}`
- `${epsg}` = output EPSG code (forced by `--target-epsg` or derived)

## Local filesystem outputs

### Manifest cache
Written by `tasks/task02_build_scene_manifest.py`:

- `${tile_work_dir}/manifests/${tile}_manifest.parquet`

### Per-scene temporary COGs
Written by `tasks/task03_process_scene_ndvi.py`:

- NDVI (float32, nodata = -9999):
  - `${tile_work_dir}/sl${p}olre_${tile}_${date}_ga1-clr_e${epsg}.tif`
- FFMASK (uint8, nodata = 0; 1=kept clear land, 0=masked):
  - `${tile_work_dir}/sl${p}olre_${tile}_${date}_ga3_e${epsg}.tif`

Cleanup behaviour:

- If `--rebase` is **not** set, these local `.tif` files are deleted after uploading to S3.

## S3 outputs

### Manifest parquet
Default location if `--manifest-uri` is not provided:

- `s3://${bucket}/${prefix}/manifests/${tile}_manifest.parquet`

If `--manifest-uri` is provided:

- The manifest is **read from** that URI if it exists.
- If it does not exist, it is **written to** that URI.

### Per-scene NDVI + FFMASK COGs
Written by `scripts/ndvi_master_pipeline.py` + `tasks/task03_process_scene_ndvi.py`.

Per scene/date:

- Output directory:
  - `s3://${bucket}/${prefix}/tiles/${tile}/${year}/${yyyymm}/`

- NDVI COG:
  - `s3://${bucket}/${prefix}/tiles/${tile}/${year}/${yyyymm}/sl${p}olre_${tile}_${date}_ga1-clr_e${epsg}.tif`

- FFMASK COG:
  - `s3://${bucket}/${prefix}/tiles/${tile}/${year}/${yyyymm}/sl${p}olre_${tile}_${date}_ga3_e${epsg}.tif`

Skip/overwrite behaviour:

- Default is **resume**: if both keys exist in S3, the scene is skipped.
- `--rebase` forces reprocessing/upload.

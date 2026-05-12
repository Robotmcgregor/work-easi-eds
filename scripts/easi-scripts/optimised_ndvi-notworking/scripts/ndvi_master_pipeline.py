#!/usr/bin/env python3
"""
NDVI master pipeline (EASI)

What it does (per tile):
  1) Inventory existing outputs in S3 (so we don’t redo work).
  2) Build / load a “scene manifest” (list of dates + paths to RED/NIR/FFMASK).
  3) For each scene:
       - reproject RED, NIR, and FFMASK to target GDA94 EPSG
       - apply mask
       - compute NDVI
       - write Cloud-Optimised GeoTIFF (COG)
       - upload to S3 using required naming convention:
           lztmre_<scene>_<yyyymmdd>_<datatype>_<epsg>.tif
  4) Update per-tile inventory record (CSV in S3).

Safe for cheap/spot nodes:
  - each scene output is checkpointed to S3
  - retries don’t corrupt anything

  python scripts/ndvi_master_pipeline.py \
  --tile p089r084 \
  --manifest /scratch/manifests/p089r084_manifest.csv \
  --s3-bucket <project-rds-bucket> \
  --s3-prefix optimised/eds \
  --work-dir /scratch/eds-work \
  --cloud-max 40

  python scripts/ndvi_master_pipeline.py \
  --tile p089r084 \
  --manifest /scratch/manifests/p089r084_manifest.csv \
  --s3-bucket <project-rds-bucket> \
  --s3-prefix optimised/eds \
  --work-dir /scratch/eds-work \
  --cloud-max 40 \
  --rebase


"""

from __future__ import annotations

import argparse
from pathlib import Path

from tasks.task01_inventory_s3 import inventory_outputs
from tasks.task02_build_scene_manifest import load_or_build_manifest
from tasks.task03_process_scene_ndvi import process_scene_to_s3
from lib.records import upsert_inventory_row
from lib.s3_io import s3_key_exists


def parse_args():
    ap = argparse.ArgumentParser()

    ap.add_argument("--tile", required=True, help="Tile in scene form, e.g. p089r084")
    ap.add_argument("--cloud-max", type=float, default=40.0, help="Cloud filter threshold (percent)")

    # Manifest input/output
    ap.add_argument("--manifest-uri", required=False, help="Optional path to a manifest .parquet. If omitted, build from a directory scan.")
    ap.add_argument("--source-dir", required=False, help="Directory containing GA/EASI data to scan (if building manifest).")

    # Output location (S3)
    ap.add_argument("--s3-bucket", required=True)
    ap.add_argument("--s3-prefix", default="eds", help="Base prefix, e.g. eds or eds/tiles")

    # Working directory (keep out of home dir)
    # ap.add_argument("--work-dir", default="/scratch/eds-work", help="Local scratch staging dir for warps/COGs")
    ap.add_argument("--work-dir", default="/home/jovyan/scratch/eds-work", help="Local staging dir for warps/COGs")

    # Projection control
    ap.add_argument("--target-epsg", type=int, default=0,
                    help="Override output EPSG (e.g. 3577). If 0, derive GDA94 MGA zone EPSG:283xx from tile centre.")
    ap.add_argument("--resolution", type=float, default=30.0, help="Output pixel size (metres). Default 30m.")

    # Rebuild logic
    ap.add_argument("--rebase", action="store_true",
                    help="If set, overwrite existing outputs in S3 (recompute everything). Otherwise resume (skip existing).")

    # Limits / debug
    ap.add_argument("--limit", type=int, default=0, help="Process only first N scenes (0 = no limit).")
    ap.add_argument("--dry-run", action="store_true", help="Print planned actions but do not run.")

    # force start and end dates
    ap.add_argument("--start-date", default=None, help="Start date YYYYMMDD (optional)")
    ap.add_argument("--end-date", default=None, help="End date YYYYMMDD (optional)")

    ap.add_argument("--tile-shp", default="/home/jovyan/assets/eds_lsat_grid_min_max.shp",
                help="Tile grid shapefile used to derive bbox for a tile.")
    ap.add_argument("--query-script", default="/home/jovyan/work-easi-eds/scripts/easi-scripts/eds_lsat_collection/ls89_fc_sr_query.py",
                    help="Path to ls89_fc_sr_query.py")
    ap.add_argument("--comparison-csv", default=None,
                    help="Optional: existing comparison_table.csv to build manifest from (skip query).")



    return ap.parse_args()


def main():
    args = parse_args()

    # Default manifest location (Parquet) if user didn't provide one
    if not args.manifest_uri:
        args.manifest_uri = (
            f"s3://{args.s3_bucket}/"
            f"{args.s3_prefix.rstrip('/')}/manifests/{args.tile.lower()}_manifest.parquet"
        )
        print(f"[INFO] No --manifest-uri supplied. Using default: {args.manifest_uri}")


    tile = args.tile.lower()
    work_dir = Path(args.work_dir) / tile
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1) Inventory S3 outputs (useful for reporting + skipping)
    inv = inventory_outputs(bucket=args.s3_bucket, prefix=args.s3_prefix, tile=tile)
    print(f"[INFO] Found {len(inv)} existing NDVI outputs in S3 for {tile}")

    # 2) Build or load manifest (scenes to process)
    manifest_df = load_or_build_manifest(
        tile=tile,
        manifest_uri=args.manifest_uri,
        source_dir=args.source_dir,      # can remain optional
        cloud_max=args.cloud_max,
        start_date=args.start_date,
        end_date=args.end_date,
        work_dir=str(work_dir),
        tile_shp=args.tile_shp,
        # query_script=args.query_script,
        comparison_csv=args.comparison_csv,
    )


    print(f"[INFO] Manifest scenes after cloud<={args.cloud_max}% filter: {len(manifest_df)}")

    if args.limit and args.limit > 0:
        manifest_df = manifest_df.head(args.limit)
        print(f"[INFO] Limit enabled: processing {len(manifest_df)} scenes")

    # 3) Process each scene/date
    for row in manifest_df.itertuples(index=False):
        yyyymmdd = row.date
        platform = row.platform

        # We produce NDVI COG output key; datatype is "ndvi"
        out_key = f"{args.s3_prefix}/tiles/{tile}/ndvi/{platform}/{yyyymmdd[:4]}/{yyyymmdd}/" \
                  f"lztmre_{tile}_{yyyymmdd}_ndvi_{row.target_epsg}.tif"

        if (not args.rebase) and s3_key_exists(args.s3_bucket, out_key):
            print(f"[SKIP] Exists: s3://{args.s3_bucket}/{out_key}")
            upsert_inventory_row(args.s3_bucket, args.s3_prefix, tile, yyyymmdd, platform,
                                 status="skipped_exists", output_key=out_key, cloud=row.cloud)
            continue

        if args.dry_run:
            print(f"[DRY] Would process {tile} {platform} {yyyymmdd} -> {out_key}")
            continue

        try:
            process_scene_to_s3(
                tile=tile,
                date=yyyymmdd,
                platform=platform,
                red_path=row.red_path,
                nir_path=row.nir_path,
                ffmask_path=row.ffmask_path,
                bucket=args.s3_bucket,
                out_key=out_key,
                work_dir=work_dir,
                target_epsg=args.target_epsg,   # 0 => derive MGA zone
                resolution=args.resolution,
                rebase=args.rebase,
            )
            upsert_inventory_row(args.s3_bucket, args.s3_prefix, tile, yyyymmdd, platform,
                                 status="ok", output_key=out_key, cloud=row.cloud)
        except Exception as e:
            print(f"[ERROR] {tile} {platform} {yyyymmdd}: {e}")
            upsert_inventory_row(args.s3_bucket, args.s3_prefix, tile, yyyymmdd, platform,
                                 status="failed", output_key=out_key, cloud=row.cloud, error=str(e))

    print("[DONE] Pipeline finished.")


if __name__ == "__main__":
    main()

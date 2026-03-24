#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from tasks.task01_inventory_s3 import inventory_existing_outputs
from tasks.task02_build_scene_manifest import load_or_build_manifest
from tasks.task03_process_scene_ndvi import process_scene_to_s3
from lib.s3_io import s3_key_exists

"""
Example prompt:

python /home/jovyan/work-easi-eds/scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
  --tile p089r084 \
  --s3-bucket dcceew-eds-data \
  --s3-prefix "AROAZ6PFZYT4B4C7MNRHV:robotmcgregor/eds/optimised" \
  --work-dir /home/jovyan/scratch/eds-work-optimised \
  --cloud-max 40 \
  --start-date 2013-01-01 \
  --end-date 2026-22-17 \
  --limit 1
"""
def parse_args():
    ap = argparse.ArgumentParser("Optimised NDVI pipeline (datacube-native, COG->S3)")

    ap.add_argument("--tile", required=True, help="e.g. p089r084")

    ap.add_argument("--s3-bucket", required=True, help="e.g. dcceew-eds-data")
    ap.add_argument("--s3-prefix", required=True, help="e.g. ARO...:robotmcgregor/eds/optimised")

    ap.add_argument("--work-dir", required=True, help="Local work dir (avoid /scratch if not permitted)")

    ap.add_argument("--tile-shp", default="/home/jovyan/assets/eds_lsat_grid_min_max.shp",

                    help="Tile grid shapefile used to derive bbox/geom for tile")

    ap.add_argument("--manifest-uri", default=None,
                    help="Optional s3://.../manifests/<tile>_manifest.parquet. If omitted, uses default under s3-prefix.")

    ap.add_argument("--start-date", default=None, help="YYYY-MM-DD (optional)")
    ap.add_argument("--end-date", default=None, help="YYYY-MM-DD (optional)")

    ap.add_argument("--products", nargs="+", default=["ga_ls8c_ard_3", "ga_ls9c_ard_3"],
                    help="Datacube product names for LS8/LS9 ARD")

    ap.add_argument("--cloud-max", type=float, default=40.0,
                    help="Max cloud cover percent. Implemented as MIN CLEAR PCT = 100 - cloud_max (using oa_fmask==1)")

    ap.add_argument("--target-epsg", type=int, default=0,
                    help="Override output EPSG (e.g. 28352). If 0, derive GDA94 MGA zone EPSG:283xx from tile centroid.")

    ap.add_argument("--resolution", type=float, default=30.0, help="Output pixel size in metres (default 30)")

    ap.add_argument("--rebase", action="store_true",
                    help="Overwrite existing outputs (NDVI and ffmask). Default: resume/skip if exists.")

    ap.add_argument("--limit", type=int, default=0, help="Process only first N scenes (0 = no limit)")
    ap.add_argument("--dry-run", action="store_true")

    # Dask chunking (keeps it cheap)
    ap.add_argument("--chunk", type=int, default=2048, help="Dask chunk size for x/y (default 2048)")

    return ap.parse_args()


def default_manifest_uri(bucket: str, prefix: str, tile: str) -> str:
    return f"s3://{bucket}/{prefix}/manifests/{tile}_manifest.parquet"


def main():
    args = parse_args()
    tile = args.tile.lower()

    work_dir = Path(args.work_dir) / tile
    work_dir.mkdir(parents=True, exist_ok=True)

    manifest_uri = args.manifest_uri or default_manifest_uri(args.s3_bucket, args.s3_prefix, tile)
    print(f"[INFO] Manifest URI: {manifest_uri}")

    # 1) inventory existing NDVI outputs (so resume is fast)
    existing = inventory_existing_outputs(
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        tile=tile,
    )
    print(f"[INFO] Existing NDVI outputs found in S3: {len(existing)}")

    # 2) build/load manifest (parquet) from datacube
    manifest_df = load_or_build_manifest(
        tile=tile,
        manifest_uri=manifest_uri,
        tile_shp=args.tile_shp,
        products=args.products,
        cloud_max=args.cloud_max,
        start_date=args.start_date,
        end_date=args.end_date,
        work_dir=str(work_dir),
        target_epsg=args.target_epsg,
    )

    print("[DEBUG] manifest cols:", list(manifest_df.columns))
    print(manifest_df.head(1).to_dict("records"))

    print(f"[INFO] Manifest scenes after filtering: {len(manifest_df)}")

    if args.limit and args.limit > 0:
        manifest_df = manifest_df.head(args.limit).reset_index(drop=True)
        print(f"[INFO] Limit enabled: {len(manifest_df)} scenes")

   # 3) process each scene
    for row in manifest_df.itertuples(index=False):
        yyyymmdd = str(row.date)
        product = str(row.product)
        platform = str(row.platform)
        target_epsg = int(row.target_epsg)

        # output keys
        out_dir  = f"{args.s3_prefix}/tiles/{tile}/ndvi/{platform}/{yyyymmdd[:4]}/{yyyymmdd}"
        ndvi_key = f"{out_dir}/lztmre_{tile}_{yyyymmdd}_ndvi_{target_epsg}.tif"
        fmk_key  = f"{out_dir}/lztmre_{tile}_{yyyymmdd}_ffmask_{target_epsg}.tif"


        # import sys
        # sys.exit("brek run...")

        if not args.rebase:
            if s3_key_exists(args.s3_bucket, ndvi_key) and s3_key_exists(args.s3_bucket, fmk_key):
                print(f"[SKIP] Exists: s3://{args.s3_bucket}/{ndvi_key}")
                continue

        if args.dry_run:
            print(f"[DRY] Would process {tile} {platform} {yyyymmdd} product={product} -> {ndvi_key}")
            continue

        # call process_scene_to_s3
        process_scene_to_s3(
            tile=tile,
            date=yyyymmdd,
            platform=platform,
            product=product,
            lon_min=float(row.lon_min),
            lat_min=float(row.lat_min),
            lon_max=float(row.lon_max),
            lat_max=float(row.lat_max),
            target_epsg=int(row.target_epsg),
            cloud_max=float(args.cloud_max),
            bucket=args.s3_bucket,
            ndvi_key=ndvi_key,
            ffmask_key=fmk_key,
            work_dir=work_dir,
            resolution=float(args.resolution),
            rebase=bool(args.rebase),
        )


    print("[DONE] NDVI pipeline finished.")


if __name__ == "__main__":
    main()

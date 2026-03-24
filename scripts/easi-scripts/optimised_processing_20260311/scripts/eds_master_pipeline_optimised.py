#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from tasks.task02_resolve_sr_dates import resolve_sr_start_end
from tasks.task03_ensure_seasonal_ndvi import build_seasonal_ndvi_plan, ensure_seasonal_ndvi_in_s3
from tasks.task04_build_db8_sr_composite import build_db8_sr_to_s3
from tasks.task07_stage_dc4_locally import stage_dc4_ndvi_locally
from tasks.task05_run_legacy_method import run_legacy_ndvi_window
from tasks.task06_convert_and_upload_outputs import convert_outputs_to_cog_and_upload
from tasks.task08_masks_and_vectors import make_masks_and_vectors


"""Optimised EDS processing pipeline (NDVI seasonal-window; datacube-native)

This pipeline is meant to replace the older "eds_processing" script for the
processing stage, but still keep the old logic basically the same.

Key ideas
- Reuse NDVI (dc4) COGs that are already in S3 (made by optimised_ndvi).
- Only build the start/end SR stacks (db8) that we actually need for the dates.
- Run the legacy seasonal-window method (same thresholds/logic, not rewriting it).
- Convert the old outputs to Cloud-Optimised GeoTIFFs (COGs) and push to S3.

Example
python /home/jovyan/work-easi-eds/scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py \
  --tile p089r078 \
  --start-date 2023-03-06 \
  --end-date 2023-10-24 \
  --s3-bucket dcceew-eds-data \
  --s3-prefix "AROAZ6PFZYT4B4C7MNRHV:robotmcgregor/eds/optimised" \
  --work-dir /home/jovyan/scratch/eds-work-processing \
  --cloud-max 40 \
  --lookback 10 \
  --copy-to-home \
#   --zip-home

"""


def parse_args():
    ap = argparse.ArgumentParser('Optimised EDS processing (NDVI seasonal window)')

    ap.add_argument('--tile', required=True, help='e.g. p115r078')
    ap.add_argument('--start-date', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end-date', required=True, help='YYYY-MM-DD')

    ap.add_argument('--s3-bucket', required=True)
    ap.add_argument('--s3-prefix', required=True)

    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--tile-shp', default='/home/jovyan/assets/eds_lsat_grid_min_max.shp')

    ap.add_argument('--cloud-max', type=float, default=40.0)

    # datacube products
    ap.add_argument('--sr-products', nargs='+', default=['ga_ls8c_ard_3', 'ga_ls9c_ard_3'])
    ap.add_argument('--ndvi-products', nargs='+', default=['ga_ls8c_ard_3', 'ga_ls9c_ard_3'])

    ap.add_argument('--target-epsg', type=int, default=0)
    ap.add_argument('--resolution', type=float, default=30.0)
    ap.add_argument('--chunk', type=int, default=2048)

    ap.add_argument('--lookback', type=int, default=10)

    ap.add_argument('--rebase', action='store_true', help='Overwrite existing derived products')
    ap.add_argument('--dry-run', action='store_true')

    ap.add_argument('--diagnostics', action='store_true')
    ap.add_argument('--verbose', action='store_true')

    # output tagging
    ap.add_argument('--run-tag', default=None, help='Optional run tag for output folder (default: tile_d<start><end>)')

    # NDVI Clear and MAsk itemsparser.add_argument("--strong-threshold", type=int, default=60)
    ap.add_argument("--strong-threshold", type=int, default=60)
    ap.add_argument("--clear-threshold", type=int, default=80)
    ap.add_argument("--min-area-ha", type=float, default=10.0)

    # Results to home
    ap.add_argument(
        "--copy-to-home",
        action="store_true",
        help="Copy db8 + outputs + masks + shapefiles to a folder under /home/jovyan for easy retrieval.",
        )
    ap.add_argument(
        "--home-out-dir",
        default="/home/jovyan/eds-outputs",
        help="Base folder for --copy-to-home outputs (default: /home/jovyan/eds-outputs).",
    )

    ap.add_argument(
        "--zip-home",
        action="store_true",
        help="Zip the copied home output folder after copying."
    )

    # Save out unmasked SR cogs
    ap.add_argument(
        "--export-sr-raw-cog",
        action="store_true",
        help="Export the *unmasked* SR composites (start/end) as Cloud Optimised GeoTIFFs (COGs).",
    )
    ap.add_argument(
        "--export-sr-raw-cog-dirname",
        default="sr_raw_cog",
        help="Subfolder under <out-root>/<scene>/ to write SR raw COGs (default: sr_raw_cog).",
    )

    return ap.parse_args()



from pathlib import Path
from osgeo import gdal

def _prefer_unmasked_sr(sr_path: str) -> str:
    """
    If sr_path points at *_clr.tif and the non-clr sibling exists, return that.
    Otherwise return sr_path unchanged.
    """
    p = Path(sr_path)
    name = p.name
    if name.endswith("_clr.tif"):
        cand = p.with_name(name.replace("_clr.tif", ".tif"))
        if cand.exists():
            return str(cand)
    return sr_path

def _write_cog(src: str, dst: str) -> None:
    """
    Write a COG using GDAL. Keeps datatype/bands; uses DEFLATE compression.
    """
    Path(dst).parent.mkdir(parents=True, exist_ok=True)

    co = [
        "COMPRESS=DEFLATE",
        "PREDICTOR=2",
        "BIGTIFF=IF_SAFER",
        "NUM_THREADS=ALL_CPUS",
    ]

    # GDAL COG driver builds overviews by default
    out = gdal.Translate(
        destName=dst,
        srcDS=src,
        format="COG",
        creationOptions=co,
    )
    if out is None:
        raise RuntimeError(f"COG write failed: {src} -> {dst}")
    out = None

def _norm_yyyymmdd(iso: str) -> str:
    y, m, d = iso.split('-')
    return f'{y}{m}{d}'


def main():
    args = parse_args()
    tile = args.tile.lower().strip()
    work_dir = Path(args.work_dir) / tile
    work_dir.mkdir(parents=True, exist_ok=True)

    sd = _norm_yyyymmdd(args.start_date)
    ed = _norm_yyyymmdd(args.end_date)

    run_tag = args.run_tag or f'{tile}_d{sd}{ed}'

    # import sys
    # sys.exit("stop here....")

    # ------------------------------------------------------------
    # 1) Resolve SR start/end dates (cloud metadata <= cloud_max)
    # ------------------------------------------------------------
    sr = resolve_sr_start_end(
        tile=tile,
        tile_shp=args.tile_shp,
        products=args.sr_products,
        cloud_max=float(args.cloud_max),
        start_date=args.start_date,
        end_date=args.end_date,
        # target_epsg=int(args.target_epsg),
    )

    eff_sd = str(sr.start_row.date)
    eff_ed = str(sr.end_row.date)

    print(f"[INFO] Effective SR start: {eff_sd} (product={sr.start_row['product']}, cloud={float(sr.start_row['cloud']):.2f})")
    print(f"[INFO] Effective SR end:   {eff_ed} (product={sr.end_row['product']}, cloud={float(sr.end_row['cloud']):.2f})")

    # import sys
    # sys.exit("stop here....")
    # ------------------------------------------------------------
    # 2) Build + ensure seasonal NDVI (dc4) in S3 across lookback
    # ------------------------------------------------------------
    plan = build_seasonal_ndvi_plan(
        tile=tile,
        tile_shp=args.tile_shp,
        products=args.ndvi_products,
        cloud_max=float(args.cloud_max),
        start_yyyymmdd=eff_sd,
        end_yyyymmdd=eff_ed,
        lookback_years=int(args.lookback),
        target_epsg=int(args.target_epsg),
    )

    print(f'[INFO] Seasonal window: {plan.window.window_start_mmdd} -> {plan.window.window_end_mmdd} (months {plan.window.months_hint()})')
    print(f'[INFO] NDVI scenes in seasonal plan: {len(plan.required_rows)}')

    ensure_seasonal_ndvi_in_s3(
        plan=plan,
        tile=tile,
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        work_dir=work_dir / 'ndvi_work',
        cloud_max=float(args.cloud_max),
        resolution=float(args.resolution),
        rebase=bool(args.rebase),
        dry_run=bool(args.dry_run),
        dask_chunk=int(args.chunk),
    )

    import sys
    sys.exit("stop here....")
    # Stage required NDVI locally for the legacy method
    required_dates = []
    for r in plan.required_rows.itertuples(index=False):
        required_dates.append((str(r.date), str(r.platform), int(r.target_epsg)))


    if args.dry_run:
        print('[DRY] Skipping dc4 NDVI staging (download).')
        print('[DRY] Skipping db8 SR build.')
        print('[DRY] Skipping legacy method run + output conversion.')
        return

    dc4_dir = stage_dc4_ndvi_locally(
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        tile=tile,
        required_dates=required_dates,
        work_dir=work_dir,
        dry_run=bool(args.dry_run),
    )



    import sys
    sys.exit("stop here....")
    # ------------------------------------------------------------
    # 3) Build db8 SR composites for start/end
    # ------------------------------------------------------------
    db8_start = build_db8_sr_to_s3(
        tile=tile,
        date=eff_sd,
        platform=str(sr.start_row["platform"]),
        product=str(sr.start_row["product"]),
        lon_min=float(sr.start_row["lon_min"]),
        lat_min=float(sr.start_row["lat_min"]),
        lon_max=float(sr.start_row["lon_max"]),
        lat_max=float(sr.start_row["lat_max"]),
        target_epsg=int(sr.start_row["target_epsg"]),
        cloud_max=float(args.cloud_max),
        bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        work_dir=work_dir / 'db8_work',
        resolution=float(args.resolution),
        dask_chunk=int(args.chunk),
        rebase=bool(args.rebase),
        dry_run=bool(args.dry_run),
    )


    db8_end = build_db8_sr_to_s3(
        tile=tile,
        date=eff_ed,
        platform=str(sr.end_row["platform"]),
        product=str(sr.end_row["product"]),
        lon_min=float(sr.end_row["lon_min"]),
        lat_min=float(sr.end_row["lat_min"]),
        lon_max=float(sr.end_row["lon_max"]),
        lat_max=float(sr.end_row["lat_max"]),
        target_epsg=int(sr.end_row["target_epsg"]),
        cloud_max=float(args.cloud_max),
        bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        work_dir=work_dir / 'db8_work',
        resolution=float(args.resolution),
        dask_chunk=int(args.chunk),
        rebase=bool(args.rebase),
        dry_run=bool(args.dry_run),
    )



    # ------------------------------------------------------------
    # 4) (NEW) Export unmasked SR (db8) as COGs (start/end)
    # ------------------------------------------------------------
    if args.export_sr_raw_cog:
        sr_raw_dir = work_dir / args.export_sr_raw_cog_dirname  # e.g. <work>/<tile>/sr_raw_cog

        # These are the SR composites you already built (db8)
        sr_start_path = str(db8_start.local_path)
        sr_end_path   = str(db8_end.local_path)

        raw_start = _prefer_unmasked_sr(sr_start_path)
        raw_end   = _prefer_unmasked_sr(sr_end_path)

        start_cog = sr_raw_dir / f"{tile}_{eff_sd}_sr_raw_cog.tif"
        end_cog   = sr_raw_dir / f"{tile}_{eff_ed}_sr_raw_cog.tif"

        print(f"[SR-RAW-COG] start: {raw_start} -> {start_cog}")
        print(f"[SR-RAW-COG] end  : {raw_end} -> {end_cog}")

        if not args.dry_run:
            _write_cog(raw_start, str(start_cog))
            _write_cog(raw_end, str(end_cog))

    # ------------------------------------------------------------
    # 5) Run legacy method + convert outputs to COG
    # ------------------------------------------------------------
    outputs = run_legacy_ndvi_window(
        methods_dir=Path(__file__).parent / 'methods',
        scene=tile,
        start_date=eff_sd,
        end_date=eff_ed,
        dc4_glob=str(dc4_dir / '*.tif'),
        start_db8=str(db8_start.local_path),
        end_db8=str(db8_end.local_path),
        window_start_mmdd=plan.window.window_start_mmdd,
        window_end_mmdd=plan.window.window_end_mmdd,
        lookback=int(args.lookback),
        diagnostics=bool(args.diagnostics),
        verbose=bool(args.verbose),
        vi_tag='vi-ndvi',
    )


    converted = convert_outputs_to_cog_and_upload(
        dll_img=outputs.dll_img,
        dlj_img=outputs.dlj_img,
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        tile=tile,
        run_tag=run_tag,
        work_dir=work_dir / "outputs",
    )

    dljmz_cog_local = Path(converted.dljmz_cog_local)

    for u in converted.uploaded:
        print("[OK]", u.s3_uri)

    # ------------------------------------------------------------
    # 5) Build strong/clear masks + polygonise to shapefiles
    # ------------------------------------------------------------
    from tasks.task08_masks_and_vectors import make_masks_and_vectors

    mv = make_masks_and_vectors(
        dljmz_cog_local=dljmz_cog_local,
        bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        tile=tile,
        run_tag=run_tag,
        strong_threshold=int(args.strong_threshold),  # 60
        clear_threshold=int(args.clear_threshold),    # 80
        min_area_ha=float(args.min_area_ha),          # default 10.0
        work_dir=work_dir / "maskvec_work",
        rebase=bool(args.rebase),
        dry_run=bool(args.dry_run),
    )

    print(f"[OK] Strong mask -> s3://{args.s3_bucket}/{mv.strong_mask_s3}")
    print(f"[OK] Clear  mask -> s3://{args.s3_bucket}/{mv.clear_mask_s3}")
    print(f"[OK] Strong SHP  -> s3://{args.s3_bucket}/{mv.strong_shp_s3_prefix}/")
    print(f"[OK] Clear  SHP  -> s3://{args.s3_bucket}/{mv.clear_shp_s3_prefix}/")

    # ------------------------------------------------------------
    # 6) Copy artefacts to /home/jovyan
    # ------------------------------------------------------------
    if bool(args.copy_to_home):
        from tasks.task09_copy_run_to_home import copy_run_to_home

        # Legacy ENVI outputs: include .img and .hdr if present
        legacy_files = [Path(outputs.dll_img), Path(outputs.dlj_img)]
        for p in list(legacy_files):
            hdr = p.with_suffix(".hdr")
            if hdr.exists():
                legacy_files.append(hdr)

        # COG outputs from conversion
        cog_files = [
            Path(converted.dllmz_cog_local),
            Path(converted.dljmz_cog_local),
        ]

        # Masks (local) from mv
        mask_files = [Path(mv.strong_mask_local), Path(mv.clear_mask_local)]

        # Vector dirs used by task08 (these are the local dirs we wrote into)
        vector_dirs = [
            (work_dir / "maskvec_work" / "vectors" / "strong"),
            (work_dir / "maskvec_work" / "vectors" / "clear"),
        ]

        copy_run_to_home(
        run_tag=run_tag,
        home_out_dir=Path(args.home_out_dir),
        db8_start_local=Path(db8_start.local_path),
        db8_end_local=Path(db8_end.local_path),
        legacy_outputs=legacy_files,
        cog_outputs=cog_files,
        mask_outputs=mask_files,
        vector_dirs=vector_dirs,
        zip_after=bool(args.zip_home),
        dry_run=bool(args.dry_run),
    )




    print("[DONE] Optimised EDS processing complete.")



if __name__ == '__main__':
    main()
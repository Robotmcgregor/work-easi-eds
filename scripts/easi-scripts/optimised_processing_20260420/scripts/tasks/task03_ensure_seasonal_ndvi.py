from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

import pandas as pd

from lib.dates import SeasonalWindow
from lib.tile_grid import load_tile_bbox_wgs84, derive_target_epsg_gda94_mga_from_lon
from lib.datacube_manifest import build_scene_manifest_from_datacube_bbox
from lib.s3_io import s3_key_exists

from tasks.task03_process_scene_ndvi import process_scene_to_s3


@dataclass(frozen=True)
class SeasonalNDVIPlan:
    window: SeasonalWindow
    required_rows: pd.DataFrame  # rows it should use use (date/platform/ product/epsg/ bbox)


def build_seasonal_ndvi_plan(
    *,
    tile: str,
    tile_shp: str,
    products: List[str],
    cloud_max: float,
    start_yyyymmdd: str,
    end_yyyymmdd: str,
    lookback_years: int,
    target_epsg: int = 0,
) -> SeasonalNDVIPlan:
    tile = tile.lower().strip()

    lon_min, lat_min, lon_max, lat_max = load_tile_bbox_wgs84(tile_shp=tile_shp, tile=tile)
    if not target_epsg or int(target_epsg) == 0:
        centre_lon = (lon_min + lon_max) / 2.0
        target_epsg = derive_target_epsg_gda94_mga_from_lon(centre_lon)

    window = SeasonalWindow.from_start_end(start_yyyymmdd, end_yyyymmdd, expand_months=2)

    df = build_scene_manifest_from_datacube_bbox(
        tile=tile,
        lon_min=lon_min,
        lat_min=lat_min,
        lon_max=lon_max,
        lat_max=lat_max,
        products=products,
        target_epsg=int(target_epsg),
        cloud_max=float(cloud_max),
        app='optimised_processing_ndvi_manifest',
    )

    # Keep all candidate scenes from the lookback period up to the END year,
    # not just up to the START year. This allows cross-year runs such as:
    #   start = 20250607
    #   end   = 20260125
    # to retain valid 2026 scenes in the manifest.
    start_year = int(start_yyyymmdd[:4])
    end_year = int(end_yyyymmdd[:4])
    min_year = start_year - int(lookback_years)

    years = df['date'].astype(str).str[:4].astype(int)
    df = df[(years >= min_year) & (years <= end_year)].copy()

    print("[DEBUG] start_yyyymmdd:", start_yyyymmdd)
    print("[DEBUG] end_yyyymmdd  :", end_yyyymmdd)
    print("[DEBUG] start_year    :", start_year)
    print("[DEBUG] end_year      :", end_year)
    print("[DEBUG] min_year      :", min_year)
    print("[DEBUG] years after year filter:", sorted(years[(years >= min_year) & (years <= end_year)].unique().tolist()))

    # Keep only dates inside the seasonal window
    df = df[df['date'].apply(lambda d: window.in_window(str(d)))].copy()

    print("[DEBUG] rows after window filter:")
    if df.empty:
        print("   <none>")
    else:
        print(df[['date', 'platform', 'product', 'target_epsg']].sort_values(['date', 'platform', 'product']).to_string(index=False))

    # Sort for stable downstream processing
    df = df.sort_values(['date', 'platform', 'product']).reset_index(drop=True)
    # print("df: ", df)

    # import sys
    # sys.exit("checking for 2026 data")

    return SeasonalNDVIPlan(window=window, required_rows=df)


def ensure_seasonal_ndvi_in_s3(
    *,
    plan: SeasonalNDVIPlan,
    tile: str,
    bucket: str,
    prefix: str,
    work_dir: Path,
    cloud_max: float,
    resolution: float,
    rebase: bool,
    dry_run: bool,
    dask_chunk: int = 2048,
) -> None:
    """Ensure all NDVI outputs required by the seasonal plan exist in S3.

    Uses the same output layout as optimised_ndvi.
    """
    tile = tile.lower().strip()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    for row in plan.required_rows.itertuples(index=False):
        yyyymmdd = str(row.date)
        platform = str(row.platform)
        product = str(row.product)
        target_epsg = int(row.target_epsg)

        out_dir = f"{prefix.rstrip('/')}/tiles/{tile}/ndvi/{platform}/{yyyymmdd[:4]}/{yyyymmdd}"
        ndvi_key = f"{out_dir}/lztmre_{tile}_{yyyymmdd}_ndvi_e{target_epsg}.tif"
        fmk_key = f"{out_dir}/lztmre_{tile}_{yyyymmdd}_ffmask_e{target_epsg}.tif"

        print("out_dir: ", out_dir)
        print("ndvi_key: ", ndvi_key)
        print("fmk_key : ", fmk_key)

        out_dir = f"{prefix.rstrip('/')}/tiles/{tile}/{yyyymmdd[:4]}/{yyyymmdd}"
        ndvi_key = f"{out_dir}/sl{platform[1:]}olre_{tile}_{yyyymmdd}_ga1-clr_e{target_epsg}.tif"
        fmk_key = f"{out_dir}/sl{platform[1:]}olre_{tile}_{yyyymmdd}_ga2_e{target_epsg}.tif"

        print("out_dir: ", out_dir)
        print("ndvi_key: ", ndvi_key)
        print("fmk_key : ", fmk_key)
        # import sys
        # sys.exit("print ndvi file names")

        print(f"[DEBUG] checking S3 for {yyyymmdd} {platform}")
        print(f"[DEBUG] ndvi_key = s3://{bucket}/{ndvi_key}")
        print(f"[DEBUG] fmk_key  = s3://{bucket}/{fmk_key}")

        # if not rebase:
        #     if s3_key_exists(bucket, ndvi_key) and s3_key_exists(bucket, fmk_key):
        #         continue
        ndvi_exists = s3_key_exists(bucket, ndvi_key)
        fmk_exists = s3_key_exists(bucket, fmk_key)

        print(f"[DEBUG] ndvi_exists={ndvi_exists} fmk_exists={fmk_exists}")

        if not rebase:
            if ndvi_exists and fmk_exists:
                print(f"[DEBUG] already present in S3, skipping {yyyymmdd} {platform}")
                continue
        if dry_run:
            print(f"[DRY] NDVI {tile} {platform} {yyyymmdd} -> s3://{bucket}/{ndvi_key}")
            continue

        result = process_scene_to_s3(
            tile=tile,
            date=yyyymmdd,
            platform=platform,
            product=product,
            lon_min=float(row.lon_min),
            lat_min=float(row.lat_min),
            lon_max=float(row.lon_max),
            lat_max=float(row.lat_max),
            target_epsg=int(row.target_epsg),
            cloud_max=float(cloud_max),
            bucket=bucket,
            ndvi_key=ndvi_key,
            ffmask_key=fmk_key,
            work_dir=work_dir,
            resolution=float(resolution),
            rebase=bool(rebase),
            dask_chunk=int(dask_chunk),
        )

        if result is None:
            continue

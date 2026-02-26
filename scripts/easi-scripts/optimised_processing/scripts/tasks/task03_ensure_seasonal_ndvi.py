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

    start_year = int(start_yyyymmdd[:4])
    min_year = start_year - int(lookback_years)

    df = df[(df['date'].astype(str).str[:4].astype(int) >= min_year) & (df['date'].astype(str).str[:4].astype(int) <= start_year)]

    # keep only dates in seasonal window
    df = df[df['date'].apply(lambda d: window.in_window(str(d)))]

    # sort
    df = df.sort_values(['date', 'platform', 'product']).reset_index(drop=True)

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
        ndvi_key = f"{out_dir}/lztmre_{tile}_{yyyymmdd}_ndvi_{target_epsg}.tif"
        fmk_key = f"{out_dir}/lztmre_{tile}_{yyyymmdd}_ffmask_{target_epsg}.tif"

        if not rebase:
            if s3_key_exists(bucket, ndvi_key) and s3_key_exists(bucket, fmk_key):
                continue

        if dry_run:
            print(f"[DRY] NDVI {tile} {platform} {yyyymmdd} -> s3://{bucket}/{ndvi_key}")
            continue

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
            cloud_max=float(cloud_max),
            bucket=bucket,
            ndvi_key=ndvi_key,
            ffmask_key=fmk_key,
            work_dir=work_dir,
            resolution=float(resolution),
            rebase=bool(rebase),
            dask_chunk=int(dask_chunk),
        )

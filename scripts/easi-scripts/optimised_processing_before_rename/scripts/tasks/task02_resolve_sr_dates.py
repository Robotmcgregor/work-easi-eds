from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional



import pandas as pd

from lib.tile_grid import load_tile_bbox_wgs84, derive_target_epsg_gda94_mga_from_lon
from lib.datacube_manifest import build_scene_manifest_from_datacube_bbox


@dataclass(frozen=True)
class ResolvedSR:
    start_row: pd.Series
    end_row: pd.Series


def resolve_sr_start_end(
    *,
    tile: str,
    tile_shp: str,
    products: List[str],
    cloud_max: float,
    start_date: str,  # YYYY-MM-DD or YYYYMMDD
    end_date: str,
    target_epsg: int = 0,
) -> ResolvedSR:
    """Resolve SR "effective" start/end scenes for a tile.

    How it works (basic idea):
    1) query datacube for SR ARD scenes that touch the tile bbox
    2) filter using scene cloud metadata <= cloud_max (strict)
    3) pick:
        - start scene = closest date on/before start_date
        - end scene   = closest date on/after end_date

    This is basically what the old EDS pipeline was trying to do, just using the
    datacube manifest style like optimised_ndvi does.
    """
    tile = tile.lower().strip()

    def norm(d: str) -> str:
        d = d.strip()
        if '-' in d:
            y, m, dd = d.split('-')
            return f'{y}{m}{dd}'
        return d

    sd = norm(start_date)
    ed = norm(end_date)

    lon_min, lat_min, lon_max, lat_max = load_tile_bbox_wgs84(tile_shp=tile_shp, tile=tile)

    if not target_epsg or int(target_epsg) == 0:
        centre_lon = (lon_min + lon_max) / 2.0
        target_epsg = derive_target_epsg_gda94_mga_from_lon(centre_lon)

    df = build_scene_manifest_from_datacube_bbox(
        tile=tile,
        lon_min=lon_min,
        lat_min=lat_min,
        lon_max=lon_max,
        lat_max=lat_max,
        products=products,
        target_epsg=int(target_epsg),
        cloud_max=float(cloud_max),
        app='optimised_processing_sr_manifest',
    )

    # before = df[df['date'] <= sd]
    # after = df[df['date'] >= ed]

    # if len(before) == 0:
    #     raise RuntimeError(f'No SR scenes found on/before start_date={sd} for tile={tile} (cloud_max={cloud_max})')
    # if len(after) == 0:
    #     raise RuntimeError(f'No SR scenes found on/after end_date={ed} for tile={tile} (cloud_max={cloud_max})')

    # start_row = before.iloc[-1]
    # end_row = after.iloc[0]

    before = df[df["date"] <= sd]
    after  = df[df["date"] >= ed]

    # ---- clamp start/end to available archive range (still respecting cloud_max) ----
    if len(before) == 0:
        # start_date earlier than available data ---->>>> use earliest available
        start_row = df.iloc[0]
        print(
            f"[WARN] No SR scenes on/before start_date={sd} for tile={tile} "
            f"(cloud_max={cloud_max}). Using earliest available: {start_row['date']}"
        )
    else:
        start_row = before.iloc[-1]

    if len(after) == 0:
        # end_date later than available data → use latest available
        end_row = df.iloc[-1]
        print(
            f"[WARN] No SR scenes on/after end_date={ed} for tile={tile} "
            f"(cloud_max={cloud_max}). Using latest available: {end_row['date']}"
        )
    else:
        end_row = after.iloc[0]



    return ResolvedSR(start_row=start_row, end_row=end_row)

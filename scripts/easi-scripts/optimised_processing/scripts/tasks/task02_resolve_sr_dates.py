#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# MIT License

# Copyright (c) 2026 Robert McGregor

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ------------------------------------------------------------------------------
# 



from __future__ import annotations

"""Task 02: choose the start/end Surface Reflectance scenes.

Non-coder summary:
- You give the pipeline a tile and a date range.
- Landsat does not have an image for every day, and many images are too cloudy.
- This task searches datacube for candidate SR scenes and picks:
    - the best start scene on/before your start date
    - the best end scene on/after your end date

The result is used to build the SR composites (GA0) and to decide the effective
dates the rest of the pipeline should use.
"""

from dataclasses import dataclass
from typing import List, Optional



import pandas as pd

# from lib.tile_grid import load_tile_bbox_wgs84, derive_target_epsg_gda94_mga_from_lon
from lib.tile_grid import load_tile_bbox_wgs84
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
) -> ResolvedSR:
    """Return the SR scenes the pipeline will actually use.

    In plain English:
    - We look for low-cloud SR scenes that overlap the tile.
    - We choose the closest usable SR scene before/at start_date.
    - We choose the closest usable SR scene after/at end_date.

    This makes runs repeatable and avoids using very cloudy SR scenes.
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

    # if not target_epsg or int(target_epsg) == 0:
    #     centre_lon = (lon_min + lon_max) / 2.0
    #     target_epsg = derive_target_epsg_gda94_mga_from_lon(centre_lon)


    df = build_scene_manifest_from_datacube_bbox(
        tile=tile,
        lon_min=lon_min,
        lat_min=lat_min,
        lon_max=lon_max,
        lat_max=lat_max,
        products=products,
        cloud_max=float(cloud_max),
        app='optimised_processing_sr_manifest',
    )

    # ------------------------------------------------------------------
    # SAFETY: native EPSG must exist in the manifest (native-crs mode)
    # ------------------------------------------------------------------
    if "dataset_epsg" not in df.columns:
        raise RuntimeError(
            "Manifest is missing 'dataset_epsg'. "
            "Update build_scene_manifest_from_datacube_bbox() to include dataset_epsg per dataset."
        )

    if df["dataset_epsg"].isna().any():
        bad = df[df["dataset_epsg"].isna()][["date", "product"]].head(10)
        raise RuntimeError(
            "Some SR datasets have no EPSG code (dataset_epsg is NaN). Examples:\n"
            f"{bad.to_string(index=False)}"
        )

    # ------------------------------------------------------------------
    # OPTIONAL: warn if multiple native CRSs exist for this tile/time range
    # (downstream processing must handle per-scene CRS if they differ)
    # ------------------------------------------------------------------
    epsgs = sorted({int(x) for x in df["dataset_epsg"].values})
    if len(epsgs) > 1:
        print(f"[WARN] Multiple native EPSGs found for tile={tile}: {epsgs}")

    before = df[df["date"] <= sd]
    after  = df[df["date"] >= ed]

    # df = build_scene_manifest_from_datacube_bbox(
    #     tile=tile,
    #     lon_min=lon_min,
    #     lat_min=lat_min,
    #     lon_max=lon_max,
    #     lat_max=lat_max,
    #     products=products,
    #     # target_epsg=int(target_epsg),
    #     cloud_max=float(cloud_max),
    #     app='optimised_processing_sr_manifest',
    # )

    # # before = df[df['date'] <= sd]
    # # after = df[df['date'] >= ed]

    # # if len(before) == 0:
    # #     raise RuntimeError(f'No SR scenes found on/before start_date={sd} for tile={tile} (cloud_max={cloud_max})')
    # # if len(after) == 0:
    # #     raise RuntimeError(f'No SR scenes found on/after end_date={ed} for tile={tile} (cloud_max={cloud_max})')

    # # start_row = before.iloc[-1]
    # # end_row = after.iloc[0]

    # before = df[df["date"] <= sd]
    # after  = df[df["date"] >= ed]

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

    # ------------------------------------------------------------------
    # OPTIONAL: warn if start/end native EPSG differ
    # ------------------------------------------------------------------
    if int(start_row["dataset_epsg"]) != int(end_row["dataset_epsg"]):
        print(
            f"[WARN] Start/end native EPSG differ for tile={tile}: "
            f"{int(start_row['dataset_epsg'])} vs {int(end_row['dataset_epsg'])}. "
            "Downstream processing must use row['dataset_epsg'] per scene when calling dc.load()."
        )

    return ResolvedSR(start_row=start_row, end_row=end_row)

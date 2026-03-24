from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SceneRecord:
    tile: str
    date: str  # YYYYMMDD
    platform: str
    product: str
    cloud: float
    target_epsg: int
    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float


def build_scene_manifest_from_datacube_bbox(
    *,
    tile: str,
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    products: List[str],
    cloud_max: float,
    target_epsg: Optional[int] = None,
    overlap_min_frac: float = 0.90,
    exclude_nrt: bool = True,
    app: str = 'optimised_processing_manifest',
) -> pd.DataFrame:
    """Query ODC/DEA datacube for scenes intersecting a tile bbox.

    Notes
    - Filtering is by *scene-level cloud metadata* (eo:cloud_cover) where present.
      Scenes with missing cloud metadata are skipped.
    - The real cloud/shadow masking is still done with oa_fmask at processing time.
    - We also filter to datasets whose footprint overlaps the tile bbox strongly.
    """
    import datacube
    from shapely.geometry import box, shape

    dc = datacube.Datacube(app=app)
    tile_poly = box(lon_min, lat_min, lon_max, lat_max)

    def overlap_ok(ds) -> bool:
        try:
            ds_poly = shape(ds.extent.to_crs('EPSG:4326').json)
        except Exception:
            return False
        inter = ds_poly.intersection(tile_poly)
        if inter.is_empty or not ds_poly.area:
            return False
        return (inter.area / ds_poly.area) >= overlap_min_frac

    def is_nrt(ds) -> bool:
        uri = getattr(ds, 'uri', None)
        if uri and '_nrt/' in str(uri):
            return True
        uris = getattr(ds, 'uris', []) or []
        return any('_nrt/' in str(u) for u in uris)

    rows = []

    for product in products:
        datasets = dc.find_datasets(
            product=product,
            lon=(lon_min, lon_max),
            lat=(lat_min, lat_max),
        )
        datasets = [ds for ds in datasets if overlap_ok(ds)]
        if exclude_nrt:
            datasets = [ds for ds in datasets if not is_nrt(ds)]

        for ds in datasets:
            date = ds.center_time.strftime('%Y%m%d')

            p = product.lower()
            platform = 'L9' if ('ls9' in p or 'landsat_9' in p) else ('L8' if ('ls8' in p or 'landsat_8' in p) else 'LS')

            cloud = np.nan
            md = getattr(ds, 'metadata_doc', {}) or {}
            for key in ('eo:cloud_cover', 'cloud_cover', 'landsat:cloud_cover'):
                if key in md:
                    try:
                        cloud = float(md[key])
                        break
                    except Exception:
                        pass
            try:
                props = md.get('properties', {})
                if np.isnan(cloud) and 'eo:cloud_cover' in props:
                    cloud = float(props['eo:cloud_cover'])
            except Exception:
                pass

            # strict filtering (matches optimised_ndvi manifest behaviour)
            if np.isnan(cloud) or cloud > float(cloud_max):
                continue

            # rows.append(
            #     dict(
            #         tile=tile,
            #         date=date,
            #         platform=platform,
            #         product=product,
            #         cloud=float(cloud),
            #         target_epsg=int(target_epsg),
            #         lon_min=float(lon_min),
            #         lat_min=float(lat_min),
            #         lon_max=float(lon_max),
            #         lat_max=float(lat_max),
            #     )
            # )
                        # Dataset native CRS / EPSG (from cube record)
            # ds_crs = getattr(ds, "crs", None)
            # ds_epsg = getattr(ds_crs, "epsg", None) if ds_crs is not None else None
            ds_crs = getattr(ds, "crs", None)
            ds_epsg = getattr(ds_crs, "epsg", None) if ds_crs is not None else None
            if ds_epsg is None:
                # cannot support native-CRS processing without a real EPSG
                continue
            # rows.append(
            #     dict(
            #         tile=tile,
            #         date=date,
            #         platform=platform,
            #         product=product,
            #         cloud=float(cloud),

            #         # what YOU want downstream
            #         target_epsg=int(target_epsg),

            #         # what the dataset actually is (native)
            #         dataset_epsg=int(ds_epsg) if ds_epsg is not None else np.nan,
            #         dataset_crs=str(ds_crs) if ds_crs is not None else "",

            #         lon_min=float(lon_min),
            #         lat_min=float(lat_min),
            #         lon_max=float(lon_max),
            #         lat_max=float(lat_max),
            #     )
            # )
            row = dict(
                tile=tile,
                date=date,
                platform=platform,
                product=product,
                cloud=float(cloud),

                # what the dataset actually is (native)
                dataset_epsg=int(ds_epsg) if ds_epsg is not None else np.nan,
                dataset_crs=str(ds_crs) if ds_crs is not None else "",

                lon_min=float(lon_min),
                lat_min=float(lat_min),
                lon_max=float(lon_max),
                lat_max=float(lat_max),
            )

            # optional: keep target_epsg only when supplied by caller
            if target_epsg is not None and int(target_epsg) != 0:
                row["target_epsg"] = int(target_epsg)

            rows.append(row)

    if not rows:
        raise RuntimeError(
            f'No datacube datasets found for tile={tile} (bbox {lon_min},{lat_min},{lon_max},{lat_max}) '
            f'for products={products} after cloud_max={cloud_max} filtering.'
        )

    # df = pd.DataFrame(rows).drop_duplicates(subset=['date', 'product'])
    df = pd.DataFrame(rows).drop_duplicates(subset=['date', 'product', 'dataset_epsg'])
    df = df.sort_values(['date', 'product']).reset_index(drop=True)
    return df


def pick_nearest_dates(df: pd.DataFrame, target_yyyymmdd: str) -> tuple[Optional[pd.Series], Optional[pd.Series]]:
    """Return (before_or_equal, after_or_equal) rows nearest to target date."""
    d = target_yyyymmdd
    before = df[df['date'] <= d]
    after = df[df['date'] >= d]

    before_row = None
    after_row = None
    if len(before):
        before_row = before.iloc[-1]
    if len(after):
        after_row = after.iloc[0]
    return before_row, after_row

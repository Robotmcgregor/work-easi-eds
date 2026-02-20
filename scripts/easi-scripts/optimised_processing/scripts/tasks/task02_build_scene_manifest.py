from __future__ import annotations
import geopandas as gpd
import re
from pathlib import Path
from typing import List
import pandas as pd
import numpy as np

from lib.s3_io import s3_uri_exists, download_s3_uri, upload_file_to_s3, parse_s3_uri
from lib.tile_grid import (
    load_tile_bbox_wgs84,
    derive_target_epsg_gda94_mga_from_lon,
)


from lib.cog import ensure_pyarrow


REQUIRED_COLS = [
    "tile", "date", "platform", "product", "cloud", "target_epsg",
    "lon_min", "lat_min", "lon_max", "lat_max",
]


def load_or_build_manifest(
    tile: str,
    manifest_uri: str,
    tile_shp: str,
    products: List[str],
    cloud_max: float,
    start_date: str | None,
    end_date: str | None,
    work_dir: str,
    target_epsg: int,
) -> pd.DataFrame:
    """
    Manifest is Parquet (local cache + optionally stored in S3).

    If it exists: load it.
    If not: build it by querying datacube datasets intersecting the tile geometry.

    NOTE: Filtering is STRICTLY by scene-level cloud metadata (cloud <= cloud_max).
        Scenes missing cloud metadata are skipped.

    """
    ensure_pyarrow()

    tile = tile.lower()
    cache_dir = Path(work_dir) / "manifests"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_cache = cache_dir / f"{tile}_manifest.parquet"

    # 1) load if exists
    if manifest_uri.startswith("s3://"):
        if s3_uri_exists(manifest_uri):
            download_s3_uri(manifest_uri, str(local_cache))
            df = pd.read_parquet(str(local_cache))
            return _finalise(df, start_date, end_date)
    else:
        p = Path(manifest_uri)
        if p.exists():
            df = pd.read_parquet(str(p))
            return _finalise(df, start_date, end_date)

    # 2) build from datacube dataset search (bbox-based)
    lon_min, lat_min, lon_max, lat_max = load_tile_bbox_wgs84(tile_shp=tile_shp, tile=tile)

    # derive MGA zone from bbox centre (unless caller forced target_epsg)
    if not target_epsg or int(target_epsg) == 0:
        centre_lon = (lon_min + lon_max) / 2.0
        target_epsg = derive_target_epsg_gda94_mga_from_lon(centre_lon)

    df = build_manifest_from_datacube_bbox(
        tile=tile,
        lon_min=lon_min,
        lat_min=lat_min,
        lon_max=lon_max,
        lat_max=lat_max,
        products=products,
        target_epsg=int(target_epsg),
        cloud_max=float(cloud_max),
    )

    df = _finalise(df, start_date, end_date)


    # 3) write parquet + upload
    df.to_parquet(str(local_cache), index=False)

    if manifest_uri.startswith("s3://"):
        b, k = parse_s3_uri(manifest_uri)
        upload_file_to_s3(local_path=str(local_cache), bucket=b, key=k)
        print(f"[OK] Manifest uploaded -> s3://{b}/{k}")
    else:
        Path(manifest_uri).parent.mkdir(parents=True, exist_ok=True)
        Path(str(local_cache)).replace(manifest_uri)

    return df


def build_manifest_from_datacube_bbox(
    tile: str,
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    products: List[str],
    target_epsg: int,
    cloud_max: float,
    overlap_min_frac: float = 0.90,
) -> pd.DataFrame:
    import datacube
    from shapely.geometry import box, shape

    dc = datacube.Datacube(app="optimised_ndvi_manifest")
    tile_poly = box(lon_min, lat_min, lon_max, lat_max)

    def overlap_ok(ds) -> bool:
        """Keep dataset if its footprint overlaps tile bbox strongly."""
        try:
            ds_poly = shape(ds.extent.to_crs("EPSG:4326").json)
        except Exception:
            return False

        inter = ds_poly.intersection(tile_poly)
        if inter.is_empty or not ds_poly.area:
            return False

        frac = inter.area / ds_poly.area
        return frac >= overlap_min_frac

    rows = []

    for product in products:
        # bbox query (fast)
        datasets = dc.find_datasets(
            product=product,
            lon=(lon_min, lon_max),
            lat=(lat_min, lat_max),
        )

        # guard against “bbox grabs neighbours”
        # datasets = [ds for ds in datasets if overlap_ok(ds)]
        # guard against “bbox grabs neighbours”
        datasets = [ds for ds in datasets if overlap_ok(ds)]

        # ------------------------------------------------------------------
        # Exclude NRT datasets (often incomplete/broken paths like ..._nrt/..._fmask.tif missing)
        # ------------------------------------------------------------------
        def is_nrt(ds) -> bool:
            # ODC 1.9+: prefer ds.uri; fallback to ds.uris
            uri = getattr(ds, "uri", None)
            if uri and "_nrt/" in str(uri):
                return True
            uris = getattr(ds, "uris", []) or []
            return any("_nrt/" in str(u) for u in uris)

        datasets = [ds for ds in datasets if not is_nrt(ds)]


        for ds in datasets:
            date = ds.center_time.strftime("%Y%m%d")

            # platform label (simple, based on product name)
            p = product.lower()
            platform = "L9" if "ls9" in p or "landsat_9" in p else ("L8" if "ls8" in p or "landsat_8" in p else "LS")

            # try to extract scene-level cloud cover if present (optional)
            cloud = np.nan
            md = getattr(ds, "metadata_doc", {}) or {}

            for key in ("eo:cloud_cover", "cloud_cover", "landsat:cloud_cover"):
                if key in md:
                    try:
                        cloud = float(md[key])
                        break
                    except Exception:
                        pass
            try:
                props = md.get("properties", {})
                if np.isnan(cloud) and "eo:cloud_cover" in props:
                    cloud = float(props["eo:cloud_cover"])
            except Exception:
                pass

            # # NOTE: we keep cloud in manifest, but your *real* masking will be oa_fmask==1 later
            # if (not np.isnan(cloud)) and cloud > cloud_max:
            #     continue

            # STRICT: only accept scenes with metadata cloud cover <= cloud_max.
            # If cloud metadata is missing, skip the scene.
            if np.isnan(cloud):
                continue

            if cloud > cloud_max:
                continue

            rows.append(
                {
                    "tile": tile,
                    "date": date,
                    "platform": platform,
                    "product": product,
                    "cloud": cloud,
                    "target_epsg": int(target_epsg),
                    "lon_min": float(lon_min),
                    "lat_min": float(lat_min),
                    "lon_max": float(lon_max),
                    "lat_max": float(lat_max),
                }
            )

    if not rows:
        raise RuntimeError(
            f"No datacube datasets found for tile={tile} (bbox {lon_min},{lat_min},{lon_max},{lat_max}) "
            f"for products={products}. Likely wrong product names."
        )

    df = pd.DataFrame(rows).drop_duplicates(subset=["date", "product"])
    df = df.sort_values(["date", "product"]).reset_index(drop=True)
    return df



def _finalise(df: pd.DataFrame, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Manifest missing columns: {missing}. Have: {list(df.columns)}")

    out = df.copy()
    out["date"] = out["date"].astype(str)

    # start/end accept YYYY-MM-DD or YYYYMMDD; normalise to YYYYMMDD
    def norm(d: str | None) -> str | None:
        if not d:
            return None
        d = d.strip()
        if "-" in d:
            parts = d.split("-")
            if len(parts) == 3:
                return f"{parts[0]}{parts[1]}{parts[2]}"
        return d

    s = norm(start_date)
    e = norm(end_date)

    if s:
        out = out[out["date"] >= s]
    if e:
        out = out[out["date"] <= e]

    out = out.sort_values(["date", "product"]).reset_index(drop=True)
    return out

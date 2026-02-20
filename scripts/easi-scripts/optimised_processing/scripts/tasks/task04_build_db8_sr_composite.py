from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from lib.s3_io import s3_key_exists, upload_file_to_s3
from lib.cog import to_cog


SR_BANDS = [
    'nbart_blue',
    'nbart_green',
    'nbart_red',
    'nbart_nir',
    'nbart_swir_1',
    'nbart_swir_2',
]


@dataclass(frozen=True)
class Db8Output:
    local_path: Path
    s3_key: str
    date: str
    platform: str
    product: str
    target_epsg: int


def build_db8_sr_to_s3(
    *,
    tile: str,
    date: str,  # YYYYMMDD
    platform: str,
    product: str,
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    target_epsg: int,
    cloud_max: float,
    bucket: str,
    s3_prefix: str,
    work_dir: Path,
    resolution: float = 30.0,
    dask_chunk: int = 2048,
    rebase: bool = False,
    dry_run: bool = False,
) -> Db8Output:
    """Create a 6-band SR stack ("db8") for a single scene date and upload to S3.

    - Loads SR bands + oa_fmask for the given date
    - Picks best time slice by % clear land (oa_fmask == 1)
    - Masks non-clear pixels to nodata
    - Writes GeoTIFF, then converts to COG (lossless)

    Output layout:
      {s3_prefix}/tiles/{tile}/db8/{platform}/{YYYY}/{YYYYMMDD}/lztmre_{tile}_{YYYYMMDD}_db8_{epsg}.tif
    """
    import datacube
    import re
    import rasterio
    from rasterio.transform import Affine

    if callable(product):
        raise TypeError(f"Expected product name string, got callable: {product!r}")


    tile = tile.lower().strip()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    out_dir = f"{s3_prefix.rstrip('/')}/tiles/{tile}/db8/{platform}/{date[:4]}/{date}"
    out_key = f"{out_dir}/lztmre_{tile}_{date}_db8_{int(target_epsg)}.tif"

    local_raw = work_dir / f"{tile}_{date}_db8_raw.tif"
    local_cog = work_dir / f"{tile}_{date}_db8_{int(target_epsg)}.tif"

    if not rebase and s3_key_exists(bucket, out_key):
        return Db8Output(local_path=local_cog, s3_key=out_key, date=date, platform=platform, product=product, target_epsg=int(target_epsg))

    if dry_run:
        print(f"[DRY] DB8 SR {tile} {platform} {date} -> s3://{bucket}/{out_key}")
        return Db8Output(local_path=local_cog, s3_key=out_key, date=date, platform=platform, product=product, target_epsg=int(target_epsg))

    dc = datacube.Datacube(app='optimised_processing_db8')

    t0 = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    time = (t0, t0)

    # Filter datasets to exact tile
    m = re.fullmatch(r"p(\d{3})r(\d{3})", tile)
    if not m:
        raise ValueError(f"Expected tile like p###r###, got: {tile}")
    path = int(m.group(1))
    row = int(m.group(2))
    region_code = f"{path:03d}{row:03d}"

    def only_this_tile(ds) -> bool:
        rc = getattr(getattr(ds, 'metadata', None), 'region_code', None)
        if rc is not None:
            return str(rc) == region_code
        try:
            uri = ds.uri if hasattr(ds, 'uri') else (ds.uris[0] if hasattr(ds, 'uris') and ds.uris else '')
            return f"/{path:03d}/{row:03d}/" in str(uri)
        except Exception:
            return False


    ds = dc.load(
        product=str(product),
        measurements=SR_BANDS + ["oa_fmask"],
        time=time,
        lon=(float(lon_min), float(lon_max)),
        lat=(float(lat_min), float(lat_max)),
        output_crs=f"EPSG:{int(target_epsg)}",
        resolution=(-float(resolution), float(resolution)),
        dask_chunks={"x": int(dask_chunk), "y": int(dask_chunk)},
        dataset_predicate=only_this_tile,
        skip_broken_datasets=True,
    )


    if ds is None or 'time' not in ds.dims or ds.sizes.get('time', 0) == 0:
        raise RuntimeError(f"No data returned by dc.load for tile={tile} product={product} date={date}")

    # Validate readability
    for band in ['oa_fmask'] + SR_BANDS:
        try:
            _ = ds[band].isel(time=0).mean().compute()
        except Exception as e:
            print(f"[SKIP] Broken dataset: {band} cannot be read ({tile} {date}): {e}")
            raise

    LAND_CLEAR_VALUE = 1

    def valid_mask(oa):
        nodata = oa.attrs.get('nodata', None)
        if nodata is None:
            return np.isfinite(oa)
        return (oa != nodata)

    def land_clear_mask(oa):
        v = valid_mask(oa)
        return (oa == LAND_CLEAR_VALUE) & v

    # choose best time slice by clear land%
    oa = ds['oa_fmask']
    v = valid_mask(oa)
    lc = land_clear_mask(oa)
    valid_count = v.sum(dim=('y', 'x'))
    clear_count = lc.sum(dim=('y', 'x'))
    frac = (clear_count / valid_count).where(valid_count > 0)
    frac = frac.compute()
    if bool(frac.isnull().all()):
        raise RuntimeError(f"land-clear% all-NaN for {tile} {date} ({product})")

    frac_filled = frac.fillna(-1.0)
    best_i = int(frac_filled.argmax(dim='time').values)

    clear_mask = land_clear_mask(oa.isel(time=best_i))

    # pull bands
    bands = []
    for b in SR_BANDS:
        bands.append(ds[b].isel(time=best_i).astype('float32'))

    # Apply mask: keep clear land only; set others to nodata
    nodata = np.float32(-9999.0)
    bands = [band.where(clear_mask, other=nodata) for band in bands]

    # compute to numpy
    arrs = [b.compute().values for b in bands]
    stack = np.stack(arrs, axis=0).astype('float32')

    # Grab georef
    crs = ds[SR_BANDS[0]].attrs.get('crs') or ds[SR_BANDS[0]].attrs.get('spatial_ref')
    transform = ds[SR_BANDS[0]].attrs.get('transform')
    if transform is None:
        # datacube sometimes stores affine as tuple
        transform = ds[SR_BANDS[0]].attrs.get('affine')
    if transform is None:
        # build from coords (fallback)
        xs = ds['x'].values
        ys = ds['y'].values
        xres = float(xs[1] - xs[0])
        yres = float(ys[1] - ys[0])
        transform = Affine.translation(xs[0] - xres / 2, ys[0] - yres / 2) * Affine.scale(xres, yres)

    profile = {
        'driver': 'GTiff',
        'height': stack.shape[1],
        'width': stack.shape[2],
        'count': stack.shape[0],
        'dtype': 'float32',
        'crs': crs,
        'transform': transform,
        'nodata': float(nodata),
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512,
        'compress': 'DEFLATE',
        'predictor': 3,
        'BIGTIFF': 'IF_SAFER',
    }

    with rasterio.open(local_raw, 'w', **profile) as dst:
        dst.write(stack)
        dst.update_tags(
            SOFTWARE='optimised_processing',
            PRODUCT=product,
            PLATFORM=platform,
            CLOUD_MAX=str(cloud_max),
        )

    # Convert to COG (keeps values identical; adds overviews)
    to_cog(str(local_raw), str(local_cog), overwrite=True)

    upload_file_to_s3(str(local_cog), bucket=bucket, key=out_key)

    try:
        local_raw.unlink(missing_ok=True)
    except Exception:
        pass

    return Db8Output(local_path=local_cog, s3_key=out_key, date=date, platform=platform, product=product, target_epsg=int(target_epsg))

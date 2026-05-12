from __future__ import annotations

import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds


def ensure_pyarrow():
    # optional helper so errors are clearer when writing parquet manifests
    try:
        import pyarrow  # noqa
    except Exception as e:
        raise RuntimeError(
            "pyarrow is required for parquet manifests. "
            "Install it in this env (conda/pip). "
            f"Original error: {e}"
        )


def _xarray_profile(da, dtype, nodata):
    # assumes da has coords x/y in projected metres
    xs = da["x"].values
    ys = da["y"].values
    width = xs.shape[0]
    height = ys.shape[0]

    left, right = float(xs.min()), float(xs.max())
    bottom, top = float(ys.min()), float(ys.max())

    transform = from_bounds(left, bottom, right, top, width, height)

    # crs is attached by datacube/rioxarray as attribute
    crs = da.attrs.get("crs") or da.attrs.get("spatial_ref")
    if not crs:
        # datacube usually stores it on dataset; da may inherit
        crs = da.rio.crs.to_wkt() if hasattr(da, "rio") and da.rio.crs else None

    if crs is None:
        raise RuntimeError("Cannot determine CRS for output COG (missing da.attrs['crs']).")

    profile = {
        "driver": "GTiff",
        "dtype": dtype,
        "nodata": nodata,
        "width": width,
        "height": height,
        "count": 1,
        "crs": crs,
        "transform": transform,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "DEFLATE",
        "predictor": 2 if dtype in ("float32", "float64") else 1,
        "BIGTIFF": "IF_SAFER",
    }
    return profile


def _write_cog(da, out_path: str, dtype: str, nodata):
    arr = da.data
    # force compute to write (dask -> numpy)
    try:
        arr = da.compute().values
    except Exception:
        arr = da.values

    profile = _xarray_profile(da, dtype=dtype, nodata=nodata)

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(arr.astype(dtype), 1)

        # overviews for COG-ish behaviour
        factors = [2, 4, 8, 16]
        dst.build_overviews(factors, Resampling.nearest if dtype == "uint8" else Resampling.average)
        dst.update_tags(ns="rio_overview", resampling="nearest" if dtype == "uint8" else "average")


def write_cog_float32(da, out_path: str, nodata: float = -9999.0) -> None:
    _write_cog(da, out_path=out_path, dtype="float32", nodata=nodata)


def write_cog_uint8(da, out_path: str, nodata: int = 0) -> None:
    _write_cog(da, out_path=out_path, dtype="uint8", nodata=nodata)


def to_cog(src_path: str, dst_path: str, overwrite: bool = False) -> None:
    """Convert an existing GeoTIFF to a tiled, compressed GeoTIFF with overviews.

    This is a pragmatic "COG-style" writer using rasterio (no external gdal_translate).
    It preserves pixel values (lossless compression) and adds internal overviews.
    """
    import os
    from rasterio.shutil import copy

    if (not overwrite) and os.path.exists(dst_path):
        return

    with rasterio.open(src_path) as src:
        profile = src.profile.copy()
        dtype_str = str(profile.get('dtype', '')).lower()
        is_float = dtype_str.startswith('float')
        # NOTE: Some GIS tools (notably ArcGIS) can behave poorly with
        # DEFLATE+predictor=2 on multi-band uint8 rasters. DLJ is 4-band uint8,
        # so prefer predictor=1 there for maximum compatibility.
        if is_float:
            predictor = 3
        else:
            predictor = 1 if int(getattr(src, 'count', 1)) > 1 else 2
        profile.update(
            driver='GTiff',
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress='DEFLATE',
            predictor=predictor,
            BIGTIFF='IF_SAFER',
        )

        copy(src, dst_path, **profile)

    # add overviews
    with rasterio.open(dst_path, 'r+') as dst:
        factors = [2, 4, 8, 16]
        dst.build_overviews(factors, Resampling.nearest)
        dst.update_tags(ns='rio_overview', resampling='nearest')

from __future__ import annotations

import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds


def ensure_pyarrow():
    # small helper to make sure pyarrow is installed
    # this is mostly so parquet write errors are clearer
    try:
        import pyarrow  # noqa
    except Exception as e:
        # fail early with a more useful message
        raise RuntimeError(
            "pyarrow is required for parquet manifests. "
            "Install it in this env (conda/pip). "
            f"Original error: {e}"
        )


def _xarray_profile(da, dtype, nodata):
    # assumes da has x/y coords in projected metres
    xs = da["x"].values
    ys = da["y"].values

    # work out raster size from coords
    width = xs.shape[0]
    height = ys.shape[0]

    # get bounds from the coord values
    left, right = float(xs.min()), float(xs.max())
    bottom, top = float(ys.min()), float(ys.max())

    # build affine transform from bounds
    transform = from_bounds(left, bottom, right, top, width, height)

    # try to get CRS from attributes (datacube usually sets this)
    crs = da.attrs.get("crs") or da.attrs.get("spatial_ref")

    # fallback: check rioxarray if available
    if not crs:
        # sometimes CRS lives on the rio accessor
        crs = da.rio.crs.to_wkt() if hasattr(da, "rio") and da.rio.crs else None

    # if we still dont have a CRS, we cant write a proper COG
    if crs is None:
        raise RuntimeError("Cannot determine CRS for output COG (missing da.attrs['crs']).")

    # basic rasterio profile for writing the file
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
        # predictor 2 helps with floats, otherwise just use 1
        "predictor": 2 if dtype in ("float32", "float64") else 1,
        "BIGTIFF": "IF_SAFER",
    }

    return profile




def _write_cog(da, out_path: str, dtype: str, nodata):
    # grab the data out of the xarray thing
    arr = da.data

    # force compute so we actually have numpy (dask sometimes)
    try:
        arr = da.compute().values
    except Exception:
        # fallback if compute doesnt work
        arr = da.values

    # build rasterio profile from coords/attrs
    profile = _xarray_profile(da, dtype=dtype, nodata=nodata)

    # write geotiff out
    with rasterio.open(out_path, "w", **profile) as dst:
        # write first band only
        dst.write(arr.astype(dtype), 1)

        # add overviews so its more COG-like (not sure if this is perfect but ok)
        factors = [2, 4, 8, 16]
        dst.build_overviews(
            factors,
            Resampling.nearest if dtype == "uint8" else Resampling.average
        )

        # tag overview resampling method (rio expects this sometimes)
        dst.update_tags(
            ns="rio_overview",
            resampling="nearest" if dtype == "uint8" else "average"
        )


def write_cog_float32(da, out_path: str, nodata: float = -9999.0) -> None:
    # wrapper for float outputs
    _write_cog(da, out_path=out_path, dtype="float32", nodata=nodata)


def write_cog_uint8(da, out_path: str, nodata: int = 0) -> None:
    # wrapper for uint8 outputs (mask)
    _write_cog(da, out_path=out_path, dtype="uint8", nodata=nodata)
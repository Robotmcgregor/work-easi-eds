from __future__ import annotations
import math
from osgeo import gdal, osr
import numpy as np

gdal.UseExceptions()

def derive_target_epsg_gda94_mga(ds: gdal.Dataset) -> int:
    """
    Derive a GDA94 MGA zone EPSG (283xx) from raster centre longitude.

    MGA zones:
      zone = floor((lon + 180)/6) + 1
      EPSG = 28300 + zone  (GDA94 / MGA zone)
    """
    gt = ds.GetGeoTransform()
    xsize = ds.RasterXSize
    ysize = ds.RasterYSize

    # centre pixel in source CRS
    cx = gt[0] + (xsize * gt[1]) / 2.0 + (ysize * gt[2]) / 2.0
    cy = gt[3] + (xsize * gt[4]) / 2.0 + (ysize * gt[5]) / 2.0

    src_srs = osr.SpatialReference()
    src_srs.ImportFromWkt(ds.GetProjection())

    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)

    ct = osr.CoordinateTransformation(src_srs, wgs84)
    lon, lat, _ = ct.TransformPoint(cx, cy)

    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    epsg = 28300 + zone
    return epsg


def warp_to_epsg(
    src: str,
    dst: str,
    epsg: int,
    res: float,
    match: str | None = None,
    nearest: bool = False,
) -> None:
    """
    Reproject & resample to a target EPSG at specified resolution.

    If match is provided, we snap output grid to match that raster (same extent/grid).
    """
    warp_opts = {
        "dstSRS": f"EPSG:{epsg}",
        "xRes": res,
        "yRes": res,
        "resampleAlg": "near" if nearest else "bilinear",
        "multithread": True,
        "format": "GTiff",
        "creationOptions": ["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
    }

    if match:
        ref = gdal.Open(match, gdal.GA_ReadOnly)
        gt = ref.GetGeoTransform()
        proj = ref.GetProjection()
        xsize = ref.RasterXSize
        ysize = ref.RasterYSize
        # derive bounds
        minx = gt[0]
        maxy = gt[3]
        maxx = minx + xsize * gt[1]
        miny = maxy + ysize * gt[5]
        warp_opts["outputBounds"] = (minx, miny, maxx, maxy)
        ref = None

    gdal.Warp(destNameOrDestDS=dst, srcDSOrSrcDSTab=src, **warp_opts)


# scripts/lib/geo.py

# FMASK_CLEAR_VALUES = {1}  # same as legacy downloader

def compute_ndvi(red, nir, clear_mask):
    clear = (clear_mask == 1)
    denom = nir + red
    valid = clear & np.isfinite(red) & np.isfinite(nir) & (denom != 0)

    ndvi = np.full(red.shape, -9999.0, dtype=np.float32)
    ndvi[valid] = (nir[valid] - red[valid]) / denom[valid]
    return ndvi




def write_cog_from_array(ref_path: str, out_path: str, array: np.ndarray, nodata: float, dtype) -> None:
    """
    Write a single-band GeoTIFF using ref georeferencing, then build overviews.
    This is a “COG-style” output (tiled + compressed + overviews).

    Note: strict COG compliance can be validated later; this is a strong practical default.
    """
    ref = gdal.Open(ref_path, gdal.GA_ReadOnly)
    gt = ref.GetGeoTransform()
    proj = ref.GetProjection()
    xsize = ref.RasterXSize
    ysize = ref.RasterYSize

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(
        out_path,
        xsize,
        ysize,
        1,
        dtype,
        options=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER", "NUM_THREADS=ALL_CPUS"],
    )
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)

    b = ds.GetRasterBand(1)
    b.WriteArray(array)
    b.SetNoDataValue(nodata)
    b.FlushCache()

    # Overviews help cloud performance
    ds.BuildOverviews("NEAREST", [2, 4, 8, 16, 32])
    ds.FlushCache()
    ds = None
    ref = None

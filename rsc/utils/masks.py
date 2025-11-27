"""
Shim for rsc.utils.masks used by the QLD script.
Provides mask constants and a simple Masker that treats non-zero as masked.
Also provides getAvailableMaskname which creates empty masks if missing.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

MT_CLOUD = 1
MT_CLOUDSHADOW = 2
MT_WATERNDX = 3
MT_TOPOINCIDENCE = 4
MT_TOPOCASTSHADOW = 5
MT_SNOW = 6


class Masker:
    def __init__(self, filename: str):
        self.filename = filename

    def mask(self, arr):
        # Non-zero means masked
        return arr != 0

    def isNull(self, arr):
        # Nulls are zero in our generated masks
        return arr == 0


def _mask_suffix(mt: int) -> str:
    return {
        MT_CLOUD: "cloud",
        MT_CLOUDSHADOW: "cloudshadow",
        MT_WATERNDX: "water",
        MT_TOPOINCIDENCE: "topoinc",
        MT_TOPOCASTSHADOW: "topocast",
        MT_SNOW: "snow",
    }.get(mt, f"mt{mt}")


def getAvailableMaskname(img_filename: str, masktype: int) -> Optional[str]:
    """Return a mask filename for the given image. If it does not exist, create an empty mask with same georeference/size.
    """
    from osgeo import gdal
    from rsc.utils.metadb import stdProjFilename
    img_path = stdProjFilename(img_filename)
    base = Path(img_path)
    suf = _mask_suffix(masktype)
    mask_name = base.with_suffix("")
    mask_name = Path(str(mask_name) + f"_{suf}.tif")
    if mask_name.exists():
        return str(mask_name)
    ds = gdal.Open(str(img_path), gdal.GA_ReadOnly)
    if ds is None:
        return None
    xsize = ds.RasterXSize
    ysize = ds.RasterYSize
    geotrans = ds.GetGeoTransform(can_return_null=True)
    proj = ds.GetProjection()
    drv = gdal.GetDriverByName("GTiff")
    out = drv.Create(str(mask_name), xsize, ysize, 1, gdal.GDT_Byte, options=["COMPRESS=LZW", "TILED=YES"])
    if out is None:
        return None
    if geotrans:
        out.SetGeoTransform(geotrans)
    if proj:
        out.SetProjection(proj)
    band = out.GetRasterBand(1)
    band.Fill(0)
    band.SetNoDataValue(0)
    band.FlushCache()
    out.FlushCache()
    del out
    del ds
    return str(mask_name)

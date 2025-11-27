#!/usr/bin/env python
"""Stub implementation of qv_applystdmasks.py for legacy change script compatibility.

The legacy script invokes this to apply standard masks (cloud, shadow, water, etc.) and output a
"masked" FPC image prior to normalisation. In this adapted environment we either have empty mask
shims or choose to ignore masking. This stub simply copies the input raster to the output path.

Args:
  --infile <path>  Original dc4 image (single band Byte)
  --outfile <path> Target masked image filename (ENVI .img expected)
  --omitmask <name> (ignored; accepted multiple times for interface compatibility)

Exit code 0 on success, non-zero on failure.
"""
from __future__ import annotations

import argparse
import sys
from osgeo import gdal


def copy_raster(src: str, dst: str) -> None:
    ds = gdal.Open(src, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open {src}")
    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    geotrans, proj = ds.GetGeoTransform(can_return_null=True), ds.GetProjection()
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()
    drv = gdal.GetDriverByName('ENVI')
    out = drv.Create(dst, xsize, ysize, 1, band.DataType)
    if geotrans:
        out.SetGeoTransform(geotrans)
    if proj:
        out.SetProjection(proj)
    out.GetRasterBand(1).WriteArray(arr)
    out.GetRasterBand(1).SetNoDataValue(band.GetNoDataValue() or 0)
    out.FlushCache()
    out = None
    ds = None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stub mask application (no-op copy)")
    ap.add_argument('--infile', required=True)
    ap.add_argument('--outfile', required=True)
    ap.add_argument('--omitmask', action='append', help='Ignored; present for interface compatibility')
    args = ap.parse_args(argv)
    try:
        copy_raster(args.infile, args.outfile)
        print(f"[stub-mask] Copied {args.infile} -> {args.outfile}")
        return 0
    except Exception as e:
        print(f"[stub-mask] ERROR: {e}")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
#!/usr/bin/env python
"""
Compat implementation of qv_applystdmasks.py used by the QLD script.
Applies standard masks to the input FPC and writes the masked output.
In compatibility mode we simply copy the input to the output (no-op masking),
as masks are applied downstream in doChangeModel via Masker.
"""
from __future__ import annotations

import argparse
from osgeo import gdal


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apply standard masks (compat no-op)")
    ap.add_argument("--infile", required=True)
    ap.add_argument("--outfile", required=True)
    ap.add_argument("--omitmask", action="append", help="Mask type to omit", default=[])
    args = ap.parse_args(argv)

    src = gdal.Open(args.infile, gdal.GA_ReadOnly)
    if src is None:
        raise SystemExit(f"Cannot open input: {args.infile}")
    drv = gdal.GetDriverByName("ENVI")
    out = drv.CreateCopy(args.outfile, src, strict=0)
    if out is None:
        raise SystemExit(f"Failed to write output: {args.outfile}")
    out.FlushCache()
    del out
    del src
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

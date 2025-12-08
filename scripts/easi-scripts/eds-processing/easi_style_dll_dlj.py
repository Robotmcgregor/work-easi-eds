#!/usr/bin/env python
"""
Apply styling to DLL/DLJ outputs:

- DLL: apply a categorical colour table (simple default here).
- DLJ: set band descriptions on the 4 bands.

This script is intentionally self-contained and works with the EASI
compat outputs created by easi_eds_master_processing_pipeline.py.
"""

import argparse
from osgeo import gdal


def style_dll(dll_path: str) -> None:
    """Apply a simple colour table to the DLL raster."""
    ds = gdal.Open(dll_path, gdal.GA_Update)
    if ds is None:
        raise RuntimeError(f"Cannot open DLL: {dll_path}")

    band = ds.GetRasterBand(1)
    ct = gdal.ColorTable()

    # Basic scheme:
    # 0   = nodata (transparent/black)
    # 1–33  = greys
    # 34–39 = stronger colours (change classes)
    # >39   = fallback greys
    ct.SetColorEntry(0, (0, 0, 0, 0))  # nodata

    # Soft grey ramp for 1–33
    for i in range(1, 34):
        v = int(255 * i / 40)
        ct.SetColorEntry(i, (v, v, v, 255))

    # Stronger colours for standard SLATS-style thresholds (34–39)
    palette = {
        34: (255, 255, 0, 255),   # yellow
        35: (255, 200, 0, 255),   # orange-yellow
        36: (255, 150, 0, 255),   # orange
        37: (255, 100, 0, 255),   # deep orange
        38: (255, 0, 0, 255),     # red
        39: (180, 0, 0, 255),     # dark red
    }
    for k, rgba in palette.items():
        ct.SetColorEntry(k, rgba)

    # Fallback greys for 40–255
    for i in range(40, 256):
        v = int(255 * i / 255)
        ct.SetColorEntry(i, (v, v, v, 255))

    band.SetRasterColorTable(ct)
    band.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    ds.FlushCache()
    del ds


def style_dlj(dlj_path: str) -> None:
    """Set band names on the DLJ raster (4-band change index)."""
    ds = gdal.Open(dlj_path, gdal.GA_Update)
    if ds is None:
        raise RuntimeError(f"Cannot open DLJ: {dlj_path}")

    names = [
        "mean_change",           # band 1
        "spectral_test",         # band 2
        "combined_index",        # band 3
        "clearing_probability",  # band 4
    ]

    for i, name in enumerate(names, start=1):
        if i <= ds.RasterCount:
            band = ds.GetRasterBand(i)
            band.SetDescription(name)

    ds.FlushCache()
    del ds


def main() -> int:
    ap = argparse.ArgumentParser(description="Style DLL/DLJ outputs")
    ap.add_argument("--dll", required=True, help="Path to DLL raster (lztmre_*_dllmz.img)")
    ap.add_argument("--dlj", required=True, help="Path to DLJ raster (lztmre_*_dljmz.img)")
    args = ap.parse_args()

    style_dll(args.dll)
    style_dlj(args.dlj)
    print(f"Styled DLL: {args.dll}")
    print(f"Styled DLJ: {args.dlj}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""
Apply a legacy-like color table to a dllmz classification raster and set band names on dljmz.

Usage:
  python scripts/style_dll_dlj.py --dll path\to\*_dllmz.img --dlj path\to\*_dljmz.img

This sets a palette similar to the SLATS clearing colours:
  0  = transparent (nodata)
  10 = no clearing (light grey)
   3 = FPC-only clearing (cyan)
  34..39 = increasing clearing strength (yellow -> orange -> reds -> magenta -> purple)

Also sets dlj band names to: spectralIndex, sTest, combinedIndex, clearingProb.
"""
from __future__ import annotations

import argparse
from osgeo import gdal


def apply_dll_palette(dll_path: str) -> None:
    ds = gdal.Open(dll_path, gdal.GA_Update)
    if ds is None:
        raise RuntimeError(f"Cannot open {dll_path} for update")
    b = ds.GetRasterBand(1)
    ct = gdal.ColorTable()
    # Defaults: everything to transparent black
    for i in range(0, 256):
        ct.SetColorEntry(i, (0, 0, 0, 0))
    # NoData 0 transparent
    # 10 no clearing: light grey
    ct.SetColorEntry(10, (200, 200, 200, 255))
    # 3 FPC-only: cyan
    ct.SetColorEntry(3, (0, 200, 200, 255))
    # 34..39 gradient
    palette = {
        34: (255, 255, 0, 255),  # yellow
        35: (255, 200, 0, 255),  # yellow-orange
        36: (255, 150, 0, 255),  # orange
        37: (255, 100, 0, 255),  # red-orange
        38: (255, 0, 0, 255),  # red
        39: (200, 0, 200, 255),  # purple
    }
    for k, rgba in palette.items():
        ct.SetColorEntry(k, rgba)

    b.SetColorTable(ct)
    b.SetColorInterpretation(gdal.GCI_PaletteIndex)
    # Keep nodata at 0
    if b.GetNoDataValue() is None:
        b.SetNoDataValue(0)
    ds.FlushCache()
    ds = None


def set_dlj_band_names(dlj_path: str) -> None:
    ds = gdal.Open(dlj_path, gdal.GA_Update)
    if ds is None:
        raise RuntimeError(f"Cannot open {dlj_path} for update")
    names = ["spectralIndex", "sTest", "combinedIndex", "clearingProb"]
    for i, name in enumerate(names, start=1):
        b = ds.GetRasterBand(i)
        b.SetDescription(name)
    ds.FlushCache()
    ds = None


def main():
    ap = argparse.ArgumentParser(description="Style dll/dlj outputs for QGIS")
    ap.add_argument("--dll", required=True, help="Path to *_dllmz.img")
    ap.add_argument("--dlj", required=True, help="Path to *_dljmz.img")
    args = ap.parse_args()

    apply_dll_palette(args.dll)
    set_dlj_band_names(args.dlj)
    print("Styled:", args.dll)
    print("        ", args.dlj)


if __name__ == "__main__":
    main()

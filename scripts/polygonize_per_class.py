#!/usr/bin/env python
"""
Polygonize a classification raster (dllmz) into per-class Shapefiles with distinct names.

- Derives scene and era from the input filename like: lztmre_<scene>_<era>_dllmz.img
- For each requested class, creates <scene>_<era>_class_<val>.shp in the output directory
- Skips classes with 0 pixels

Usage:
  python scripts/polygonize_per_class.py \
    --dll data/compat/files/p089r080/lztmre_p089r080_d2023102420240831_dllmz.img \
    --classes 3 34 35 36 37 38 39 \
    --out-dir data/compat/files/p089r080/shp_d20231024_20240831
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()


def parse_scene_era(path: str) -> tuple[str, str]:
    base = os.path.basename(path)
    m = re.match(
        r"lztmre_(p\d{3}r\d{3})_(d\d{8}\d{8}|e\d+)_dllmz\.img$",
        base,
        flags=re.IGNORECASE,
    )
    if not m:
        # fallback generic
        stem = os.path.splitext(base)[0]
        return ("scene", stem)
    return m.group(1).lower(), m.group(2).lower()


def _get_pixel_area_m2(
    gt: Tuple[float, float, float, float, float, float],
) -> Optional[float]:
    """Return pixel area in m^2 if geotransform suggests planar meters (no rotation)."""
    px_w = abs(gt[1])
    px_h = abs(gt[5])
    if px_w == 0 or px_h == 0:
        return None
    return px_w * px_h


def _needs_reproject_for_area(srs: osr.SpatialReference) -> bool:
    # If geographic (lat/long) we need reprojection for accurate area.
    return srs.IsGeographic() == 1


def polygonize_class(
    arr: np.ndarray, c: int, gt, wkt, out_path: Path, min_ha: Optional[float] = None
) -> tuple[int, int]:
    """Polygonize a single class value.

    Returns (kept_features, original_features).
    """
    xsize = arr.shape[1]
    ysize = arr.shape[0]
    mask = (arr == c).astype(np.uint8)
    if mask.sum() == 0:
        return 0, 0

    mem = gdal.GetDriverByName("MEM")
    ds_val = mem.Create("", xsize, ysize, 1, gdal.GDT_Byte)
    ds_val.SetGeoTransform(gt)
    ds_val.SetProjection(wkt)
    band = ds_val.GetRasterBand(1)
    band.WriteArray(mask * c)

    ds_msk = mem.Create("", xsize, ysize, 1, gdal.GDT_Byte)
    ds_msk.GetRasterBand(1).WriteArray(mask)

    # Vectorize into memory first
    vdrv_mem = ogr.GetDriverByName("Memory")
    mem_ds = vdrv_mem.CreateDataSource("")
    srs = osr.SpatialReference()
    srs.ImportFromWkt(wkt)
    mem_lyr = mem_ds.CreateLayer("tmp", srs=srs, geom_type=ogr.wkbPolygon)
    mem_lyr.CreateField(ogr.FieldDefn("class", ogr.OFTInteger))
    gdal.Polygonize(
        ds_val.GetRasterBand(1), ds_msk.GetRasterBand(1), mem_lyr, 0, [], callback=None
    )
    orig_count = mem_lyr.GetFeatureCount()

    # Prepare output
    drv = ogr.GetDriverByName("ESRI Shapefile")
    if out_path.exists():
        drv.DeleteDataSource(str(out_path))
    out_ds = drv.CreateDataSource(str(out_path))
    out_lyr = out_ds.CreateLayer("polygons", srs=srs, geom_type=ogr.wkbPolygon)
    out_lyr.CreateField(ogr.FieldDefn("class", ogr.OFTInteger))
    out_lyr.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))
    out_lyr.CreateField(ogr.FieldDefn("area_ha", ogr.OFTReal))

    # Area computation setup
    pixel_area = _get_pixel_area_m2(gt)
    needs_reproj = _needs_reproject_for_area(srs)
    reproj_ct = None
    if needs_reproj:
        # Use Australian Albers (EPSG:3577) for area measurement if geographic.
        target = osr.SpatialReference()
        target.ImportFromEPSG(3577)
        reproj_ct = osr.CoordinateTransformation(srs, target)

    kept = 0
    # Iterate features
    mem_lyr.ResetReading()
    for feat in mem_lyr:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        # Compute area
        if needs_reproj:
            geom_clone = geom.Clone()
            geom_clone.Transform(reproj_ct)
            area_m2 = geom_clone.GetArea()
        else:
            area_m2 = geom.GetArea()
            # Fallback if area 0 and pixel_area known (very small polygons?)
            if area_m2 == 0 and pixel_area is not None:
                area_m2 = pixel_area
        area_ha = area_m2 / 10000.0
        if min_ha is not None and area_ha < min_ha:
            continue
        # Write filtered feature
        out_feat = ogr.Feature(out_lyr.GetLayerDefn())
        out_feat.SetField("class", c)
        out_feat.SetField("area_m2", float(area_m2))
        out_feat.SetField("area_ha", float(area_ha))
        out_feat.SetGeometry(geom.Clone())
        out_lyr.CreateFeature(out_feat)
        out_feat = None
        kept += 1

    out_ds = None
    ds_val = None
    ds_msk = None
    mem_ds = None
    return kept, orig_count


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Polygonize dllmz per class to distinct shapefiles (optionally apply min area filter)."
    )
    ap.add_argument("--dll", required=True, help="Path to *_dllmz.img")
    ap.add_argument(
        "--classes",
        nargs="*",
        type=int,
        help="Class values to extract. Default: all >0 in raster",
    )
    ap.add_argument("--out-dir", required=True, help="Output directory for shapefiles")
    ap.add_argument(
        "--min-ha",
        type=float,
        default=None,
        help="Minimum polygon area (hectares) to keep. Filters small noisy polygons.",
    )
    args = ap.parse_args(argv)

    print(f"[INFO] Opening raster: {args.dll}")
    ds = gdal.Open(args.dll, gdal.GA_ReadOnly)
    if ds is None:
        raise SystemExit(f"Cannot open {args.dll}")
    band = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform()
    wkt = ds.GetProjection()

    print("[INFO] Reading full raster array ...")
    arr = band.ReadAsArray()
    uniq = np.unique(arr)
    print(f"[INFO] Unique class values in raster: {uniq.tolist()}")

    if args.classes:
        classes = [c for c in args.classes if c in uniq and c != 0]
        print(f"[INFO] Restricting to classes present: {classes}")
    else:
        classes = [int(v) for v in uniq.tolist() if int(v) != 0]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene, era = parse_scene_era(args.dll)
    total = 0
    for c in classes:
        shp_name = f"{scene}_{era}_class_{c}.shp"
        out_path = out_dir / shp_name
        print(f"[INFO] Polygonizing class {c} (min_ha={args.min_ha}) -> {out_path}")
        kept, orig = polygonize_class(arr, c, gt, wkt, out_path, min_ha=args.min_ha)
        print(
            f"[OK] {shp_name}: {kept} features kept (original {orig}, removed {orig - kept})"
        )
        total += kept

    print(
        f"[DONE] Wrote shapefiles for {len(classes)} classes to: {out_dir}. Total kept features: {total}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

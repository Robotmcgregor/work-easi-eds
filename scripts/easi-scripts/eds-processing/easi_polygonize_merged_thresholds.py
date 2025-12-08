#!/usr/bin/env python
"""Aggregate clearing classes into threshold-based merged polygons with min-area filtering.

Rules (>= threshold semantics):
  threshold 34 -> classes 34,35,36,37,38,39
  threshold 35 -> classes 35,36,37,38,39
  ...
  threshold 39 -> class 39 only

Outputs one shapefile per threshold with area attributes and optional min-ha filter.

Usage:
  python scripts/polygonize_merged_thresholds.py \
    --dll data/compat/files/p089r080/lztmre_p089r080_d2023102420240831_dllmz.img \
    --thresholds 34 35 36 37 38 39 \
    --min-ha 1 \
    --out-dir data/compat/files/p089r080/shp_d20231024_20240831_merged_min1ha
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
    m = re.match(r"lztmre_(p\d{3}r\d{3})_(d\d{8}\d{8}|e\d+)_dllmz\.img$", base, flags=re.IGNORECASE)
    if not m:
        stem = os.path.splitext(base)[0]
        return ("scene", stem)
    return m.group(1).lower(), m.group(2).lower()


def _get_pixel_area_m2(gt: Tuple[float, float, float, float, float, float]) -> Optional[float]:
    px_w = abs(gt[1])
    px_h = abs(gt[5])
    if px_w == 0 or px_h == 0:
        return None
    return px_w * px_h


def _needs_reproject_for_area(srs: osr.SpatialReference) -> bool:
    return srs.IsGeographic() == 1


def polygonize_mask(mask: np.ndarray, value_mask: np.ndarray, gt, wkt: str, out_path: Path, min_ha: Optional[float]) -> tuple[int, int]:
    # value_mask holds original class values (for potential future attributes) but we only keep polygons as a whole.
    if mask.sum() == 0:
        return 0, 0
    ysize, xsize = mask.shape
    mem = gdal.GetDriverByName('MEM')
    ds_val = mem.Create('', xsize, ysize, 1, gdal.GDT_Int16)
    ds_val.SetGeoTransform(gt)
    ds_val.SetProjection(wkt)
    ds_val.GetRasterBand(1).WriteArray(value_mask)

    ds_msk = mem.Create('', xsize, ysize, 1, gdal.GDT_Byte)
    ds_msk.GetRasterBand(1).WriteArray(mask.astype(np.uint8))

    vdrv_mem = ogr.GetDriverByName('Memory')
    mem_ds = vdrv_mem.CreateDataSource('')
    srs = osr.SpatialReference(); srs.ImportFromWkt(wkt)
    mem_lyr = mem_ds.CreateLayer('tmp', srs=srs, geom_type=ogr.wkbPolygon)
    mem_lyr.CreateField(ogr.FieldDefn('dummy', ogr.OFTInteger))
    gdal.Polygonize(ds_val.GetRasterBand(1), ds_msk.GetRasterBand(1), mem_lyr, 0, [], callback=None)
    orig = mem_lyr.GetFeatureCount()

    drv = ogr.GetDriverByName('ESRI Shapefile')
    if out_path.exists():
        drv.DeleteDataSource(str(out_path))
    out_ds = drv.CreateDataSource(str(out_path))
    out_lyr = out_ds.CreateLayer('polygons', srs=srs, geom_type=ogr.wkbPolygon)
    out_lyr.CreateField(ogr.FieldDefn('thr', ogr.OFTInteger))
    out_lyr.CreateField(ogr.FieldDefn('area_m2', ogr.OFTReal))
    out_lyr.CreateField(ogr.FieldDefn('area_ha', ogr.OFTReal))

    pixel_area = _get_pixel_area_m2(gt)
    needs_reproj = _needs_reproject_for_area(srs)
    reproj_ct = None
    if needs_reproj:
        target = osr.SpatialReference(); target.ImportFromEPSG(3577)
        reproj_ct = osr.CoordinateTransformation(srs, target)

    kept = 0
    mem_lyr.ResetReading()
    for feat in mem_lyr:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        if needs_reproj:
            g2 = geom.Clone(); g2.Transform(reproj_ct); area_m2 = g2.GetArea()
        else:
            area_m2 = geom.GetArea()
            if area_m2 == 0 and pixel_area is not None:
                area_m2 = pixel_area
        area_ha = area_m2 / 10000.0
        if min_ha is not None and area_ha < min_ha:
            continue
        out_feat = ogr.Feature(out_lyr.GetLayerDefn())
        out_feat.SetField('thr', int(out_path.stem.split('_')[-1]))
        out_feat.SetField('area_m2', float(area_m2))
        out_feat.SetField('area_ha', float(area_ha))
        out_feat.SetGeometry(geom.Clone())
        out_lyr.CreateFeature(out_feat)
        out_feat = None
        kept += 1

    out_ds = None
    mem_ds = None
    ds_val = None
    ds_msk = None
    return kept, orig


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Create merged threshold clearing shapefiles (>= threshold) with min-area filtering.')
    ap.add_argument('--dll', required=True, help='Path to *_dllmz.img classification raster')
    ap.add_argument('--thresholds', nargs='*', type=int, default=[34,35,36,37,38,39], help='Threshold base classes to aggregate (default 34..39)')
    ap.add_argument('--min-ha', type=float, default=1.0, help='Minimum polygon area (hectares) to keep (default 1)')
    ap.add_argument('--out-dir', required=True, help='Output directory for merged shapefiles')
    args = ap.parse_args(argv)

    print(f'[INFO] Opening raster {args.dll}')
    ds = gdal.Open(args.dll, gdal.GA_ReadOnly)
    if ds is None:
        raise SystemExit(f'Cannot open raster: {args.dll}')
    arr = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform(); wkt = ds.GetProjection()
    uniq = np.unique(arr)
    print(f'[INFO] Unique classes: {uniq.tolist()}')

    scene, era = parse_scene_era(args.dll)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)

    thresholds = sorted({t for t in args.thresholds if t in uniq})
    print(f'[INFO] Will produce merged polygons for thresholds: {thresholds} (min_ha={args.min_ha})')

    total_kept = 0
    for t in thresholds:
        # Build mask of classes >= t, but ensure background (e.g. 10 or 0) excluded.
        mask = (arr >= t) & (arr <= 39)  # assuming 39 highest clearing class
        if t == 39:
            mask = (arr == 39)
        if mask.sum() == 0:
            print(f'[SKIP] Threshold {t}: no pixels.')
            continue
        value_mask = np.where(mask, arr, 0)
        shp_name = f'{scene}_{era}_thr_{t}.shp'
        out_path = out_dir / shp_name
        print(f'[INFO] Polygonizing threshold {t} -> {out_path}')
        kept, orig = polygonize_mask(mask.astype(np.uint8), value_mask.astype(np.int16), gt, wkt, out_path, args.min_ha)
        print(f'[OK] {shp_name}: kept {kept} (original {orig}, removed {orig - kept})')
        total_kept += kept

    print(f'[DONE] Merged threshold shapefiles written to {out_dir}. Total kept features across thresholds: {total_kept}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

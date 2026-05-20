#!/usr/bin/env python
"""
Export clearing classes from a dllmz raster to vector polygons.

Defaults:
- Writes a GeoPackage layer with all classes present and an integer field 'class'.
- Optionally filter to a subset of classes (e.g., 34 35 36 37 38 39 3).
- Optionally write per-class Shapefiles instead of a single GeoPackage.

Examples:
  # Single GeoPackage with only clearing classes 34-39 and 3
  python scripts/export_clearing_vectors.py \
    --dll data/compat/files/p089r080/lztmre_p089r080_d2023102420240831_dllmz.img \
    --classes 34 35 36 37 38 39 3 \
    --out C:/Users/DCCEEW/code/eds/data/compat/files/p089r080/dll_clearing.gpkg

  # Per-class Shapefiles under out-dir
  python scripts/export_clearing_vectors.py \
    --dll data/compat/files/p089r080/lztmre_p089r080_d2023102420240831_dllmz.img \
    --classes 34 35 36 37 38 39 3 \
    --per-class-shapefiles --out-dir C:/tmp/clearing_shp
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Optional

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
import numpy as np


def polygonize_to_layer(
    src_band: gdal.Band, srs_wkt: str, dst_ds: ogr.DataSource, layer_name: str
) -> ogr.Layer:
    # Create layer
    srs = osr.SpatialReference()
    if srs_wkt:
        srs.ImportFromWkt(srs_wkt)
    lyr = dst_ds.CreateLayer(layer_name, srs=srs, geom_type=ogr.wkbPolygon)
    fld = ogr.FieldDefn("class", ogr.OFTInteger)
    lyr.CreateField(fld)
    # Polygonize: output field index 0 corresponds to 'class'
    gdal.Polygonize(src_band, None, lyr, 0, [], callback=None)
    return lyr


def filter_layer_inplace(lyr: ogr.Layer, keep_values: List[int]) -> None:
    keep_set = set(keep_values)
    lyr.ResetReading()
    to_delete = []
    for feat in lyr:
        val = feat.GetField("class")
        if val not in keep_set:
            to_delete.append(feat.GetFID())
    for fid in to_delete:
        lyr.DeleteFeature(fid)
    lyr.SyncToDisk()


def export_per_class_shapefiles(
    src_lyr: ogr.Layer, out_dir: Path, classes: List[int]
) -> None:
    drv = ogr.GetDriverByName("ESRI Shapefile")
    for c in classes:
        out_path = out_dir / f"class_{c}.shp"
        if out_path.exists():
            drv.DeleteDataSource(str(out_path))
        ds = drv.CreateDataSource(str(out_path))
        dst_lyr = ds.CreateLayer(
            "polygons", srs=src_lyr.GetSpatialRef(), geom_type=ogr.wkbPolygon
        )
        fld = ogr.FieldDefn("class", ogr.OFTInteger)
        dst_lyr.CreateField(fld)
        src_lyr.SetAttributeFilter(f"class = {c}")
        for feat in src_lyr:
            dst_feat = ogr.Feature(dst_lyr.GetLayerDefn())
            dst_feat.SetField("class", c)
            dst_feat.SetGeometry(feat.GetGeometryRef().Clone())
            dst_lyr.CreateFeature(dst_feat)
        src_lyr.SetAttributeFilter(None)
        ds = None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export dllmz clearing classes to vector")
    ap.add_argument("--dll", required=True, help="Path to *_dllmz.img")
    ap.add_argument(
        "--classes", nargs="*", type=int, help="Class values to keep (default: all)"
    )
    ap.add_argument("--out", help="Output GPKG path (single layer)")
    ap.add_argument("--out-dir", help="Output directory for per-class Shapefiles")
    ap.add_argument(
        "--per-class-shapefiles",
        action="store_true",
        help="Write one Shapefile per class (requires --out-dir)",
    )
    args = ap.parse_args(argv)

    if args.per_class_shapefiles and not args.out_dir:
        raise SystemExit("--per-class-shapefiles requires --out-dir")
    if not args.per_class_shapefiles and not args.out:
        raise SystemExit(
            "Provide --out for single GeoPackage output, or use --per-class-shapefiles with --out-dir"
        )

    print(f"[INFO] Opening raster: {args.dll}")
    ds = gdal.Open(args.dll, gdal.GA_ReadOnly)
    if ds is None:
        raise SystemExit(f"Cannot open {args.dll}")
    band = ds.GetRasterBand(1)
    srs_wkt = ds.GetProjection()
    arr_preview = band.ReadAsArray(0, 0, min(500, band.XSize), min(500, band.YSize))
    uniq = np.unique(arr_preview)
    print(f"[DEBUG] Preview unique values (<=500x500 window): {uniq.tolist()}")
    full_uniqs = np.unique(band.ReadAsArray())
    print(
        f"[DEBUG] Full unique class list ({len(full_uniqs)}): {full_uniqs.tolist()[:50]}{'...' if len(full_uniqs)>50 else ''}"
    )
    if args.classes:
        print(f"[INFO] Requested classes: {args.classes}")

    if args.per_class_shapefiles:
        # Shapefile-only path: create one mask per class and polygonize directly to Shapefile (no GPKG dependency)
        out_dir_path = Path(args.out_dir)
        out_dir_path.mkdir(parents=True, exist_ok=True)
        xsize = ds.RasterXSize
        ysize = ds.RasterYSize
        gt = ds.GetGeoTransform()
        wkt = ds.GetProjection()
        print(
            f"[INFO] Reading full raster to numpy array for per-class polygonize ({xsize}x{ysize})"
        )
        src_arr = band.ReadAsArray()
        print(f"[DEBUG] N unique classes: {np.unique(src_arr).size}")
        mem_drv = gdal.GetDriverByName("MEM")
        shp_drv = ogr.GetDriverByName("ESRI Shapefile")
        classes = args.classes or list(np.unique(src_arr).tolist())
        for c in classes:
            if c == 0:
                continue
            # Build binary mask and value band (value=c where class==c, else 0)
            mask = (src_arr == c).astype(np.uint8)
            if mask.sum() == 0:
                print(f"[INFO] Class {c} has 0 pixels; skipping")
                continue
            val = (src_arr == c).astype(np.uint8) * c
            mem_ds = mem_drv.Create("", xsize, ysize, 1, gdal.GDT_Byte)
            mem_ds.SetGeoTransform(gt)
            mem_ds.SetProjection(wkt)
            mem_ds.GetRasterBand(1).WriteArray(val)
            mem_msk = mem_drv.Create("", xsize, ysize, 1, gdal.GDT_Byte)
            mem_msk.GetRasterBand(1).WriteArray(mask)

            out_shp = out_dir_path / f"class_{c}.shp"
            if out_shp.exists():
                shp_drv.DeleteDataSource(str(out_shp))
            out_ds = shp_drv.CreateDataSource(str(out_shp))
            srs = osr.SpatialReference()
            srs.ImportFromWkt(wkt)
            out_lyr = out_ds.CreateLayer("polygons", srs=srs, geom_type=ogr.wkbPolygon)
            fld = ogr.FieldDefn("class", ogr.OFTInteger)
            out_lyr.CreateField(fld)
            # Polygonize using mask to avoid background
            print(f"[INFO] Polygonizing class {c} -> {out_shp.name}")
            gdal.Polygonize(
                mem_ds.GetRasterBand(1),
                mem_msk.GetRasterBand(1),
                out_lyr,
                0,
                [],
                callback=None,
            )
            print(f"[DEBUG] class {c} feature count: {out_lyr.GetFeatureCount()}")
            out_ds = None
            mem_ds = None
            mem_msk = None
            print(f"[OK] Wrote: {out_shp}")
        ds = None
    else:
        # GPKG combined path
        gpkg_drv = ogr.GetDriverByName("GPKG")
        if gpkg_drv is None:
            raise SystemExit("GPKG driver not available")
        out_gpkg = args.out
        if os.path.exists(out_gpkg):
            gpkg_drv.DeleteDataSource(out_gpkg)
        print(f"[INFO] Creating GeoPackage: {out_gpkg}")
        dst_ds = gpkg_drv.CreateDataSource(out_gpkg)
        if dst_ds is None:
            raise SystemExit("Failed to create GeoPackage datasource")
        layer_name = "dll_polygons"
        print("[INFO] Running Polygonize...")
        lyr = polygonize_to_layer(band, srs_wkt, dst_ds, layer_name)
        feat_count_initial = lyr.GetFeatureCount()
        print(
            f"[DEBUG] Polygonize produced {feat_count_initial} features before filtering"
        )
        dst_ds = None

        # Reopen for filtering
        dst_ds = ogr.Open(out_gpkg, update=1)
        lyr = dst_ds.GetLayer(layer_name)
        if args.classes:
            filter_layer_inplace(lyr, args.classes)
            print(f"[DEBUG] Feature count after class filter: {lyr.GetFeatureCount()}")
        dst_ds = None
        ds = None
        print(f"[OK] Wrote: {out_gpkg} layer={layer_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

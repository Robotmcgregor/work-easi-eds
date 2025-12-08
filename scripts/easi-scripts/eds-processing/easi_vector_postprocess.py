#!/usr/bin/env python
"""
Vector post-process utilities for polygonized clearing outputs.

Features (toggleable):
- dissolve: Merge adjacent/overlapping polygons to reduce fragmentation.
- skinny filter: Remove polygons whose maximum core width is below N pixels
  (approximate via negative buffer of (N * pixel_size / 2) and drop polygons
  that fully erode).

Usage examples:
  # Dissolve only
  python scripts/vector_postprocess.py \
    --input-dir data/compat/files/p089r080/shp_d20231024_20240831_merged_min1ha \
    --out-dir   data/compat/files/p089r080/shp_d20231024_20240831_merged_min1ha_diss \
    --dissolve

  # Dissolve + skinny filter (3-pixel core)
  python scripts/vector_postprocess.py \
    --input-dir data/compat/files/p089r080/shp_d20231024_20240831_merged_min1ha \
    --out-dir   data/compat/files/p089r080/shp_d20231024_20240831_merged_min1ha_clean \
    --dissolve --skinny-pixels 3 --from-raster data/compat/files/p089r080/lztmre_p089r080_d2023102420240831_dllmz.img
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional, Tuple, List

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()


def _get_pixel_size_from_raster(raster_path: Optional[str]) -> Optional[float]:
    if not raster_path:
        return None
    ds = gdal.Open(raster_path, gdal.GA_ReadOnly)
    if ds is None:
        raise SystemExit(f"Cannot open raster for pixel size: {raster_path}")
    gt = ds.GetGeoTransform()
    px = abs(gt[1])
    py = abs(gt[5])
    if px == 0 or py == 0:
        return None
    return (px + py) / 2.0


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _copy_spatial_ref(lyr: ogr.Layer) -> osr.SpatialReference:
    srs = lyr.GetSpatialRef()
    if srs is None:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3577)  # fallback to Albers if missing
    return srs


def _create_out_layer(driver: ogr.Driver, out_path: Path, srs: osr.SpatialReference, template_lyr: ogr.Layer) -> Tuple[ogr.DataSource, ogr.Layer]:
    if out_path.exists():
        driver.DeleteDataSource(str(out_path))
    ds = driver.CreateDataSource(str(out_path))
    out_lyr = ds.CreateLayer('polygons', srs=srs, geom_type=ogr.wkbPolygon)
    # Preserve key attributes if present
    defn = template_lyr.GetLayerDefn()
    for fld_name in ('class', 'thr'):
        idx = defn.GetFieldIndex(fld_name)
        if idx != -1:
            fld_def = defn.GetFieldDefn(idx)
            out_lyr.CreateField(ogr.FieldDefn(fld_def.GetName(), fld_def.GetType()))
    out_lyr.CreateField(ogr.FieldDefn('area_m2', ogr.OFTReal))
    out_lyr.CreateField(ogr.FieldDefn('area_ha', ogr.OFTReal))
    return ds, out_lyr


def _compute_area_fields(geom: ogr.Geometry, srs: osr.SpatialReference) -> Tuple[float, float]:
    # If geographic, reproject to EPSG:3577 for area
    if srs and srs.IsGeographic() == 1:
        target = osr.SpatialReference(); target.ImportFromEPSG(3577)
        ct = osr.CoordinateTransformation(srs, target)
        g2 = geom.Clone(); g2.Transform(ct)
        area_m2 = g2.GetArea()
    else:
        area_m2 = geom.GetArea()
    return area_m2, area_m2 / 10000.0


def _explode_to_parts(geom: ogr.Geometry) -> List[ogr.Geometry]:
    if geom is None:
        return []
    gtype = geom.GetGeometryType()
    if gtype == ogr.wkbPolygon or gtype == ogr.wkbPolygon25D:
        return [geom]
    parts = []
    for i in range(geom.GetGeometryCount()):
        part = geom.GetGeometryRef(i)
        parts.append(part.Clone())
    return parts


def skinny_filter_and_dissolve(in_path: Path, out_path: Path, skinny_pixels: int, pixel_size: Optional[float], do_dissolve: bool) -> None:
    ds = ogr.Open(str(in_path))
    if ds is None:
        print(f"[WARN] Cannot open {in_path}")
        return
    lyr = ds.GetLayer(0)
    srs = _copy_spatial_ref(lyr)

    driver = ogr.GetDriverByName('ESRI Shapefile')
    out_ds, out_lyr = _create_out_layer(driver, out_path, srs, lyr)

    # Determine skinny core buffer distance (in meters)
    core_buf_m = None
    if skinny_pixels and skinny_pixels > 0:
        if pixel_size is None:
            raise SystemExit("--skinny-pixels requires either --pixel-size or --from-raster")
        core_buf_m = (skinny_pixels * pixel_size) / 2.0
        print(f"[INFO] Skinny-core filter: N={skinny_pixels} px -> in-buffer distance={core_buf_m:.3f} m")

    kept_geoms: List[ogr.Geometry] = []
    # Preserve attribute value (assumed constant per file)
    defn = lyr.GetLayerDefn()
    attr_name = 'thr' if defn.GetFieldIndex('thr') != -1 else ('class' if defn.GetFieldIndex('class') != -1 else None)
    attr_val = None

    # Prepare transform for skinny filter if layer is geographic
    needs_reproj = srs.IsGeographic() == 1
    to_ae = None
    from_ae = None
    if needs_reproj:
        ae = osr.SpatialReference(); ae.ImportFromEPSG(3577)
        to_ae = osr.CoordinateTransformation(srs, ae)
        from_ae = osr.CoordinateTransformation(ae, srs)

    for feat in lyr:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        if attr_name and attr_val is None:
            attr_val = feat.GetField(attr_name)
        # Skinny filter
        if core_buf_m is not None:
            if needs_reproj:
                g_proj = geom.Clone(); g_proj.Transform(to_ae)
                g_eroded = g_proj.Buffer(-core_buf_m)
                if g_eroded is None or g_eroded.IsEmpty():
                    continue  # too skinny
            else:
                g_eroded = geom.Clone().Buffer(-core_buf_m)
                if g_eroded is None or g_eroded.IsEmpty():
                    continue
        kept_geoms.append(geom.Clone())

    if not kept_geoms:
        print(f"[INFO] No features kept after skinny filter for {in_path.name}")
        return

    if do_dissolve:
        # Union cascaded: build MultiPolygon explicitly
        mpoly = ogr.Geometry(ogr.wkbMultiPolygon)
        for g in kept_geoms:
            gtype = g.GetGeometryType()
            if gtype in (ogr.wkbPolygon, ogr.wkbPolygon25D):
                mpoly.AddGeometry(g)
            elif gtype in (ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D):
                for i in range(g.GetGeometryCount()):
                    part = g.GetGeometryRef(i)
                    mpoly.AddGeometry(part.Clone())
            else:
                # Try to get polygon boundary as a polygon if possible
                env = g.GetEnvelope()
                if env:
                    # Fallback: skip non-polygonal
                    continue
        dissolved = mpoly.UnionCascaded()
        parts = _explode_to_parts(dissolved)
        for part in parts:
            area_m2, area_ha = _compute_area_fields(part, srs)
            out_feat = ogr.Feature(out_lyr.GetLayerDefn())
            if attr_name and attr_val is not None:
                out_feat.SetField(attr_name, attr_val)
            out_feat.SetField('area_m2', float(area_m2))
            out_feat.SetField('area_ha', float(area_ha))
            out_feat.SetGeometry(part)
            out_lyr.CreateFeature(out_feat)
            out_feat = None
    else:
        # Write kept geoms without dissolving
        for g in kept_geoms:
            area_m2, area_ha = _compute_area_fields(g, srs)
            out_feat = ogr.Feature(out_lyr.GetLayerDefn())
            if attr_name and attr_val is not None:
                out_feat.SetField(attr_name, attr_val)
            out_feat.SetField('area_m2', float(area_m2))
            out_feat.SetField('area_ha', float(area_ha))
            out_feat.SetGeometry(g)
            out_lyr.CreateFeature(out_feat)
            out_feat = None

    # Flush / close
    out_lyr = None
    out_ds = None
    ds = None
    print(f"[OK] Wrote {out_path.name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Post-process clearing polygons: dissolve and/or skinny-core filter.')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--input-dir', help='Directory of .shp files to process')
    g.add_argument('--input-file', help='Single shapefile to process')
    ap.add_argument('--out-dir', required=True, help='Output directory for processed shapefiles')
    ap.add_argument('--dissolve', action='store_true', help='Dissolve adjacent/overlapping polygons')
    ap.add_argument('--skinny-pixels', type=int, default=0, help='Minimum core width in pixels (0 disables)')
    ap.add_argument('--pixel-size', type=float, default=None, help='Pixel size in layer CRS units (e.g., meters)')
    ap.add_argument('--from-raster', type=str, default=None, help='Raster to read pixel size from (uses geotransform)')
    args = ap.parse_args(argv)

    pixel_size = args.pixel_size or _get_pixel_size_from_raster(args.from_raster)

    in_files: List[Path] = []
    if args.input_file:
        in_files = [Path(args.input_file)]
    else:
        in_dir = Path(args.input_dir)
        in_files = [p for p in in_dir.glob('*.shp') if p.is_file()]
    if not in_files:
        print('[INFO] No input shapefiles found.')
        return 0

    out_dir = Path(args.out_dir)
    _ensure_dir(out_dir)

    for shp in sorted(in_files):
        out_path = out_dir / shp.name
        print(f"[INFO] Processing {shp.name} -> {out_path.name}")
        skinny_filter_and_dissolve(shp, out_path, args.skinny_pixels, pixel_size, args.dissolve)

    print(f"[DONE] Processed {len(in_files)} shapefiles into {out_dir}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

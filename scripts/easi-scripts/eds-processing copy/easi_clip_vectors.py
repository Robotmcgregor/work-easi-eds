#!/usr/bin/env python
"""Clip vector polygons by a clip polygon layer.

Usage:
  python scripts/clip_vectors.py \
    --input-dir data/compat/files/p089r080/shp_d20231024_20240831_merged_min1ha_clean \
    --clip data/compat/files/p089r080/fc_coverage/p089r080_fc_consistent.shp \
    --out-dir data/compat/files/p089r080/shp_d20231024_20240831_merged_min1ha_clean_clip_strict

Notes:
  - If the clip dataset has many features (e.g., a mask polygonized from a raster),
    this script unions them into a single MultiPolygon for efficiency.
  - Preserves original attributes. If fields area_m2/area_ha exist, recomputes them
    from the clipped geometry in projected meters (EPSG:3577) or native planar CRS.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple

from osgeo import ogr, osr

ogr.UseExceptions()


def _explode(geom: ogr.Geometry) -> List[ogr.Geometry]:
    if geom is None or geom.IsEmpty():
        return []
    gtype = geom.GetGeometryType()
    if gtype in (ogr.wkbPolygon, ogr.wkbPolygon25D):
        return [geom]
    parts: List[ogr.Geometry] = []
    for i in range(geom.GetGeometryCount()):
        parts.append(geom.GetGeometryRef(i).Clone())
    return parts


def _union_layer_polygons(lyr: ogr.Layer) -> ogr.Geometry:
    # Build a single MultiPolygon and UnionCascaded
    mpoly = ogr.Geometry(ogr.wkbMultiPolygon)
    for feat in lyr:
        g = feat.GetGeometryRef()
        if g is None:
            continue
        if g.GetGeometryType() in (ogr.wkbPolygon, ogr.wkbPolygon25D):
            mpoly.AddGeometry(g)
        elif g.GetGeometryType() in (ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D):
            for i in range(g.GetGeometryCount()):
                mpoly.AddGeometry(g.GetGeometryRef(i).Clone())
    lyr.ResetReading()
    return mpoly.UnionCascaded()


def _ensure_same_srs(
    geom: ogr.Geometry, src_srs: osr.SpatialReference, dst_srs: osr.SpatialReference
) -> ogr.Geometry:
    if src_srs is None or dst_srs is None:
        return geom
    if src_srs.IsSame(dst_srs):
        return geom
    ct = osr.CoordinateTransformation(src_srs, dst_srs)
    g2 = geom.Clone()
    g2.Transform(ct)
    return g2


def _area_fields(geom: ogr.Geometry, srs: osr.SpatialReference) -> Tuple[float, float]:
    if srs is not None and srs.IsGeographic() == 1:
        # project to Albers for area
        tgt = osr.SpatialReference()
        tgt.ImportFromEPSG(3577)
        ct = osr.CoordinateTransformation(srs, tgt)
        g2 = geom.Clone()
        g2.Transform(ct)
        a_m2 = g2.GetArea()
    else:
        a_m2 = geom.GetArea()
    return float(a_m2), float(a_m2 / 10000.0)


def clip_file(in_path: Path, clip_ds: ogr.DataSource, out_dir: Path) -> None:
    in_ds = ogr.Open(str(in_path))
    if in_ds is None:
        print(f"[WARN] Cannot open {in_path}")
        return
    in_lyr = in_ds.GetLayer(0)
    in_srs = in_lyr.GetSpatialRef()

    # Build clip geometry (union) once per input SRS
    clip_lyr = clip_ds.GetLayer(0)
    clip_srs = clip_lyr.GetSpatialRef()
    clip_union = _union_layer_polygons(clip_lyr)
    clip_union = _ensure_same_srs(clip_union, clip_srs, in_srs)

    drv = ogr.GetDriverByName("ESRI Shapefile")
    out_path = out_dir / in_path.name
    if out_path.exists():
        drv.DeleteDataSource(str(out_path))
    out_ds = drv.CreateDataSource(str(out_path))
    out_lyr = out_ds.CreateLayer("polygons", srs=in_srs, geom_type=ogr.wkbPolygon)

    # Copy fields from input; then ensure area fields at the end
    defn = in_lyr.GetLayerDefn()
    field_names = []
    for i in range(defn.GetFieldCount()):
        fdef = defn.GetFieldDefn(i)
        name = fdef.GetName()
        field_names.append(name)
        out_lyr.CreateField(ogr.FieldDefn(name, fdef.GetType()))
    # area fields: create only if not present
    has_area_m2 = "area_m2" in field_names
    has_area_ha = "area_ha" in field_names
    if not has_area_m2:
        out_lyr.CreateField(ogr.FieldDefn("area_m2", ogr.OFTReal))
    if not has_area_ha:
        out_lyr.CreateField(ogr.FieldDefn("area_ha", ogr.OFTReal))

    # Clip
    for feat in in_lyr:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        inter = geom.Intersection(clip_union)
        if inter is None or inter.IsEmpty():
            continue
        # Fix potential topology issues and filter to polygons only
        try:
            inter = inter.MakeValid()
        except AttributeError:
            inter = inter.Buffer(0)
        for part in _explode(inter):
            if part.GetGeometryType() not in (ogr.wkbPolygon, ogr.wkbPolygon25D):
                continue
            a_m2, a_ha = _area_fields(part, in_srs)
            out_feat = ogr.Feature(out_lyr.GetLayerDefn())
            for name in field_names:
                out_feat.SetField(name, feat.GetField(name))
            # set area fields into existing names or created ones
            out_feat.SetField("area_m2", a_m2)
            out_feat.SetField("area_ha", a_ha)
            out_feat.SetGeometry(part)
            out_lyr.CreateFeature(out_feat)
            out_feat = None

    out_lyr = None
    out_ds = None
    in_ds = None
    print(f"[OK] Clipped {in_path.name} -> {out_path.name}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Clip polygons by a clip polygon layer")
    ap.add_argument(
        "--input-dir", required=True, help="Directory of .shp files to clip"
    )
    ap.add_argument("--clip", required=True, help="Clip polygon shapefile path")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    args = ap.parse_args(argv)

    in_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shp_files = sorted([p for p in in_dir.glob("*.shp") if p.is_file()])
    if not shp_files:
        print("[INFO] No shapefiles found to clip.")
        return 0

    clip_ds = ogr.Open(args.clip)
    if clip_ds is None:
        raise SystemExit(f"Cannot open clip dataset: {args.clip}")

    for shp in shp_files:
        clip_file(shp, clip_ds, out_dir)
    print(f"[DONE] Clipped {len(shp_files)} files into {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

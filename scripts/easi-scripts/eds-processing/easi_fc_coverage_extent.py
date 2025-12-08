#!/usr/bin/env python
"""Derive fractional cover (FC) input spatial coverage footprints and a consistent coverage mask.

Generates two shapefiles:
  1. <scene>_fc_inputs_union.shp  -> union of extents of all FC rasters (masked if *_clr present)
  2. <scene>_fc_consistent.shp    -> area with consistent coverage across time. Two modes:
       a) Intersection of all rasters (default) => strict core where every FC image has data.
       b) Data density threshold (--min-presence-ratio) => keep pixels with data in >= ratio of rasters.

Additionally writes a raster mask (<scene>_fc_consistent_mask.tif) if ratio mode chosen for potential clipping.

Optional: write per-input valid-data masks aligned to a common grid (useful for QA and custom coverage logic).

Usage:
  python scripts/fc_coverage_extent.py \
    --fc-dir data/compat/files/p089r080 \
    --scene p089r080 \
    --pattern "*_dc4mz.img" \
    --out-dir data/compat/files/p089r080/fc_coverage \
        --min-presence-ratio 0.9 \
        --save-per-input-masks

If --min-presence-ratio omitted, strict intersection polygon is produced.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Optional

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()


def list_fc_rasters(fc_dir: Path, pattern: str) -> List[Path]:
    return sorted([p for p in fc_dir.glob(pattern) if p.is_file()])


def open_raster(path: Path):
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {path}")
    return ds


def raster_footprint_polygon(ds) -> ogr.Geometry:
    gt = ds.GetGeoTransform()
    xsize = ds.RasterXSize
    ysize = ds.RasterYSize
    # corners
    x0 = gt[0]; y0 = gt[3]
    px_w = gt[1]; px_h = gt[5]
    x1 = x0 + xsize * px_w
    y1 = y0 + ysize * px_h
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(x0, y0)
    ring.AddPoint(x1, y0)
    ring.AddPoint(x1, y1)
    ring.AddPoint(x0, y1)
    ring.AddPoint(x0, y0)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def union_geoms(geoms: List[ogr.Geometry]) -> ogr.Geometry:
    if not geoms:
        return None
    out = geoms[0].Clone()
    for g in geoms[1:]:
        out = out.Union(g)
    return out


def intersect_geoms(geoms: List[ogr.Geometry]) -> ogr.Geometry:
    if not geoms:
        return None
    out = geoms[0].Clone()
    for g in geoms[1:]:
        out = out.Intersection(g)
        if out is None or out.IsEmpty():
            break
    return out


def save_polygon(out_path: Path, geom: ogr.Geometry, srs_wkt: str, layer_name: str='coverage'):
    """Create (or recreate) a single-polygon shapefile.

    Uses robust deletion logic to avoid GDAL Create errors on re-run. If the
    driver still fails, attempts a fallback rename of existing components.
    """
    drv = ogr.GetDriverByName('ESRI Shapefile')
    # Full clean of existing sidecars
    stem = out_path.with_suffix('')  # base path without .shp
    if out_path.exists():
        try:
            drv.DeleteDataSource(str(out_path))
        except Exception:
            # Manual sidecar cleanup
            for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'): 
                side = stem.with_suffix(ext)
                if side.exists():
                    try:
                        side.unlink()
                    except Exception:
                        pass
    # Create new dataset
    ds = drv.CreateDataSource(str(out_path))
    if ds is None:
        raise RuntimeError(f'Failed to create shapefile: {out_path}')
    srs = osr.SpatialReference(); srs.ImportFromWkt(srs_wkt)
    lyr = ds.CreateLayer(layer_name, srs=srs, geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
    feat = ogr.Feature(lyr.GetLayerDefn())
    feat.SetField('id', 1)
    feat.SetGeometry(geom)
    lyr.CreateFeature(feat)
    feat = None
    ds = None


def _write_mask_raster(out_path: Path, gt, proj, mask_arr: np.ndarray):
    drv = gdal.GetDriverByName('GTiff')
    if out_path.exists():
        out_path.unlink()
    ysize, xsize = mask_arr.shape
    ds = drv.Create(str(out_path), xsize, ysize, 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt); ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    band.WriteArray(mask_arr.astype(np.uint8))
    band.SetNoDataValue(0)
    ds = None


def build_presence_mask(
    rasters: List[Path],
    min_ratio: float,
    out_mask: Path,
    per_input_dir: Optional[Path] = None,
):
    # Align rasters to first raster grid; if different size/transform skip or warp in-memory.
    datasets = [open_raster(r) for r in rasters]
    ref = datasets[0]
    gt_ref = ref.GetGeoTransform(); proj = ref.GetProjection()
    xsize_ref = ref.RasterXSize; ysize_ref = ref.RasterYSize
    nodatas = []
    for ds in datasets:
        band = ds.GetRasterBand(1)
        nodatas.append(band.GetNoDataValue())

    presence = np.zeros((ysize_ref, xsize_ref), dtype=np.uint16)
    total = 0
    for src_path, ds, nd in zip(rasters, datasets, nodatas):
        gt = ds.GetGeoTransform()
        if (gt != gt_ref) or (ds.RasterXSize != xsize_ref) or (ds.RasterYSize != ysize_ref):
            # Warp to reference grid
            mem_drv = gdal.GetDriverByName('MEM')
            tmp = mem_drv.Create('', xsize_ref, ysize_ref, 1, gdal.GDT_Float32)
            tmp.SetGeoTransform(gt_ref); tmp.SetProjection(proj)
            gdal.ReprojectImage(ds, tmp, ds.GetProjection(), proj, gdal.GRA_NearestNeighbour)
            arr = tmp.GetRasterBand(1).ReadAsArray()
            tmp = None
        else:
            arr = ds.GetRasterBand(1).ReadAsArray()
        # Build valid mask: finite and not equal to nodata (if provided). Fallback: non-zero.
        mask = np.isfinite(arr)
        if nd is not None:
            try:
                mask &= (arr != nd)
            except Exception:
                mask &= (arr != nd)
        else:
            mask &= (arr != 0)
        presence += mask.astype(np.uint16)
        total += 1
        # Optionally write per-input mask aligned to reference grid
        if per_input_dir is not None:
            per_input_dir.mkdir(parents=True, exist_ok=True)
            out_name = src_path.stem + '_valid_mask.tif'
            _write_mask_raster(per_input_dir / out_name, gt_ref, proj, mask)
    ratio = presence.astype(np.float32) / float(total)
    keep = ratio >= min_ratio

    _write_mask_raster(out_mask, gt_ref, proj, keep)
    # Polygonize keep mask for shapefile
    mem = gdal.GetDriverByName('MEM').Create('', xsize_ref, ysize_ref, 1, gdal.GDT_Byte)
    mem.SetGeoTransform(gt_ref); mem.SetProjection(proj)
    mem.GetRasterBand(1).WriteArray(keep.astype(np.uint8))
    mem.GetRasterBand(1).SetNoDataValue(0)
    drv_shp = ogr.GetDriverByName('ESRI Shapefile')
    shp_path = out_mask.with_name(out_mask.stem + '.shp')
    # Cleanup any pre-existing shapefile components
    if shp_path.exists():
        try:
            drv_shp.DeleteDataSource(str(shp_path))
        except Exception:
            stem = shp_path.with_suffix('')
            for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
                side = stem.with_suffix(ext)
                if side.exists():
                    try:
                        side.unlink()
                    except Exception:
                        pass
    # Create shapefile, with a fallback name if creation fails on some systems
    shp_ds = drv_shp.CreateDataSource(str(shp_path))
    if shp_ds is None:
        alt_path = out_mask.with_name(out_mask.stem + '_poly.shp')
        shp_ds = drv_shp.CreateDataSource(str(alt_path))
        if shp_ds is None:
            raise RuntimeError(f'Failed to create ratio mask shapefile: {shp_path} (and fallback {alt_path})')
        shp_path = alt_path
    srs = osr.SpatialReference(); srs.ImportFromWkt(proj)
    lyr = shp_ds.CreateLayer('consistent', srs=srs, geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('val', ogr.OFTInteger))
    gdal.Polygonize(mem.GetRasterBand(1), None, lyr, 0, [], callback=None)
    shp_ds = None


def write_per_input_masks_only(rasters: List[Path], per_input_dir: Path):
    """Write valid-data masks for each input, aligned to the first raster's grid.

    No ratio aggregation is produced; used when ratio outputs already exist but
    per-input masks are requested.
    """
    datasets = [open_raster(r) for r in rasters]
    ref = datasets[0]
    gt_ref = ref.GetGeoTransform(); proj = ref.GetProjection()
    xsize_ref = ref.RasterXSize; ysize_ref = ref.RasterYSize
    nodatas = []
    for ds in datasets:
        band = ds.GetRasterBand(1)
        nodatas.append(band.GetNoDataValue())

    per_input_dir.mkdir(parents=True, exist_ok=True)
    for src_path, ds, nd in zip(rasters, datasets, nodatas):
        gt = ds.GetGeoTransform()
        if (gt != gt_ref) or (ds.RasterXSize != xsize_ref) or (ds.RasterYSize != ysize_ref):
            mem_drv = gdal.GetDriverByName('MEM')
            tmp = mem_drv.Create('', xsize_ref, ysize_ref, 1, gdal.GDT_Float32)
            tmp.SetGeoTransform(gt_ref); tmp.SetProjection(proj)
            gdal.ReprojectImage(ds, tmp, ds.GetProjection(), proj, gdal.GRA_NearestNeighbour)
            arr = tmp.GetRasterBand(1).ReadAsArray()
            tmp = None
        else:
            arr = ds.GetRasterBand(1).ReadAsArray()
        mask = np.isfinite(arr)
        if nd is not None:
            mask &= (arr != nd)
        else:
            mask &= (arr != 0)
        out_name = src_path.stem + '_valid_mask.tif'
        _write_mask_raster(per_input_dir / out_name, gt_ref, proj, mask)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Compute FC input union and consistent coverage polygons.')
    ap.add_argument('--fc-dir', required=True, help='Directory containing FC rasters')
    ap.add_argument('--scene', required=True, help='Scene identifier (e.g., p089r080) used in output names')
    ap.add_argument('--pattern', default='*_dc4mz.img', help='Glob pattern for FC rasters (default *_dc4mz.img)')
    ap.add_argument('--out-dir', required=True, help='Output directory')
    ap.add_argument('--min-presence-ratio', type=float, default=None, help='(Deprecated in multi-ratio mode) Single ratio; prefer --ratios')
    ap.add_argument('--ratios', type=float, nargs='*', default=None, help='One or more presence ratios (e.g. 0.95 0.90) to generate multiple coverage masks')
    ap.add_argument('--save-per-input-masks', action='store_true', help='Write per-input valid masks aligned to the reference grid')
    ap.add_argument('--per-input-dir', default=None, help='Directory to write per-input masks (default: <out-dir>/masks)')
    ap.add_argument('--force', action='store_true', help='Force overwrite of outputs (mask TIFF and shapefile) if they exist')
    args = ap.parse_args(argv)

    fc_dir = Path(args.fc_dir)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    rasters = list_fc_rasters(fc_dir, args.pattern)
    if not rasters:
        raise SystemExit('No FC rasters found.')
    print(f'[INFO] Found {len(rasters)} FC rasters')

    # Build footprint polygons
    geoms = []
    proj_wkt = None
    for rp in rasters:
        ds = open_raster(rp)
        if proj_wkt is None:
            proj_wkt = ds.GetProjection()
        poly = raster_footprint_polygon(ds)
        geoms.append(poly)
    union = union_geoms(geoms)
    inter = intersect_geoms(geoms)

    union_path = out_dir / f'{args.scene}_fc_inputs_union.shp'
    consistent_path = out_dir / f'{args.scene}_fc_consistent.shp'

    if union_path.exists():
        print(f'[SKIP] Union footprint already exists: {union_path}')
    else:
        save_polygon(union_path, union, proj_wkt, 'inputs_union')
        print(f'[OK] Wrote union footprint: {union_path}')

    # Determine ratios list
    ratios: List[float] = []
    if args.ratios:
        ratios = args.ratios
    elif args.min_presence_ratio is not None:
        ratios = [args.min_presence_ratio]

    if not ratios:
        if consistent_path.exists():
            print(f'[SKIP] Strict intersection already exists: {consistent_path}')
        else:
            save_polygon(consistent_path, inter, proj_wkt, 'consistent_all')
            print(f'[OK] Wrote strict intersection: {consistent_path}')
    else:
        # Validate ratios
        for r in ratios:
            if not (0 < r <= 1):
                raise SystemExit(f'Invalid ratio {r}; must be in (0,1]')
        per_dir = None
        if args.save_per_input_masks:
            per_dir = Path(args.per_input_dir) if args.per_input_dir else (out_dir / 'masks')
            # Always write per-input masks once
            write_per_input_masks_only(rasters, per_dir)
            print(f'[OK] Wrote per-input valid masks: {per_dir}')
        for r in ratios:
            suffix = f'{int(r*100):03d}'  # e.g. 95 -> '095'
            mask_path = out_dir / f'{args.scene}_fc_consistent_r{suffix}.tif'
            shp_path = mask_path.with_name(mask_path.stem + '.shp')
            if not args.force and mask_path.exists() and shp_path.exists():
                print(f'[SKIP] Ratio {r:.2f} outputs already exist: {mask_path} and {shp_path}')
                continue
            try:
                build_presence_mask(rasters, r, mask_path, per_input_dir=None)
                print(f'[OK] Wrote ratio {r:.2f} mask & polygon: {mask_path} -> {shp_path}')
            except Exception as e:
                print(f'[ERROR] Failed ratio {r:.2f} build: {e}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())

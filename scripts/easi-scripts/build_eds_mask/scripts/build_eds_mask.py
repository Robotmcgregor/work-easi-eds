#!/usr/bin/env python3
from __future__ import annotations

"""build_eds_mask — rasterize clearing polygons to an aligned Landsat GA0 grid.

High-level behavior
-------------------
- Scans an input folder for Shapefiles (".shp").
- Reads all features where `IsClearing == "y"` (case-insensitive, configurable).
- Validates that selected geometries are polygonal (Polygon/MultiPolygon).
- Groups by Landsat tile id (e.g. "p089r084") using a tile field or infers from filename.
- For each tile:
  - Locates a GA0 GeoTIFF for that tile under `--ga0-root`.
  - Uses the GA0 raster geotransform/shape/CRS as the mask grid.
  - Rasterizes all clearing polygons for that tile into a 1-band Byte mask.

Notes
-----
- This script uses GDAL/OGR for vector IO and rasterization (fast + reliable for this job).
- RIOS is typically best for pixel-wise operations; for vector->raster rasterization GDAL is the
  standard tool, while we still use similar GeoTIFF tiling/compression conventions.

You said you cannot test until running on EASI; this is written to be conservative:
- `--dry-run` is the default.
- `--apply` is required to write outputs.

Example
-------
python scripts/easi-scripts/build_eds_mask/scripts/build_eds_mask.py \
  --input-data /data/clearing_vectors \
  --ga0-root /data/ga0_cache \
  --out-dir /data/eds_masks \
  --tile-field tile \
  --dry-run
"""

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


try:
    from osgeo import gdal, ogr, osr  # type: ignore

    gdal.UseExceptions()
    ogr.UseExceptions()
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "GDAL/OGR is required (osgeo.gdal/ogr/osr). "
        "Install it in your EASI conda env (e.g. conda install gdal). "
        f"Import error: {e}"
    )


TILE_RE = re.compile(r"p\d{3}r\d{3}", re.IGNORECASE)


@dataclass(frozen=True)
class TileInputs:
    tile: str
    clearing_feature_count: int


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser("build_eds_mask")

    ap.add_argument(
        "--input-data",
        required=True,
        help="Folder containing input Shapefiles (.shp). Searched recursively.",
    )
    ap.add_argument(
        "--ga0-root",
        required=True,
        help="Folder containing GA0 GeoTIFFs; searched recursively by tile.",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Output folder for generated mask GeoTIFFs.",
    )

    ap.add_argument(
        "--clearing-field",
        default="IsClearing",
        help="Attribute field used to filter polygons (default: IsClearing).",
    )
    ap.add_argument(
        "--clearing-value",
        default="y",
        help="Value indicating a clearing polygon (case-insensitive, default: y).",
    )

    ap.add_argument(
        "--tile-field",
        default=None,
        help=(
            "Optional attribute field containing tile id (e.g. p089r084). "
            "If omitted, tries to infer from common field names or the shapefile filename."
        ),
    )

    ap.add_argument(
        "--ga0-pattern",
        default="*olre_{tile}_*_ga0*_e*.tif",
        help=(
            "Glob pattern (within --ga0-root) used to find GA0 rasters. "
            "Use '{tile}' placeholder (default: *olre_{tile}_*_ga0*_e*.tif)."
        ),
    )

    ap.add_argument(
        "--all-touched",
        action="store_true",
        help="Rasterize with ALL_TOUCHED=TRUE (default: false).",
    )

    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only (default unless --apply).",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually write outputs.",
    )

    ap.add_argument(
        "--limit-tiles",
        type=int,
        default=0,
        help="Process only first N tiles (0 = no limit).",
    )

    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output masks.",
    )

    args = ap.parse_args(argv)

    # Default to dry-run unless explicitly applying.
    if not args.apply:
        args.dry_run = True

    return args


def iter_shapefiles(root: Path) -> Iterator[Path]:
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".shp"):
                yield Path(dirpath) / fn


def _extract_tile_from_text(text: str) -> Optional[str]:
    m = TILE_RE.search(text or "")
    if not m:
        return None
    return m.group(0).lower()


def _guess_tile_field(layer_defn: ogr.FeatureDefn) -> Optional[str]:
    """Try common tile field names."""
    candidates = [
        "tile",
        "Tile",
        "TILE",
        "tile_id",
        "TileID",
        "scene",
        "Scene",
        "SCENE",
    ]
    names = {layer_defn.GetFieldDefn(i).GetName() for i in range(layer_defn.GetFieldCount())}
    for c in candidates:
        if c in names:
            return c
    return None


def _is_polygonal(geom: ogr.Geometry) -> bool:
    if geom is None:
        return False
    gtype = geom.GetGeometryType()
    return gtype in (
        ogr.wkbPolygon,
        ogr.wkbPolygon25D,
        ogr.wkbMultiPolygon,
        ogr.wkbMultiPolygon25D,
    )


def _norm_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _field_value_equals(v, expected: str) -> bool:
    return _norm_str(v).lower() == _norm_str(expected).lower()


def scan_tiles(
    shp_files: Sequence[Path],
    *,
    clearing_field: str,
    clearing_value: str,
    tile_field: Optional[str],
) -> Dict[str, TileInputs]:
    """Scan all shapefiles and return tiles that contain clearing polygons.

    Also validates:
    - `clearing_field` exists
    - geometries are polygonal for any selected (clearing) features
    - tile id can be derived
    """

    tiles: Dict[str, int] = {}

    for shp_path in shp_files:
        ds = ogr.Open(str(shp_path))
        if ds is None:
            raise RuntimeError(f"Cannot open shapefile: {shp_path}")
        lyr = ds.GetLayer(0)
        if lyr is None:
            raise RuntimeError(f"No layer found in: {shp_path}")

        defn = lyr.GetLayerDefn()
        effective_tile_field = tile_field or _guess_tile_field(defn)
        file_tile_hint = _extract_tile_from_text(shp_path.name)

        # Validate clearing field exists
        field_names = {defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())}
        if clearing_field not in field_names:
            raise RuntimeError(
                f"Missing clearing field '{clearing_field}' in {shp_path} (fields={sorted(field_names)})"
            )

        if tile_field and tile_field not in field_names:
            raise RuntimeError(
                f"Missing tile field '{tile_field}' in {shp_path} (fields={sorted(field_names)})"
            )

        for feat in lyr:
            if not _field_value_equals(feat.GetField(clearing_field), clearing_value):
                continue

            geom = feat.GetGeometryRef()
            if geom is None:
                continue

            if not _is_polygonal(geom):
                raise RuntimeError(
                    f"Non-polygon geometry found in {shp_path} for clearing feature (geom_type={geom.GetGeometryName()})"
                )

            tile_val: Optional[str] = None
            if effective_tile_field:
                tile_val = _extract_tile_from_text(_norm_str(feat.GetField(effective_tile_field)))
            if not tile_val and file_tile_hint:
                tile_val = file_tile_hint
            if not tile_val:
                raise RuntimeError(
                    f"Could not determine tile id for clearing feature in {shp_path}. "
                    f"Provide --tile-field or include 'p###r###' in filename."
                )

            tiles[tile_val] = tiles.get(tile_val, 0) + 1

        lyr.ResetReading()
        ds = None

    return {t: TileInputs(tile=t, clearing_feature_count=n) for t, n in sorted(tiles.items())}


def _find_ga0_for_tile(ga0_root: Path, pattern_template: str, tile: str) -> Path:
    pattern = pattern_template.format(tile=tile)
    candidates = sorted(ga0_root.rglob(pattern))
    if not candidates:
        raise RuntimeError(
            f"No GA0 GeoTIFF found for tile={tile} under {ga0_root} with pattern={pattern!r}"
        )

    if len(candidates) == 1:
        return candidates[0]

    # Prefer ga0-clr
    clr = [p for p in candidates if "_ga0-clr_" in p.name or "_ga0-clr" in p.name]
    if len(clr) == 1:
        return clr[0]

    # Prefer newest by date token _YYYYMMDD_ in filename
    def _date_token(p: Path) -> str:
        m = re.search(r"_(\d{8})_ga0", p.name)
        return m.group(1) if m else "00000000"

    by_date = sorted(candidates, key=_date_token, reverse=True)
    best = by_date[0]

    # If the top two have same date token, selection is ambiguous.
    if len(by_date) > 1 and _date_token(by_date[1]) == _date_token(best):
        raise RuntimeError(
            f"Multiple GA0 candidates for tile={tile} and same date token; please narrow --ga0-pattern. "
            f"Candidates: {[str(p) for p in candidates]}"
        )

    return best


def _epsg_from_dataset(ds: gdal.Dataset) -> Optional[int]:
    wkt = ds.GetProjection() or ""
    if not wkt:
        return None
    srs = osr.SpatialReference()
    srs.ImportFromWkt(wkt)
    srs.AutoIdentifyEPSG()
    auth = srs.GetAuthorityCode(None)
    if auth and str(auth).isdigit():
        return int(auth)
    # fallback: try from PROJCS/GEOGCS
    auth = srs.GetAuthorityCode("PROJCS") or srs.GetAuthorityCode("GEOGCS")
    if auth and str(auth).isdigit():
        return int(auth)
    return None


def _make_mask_output_path(out_dir: Path, tile: str, epsg: Optional[int]) -> Path:
    if epsg:
        return out_dir / f"eds_mask_{tile}_e{epsg}.tif"
    return out_dir / f"eds_mask_{tile}.tif"


def _rio_like_gtiff_creation_options() -> List[str]:
    # Mirror the general conventions used elsewhere in the repo (tiled + LZW).
    return [
        "COMPRESS=LZW",
        "TILED=YES",
        "BLOCKXSIZE=256",
        "BLOCKYSIZE=256",
        "BIGTIFF=IF_SAFER",
    ]


def rasterize_tile_mask(
    *,
    tile: str,
    shp_files: Sequence[Path],
    ga0_path: Path,
    out_path: Path,
    clearing_field: str,
    clearing_value: str,
    tile_field: Optional[str],
    all_touched: bool,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Create a mask raster for a single tile."""

    ga0_ds = gdal.Open(str(ga0_path), gdal.GA_ReadOnly)
    if ga0_ds is None:
        raise RuntimeError(f"Cannot open GA0 raster: {ga0_path}")

    xsize = ga0_ds.RasterXSize
    ysize = ga0_ds.RasterYSize
    geot = ga0_ds.GetGeoTransform()
    proj = ga0_ds.GetProjection()

    epsg = _epsg_from_dataset(ga0_ds)

    print(f"[TILE] {tile}: ga0={ga0_path} epsg={epsg} size={xsize}x{ysize}")
    print(f"[OUT ] {out_path}")

    if out_path.exists() and not overwrite:
        print(f"[SKIP] Exists (use --overwrite): {out_path}")
        return

    if dry_run:
        # We still scan inputs to be able to report approximate work, but do not write.
        print("[DRY] Would create mask and rasterize clearing polygons")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)

    drv = gdal.GetDriverByName("GTiff")
    if out_path.exists():
        drv.Delete(str(out_path))

    out_ds = drv.Create(
        str(out_path),
        xsize,
        ysize,
        1,
        gdal.GDT_Byte,
        options=_rio_like_gtiff_creation_options(),
    )
    if out_ds is None:
        raise RuntimeError(f"Failed to create output raster: {out_path}")

    out_ds.SetGeoTransform(geot)
    if proj:
        out_ds.SetProjection(proj)

    band = out_ds.GetRasterBand(1)
    band.SetNoDataValue(0)
    band.Fill(0)

    # Output SRS derived from GA0
    dst_srs = osr.SpatialReference()
    if proj:
        dst_srs.ImportFromWkt(proj)

    burned = 0

    for shp_path in shp_files:
        ds = ogr.Open(str(shp_path))
        if ds is None:
            raise RuntimeError(f"Cannot open shapefile: {shp_path}")
        lyr = ds.GetLayer(0)
        if lyr is None:
            raise RuntimeError(f"No layer found in: {shp_path}")

        defn = lyr.GetLayerDefn()
        field_names = {defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())}
        if clearing_field not in field_names:
            raise RuntimeError(f"Missing clearing field '{clearing_field}' in {shp_path}")

        effective_tile_field = tile_field or _guess_tile_field(defn)
        file_tile_hint = _extract_tile_from_text(shp_path.name)

        src_srs = lyr.GetSpatialRef()
        ct = None
        if src_srs is not None and dst_srs is not None and proj:
            if not src_srs.IsSame(dst_srs):
                ct = osr.CoordinateTransformation(src_srs, dst_srs)

        for feat in lyr:
            if not _field_value_equals(feat.GetField(clearing_field), clearing_value):
                continue

            tile_val: Optional[str] = None
            if effective_tile_field and effective_tile_field in field_names:
                tile_val = _extract_tile_from_text(_norm_str(feat.GetField(effective_tile_field)))
            if not tile_val and file_tile_hint:
                tile_val = file_tile_hint
            if not tile_val:
                raise RuntimeError(
                    f"Could not determine tile id for clearing feature in {shp_path}. Provide --tile-field."
                )
            if tile_val.lower() != tile.lower():
                continue

            geom = feat.GetGeometryRef()
            if geom is None or geom.IsEmpty():
                continue
            if not _is_polygonal(geom):
                raise RuntimeError(
                    f"Non-polygon geometry found in {shp_path} for clearing feature (geom_type={geom.GetGeometryName()})"
                )

            g2 = geom.Clone()
            if ct is not None:
                g2.Transform(ct)

            # Rasterize this geometry onto the output dataset.
            opts = ["ALL_TOUCHED=TRUE"] if all_touched else []
            err = gdal.RasterizeGeometries(
                out_ds,
                [1],
                [g2],
                burnValues=[1],
                options=opts,
            )
            if err != 0:
                raise RuntimeError(f"RasterizeGeometries failed for {shp_path}")
            burned += 1

        lyr.ResetReading()
        ds = None

    band.FlushCache()
    out_ds.FlushCache()
    out_ds = None
    ga0_ds = None

    print(f"[OK] Burned {burned} clearing polygons -> {out_path}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    input_root = Path(args.input_data)
    ga0_root = Path(args.ga0_root)
    out_dir = Path(args.out_dir)

    shp_files = sorted(iter_shapefiles(input_root))
    if not shp_files:
        print(f"[INFO] No shapefiles found under: {input_root}")
        return 0

    print(f"[INFO] Shapefiles found: {len(shp_files)}")

    tiles = scan_tiles(
        shp_files,
        clearing_field=args.clearing_field,
        clearing_value=args.clearing_value,
        tile_field=args.tile_field,
    )

    if not tiles:
        print("[INFO] No clearing polygons found (after filtering).")
        return 0

    tile_list = list(tiles.values())
    if args.limit_tiles and args.limit_tiles > 0:
        tile_list = tile_list[: args.limit_tiles]
        print(f"[INFO] limit-tiles enabled: {len(tile_list)}")

    out_dir.mkdir(parents=True, exist_ok=True)

    for t in tile_list:
        ga0_path = _find_ga0_for_tile(ga0_root, args.ga0_pattern, t.tile)
        ga0_ds = gdal.Open(str(ga0_path), gdal.GA_ReadOnly)
        epsg = _epsg_from_dataset(ga0_ds) if ga0_ds else None
        if ga0_ds:
            ga0_ds = None

        out_path = _make_mask_output_path(out_dir, t.tile, epsg)

        print(f"[INFO] Tile {t.tile}: clearing_features={t.clearing_feature_count}")
        rasterize_tile_mask(
            tile=t.tile,
            shp_files=shp_files,
            ga0_path=ga0_path,
            out_path=out_path,
            clearing_field=args.clearing_field,
            clearing_value=args.clearing_value,
            tile_field=args.tile_field,
            all_touched=bool(args.all_touched),
            overwrite=bool(args.overwrite),
            dry_run=bool(args.dry_run),
        )

    print("[DONE] build_eds_mask finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

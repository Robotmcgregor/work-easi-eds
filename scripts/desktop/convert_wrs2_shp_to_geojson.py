#!/usr/bin/env python
"""
Convert a WRS-2 Shapefile to GeoJSON using the lightweight 'pyshp' library (no GDAL required).

Usage (PowerShell):
  # Install dependency once (small, pure-Python)
  # py -m pip install pyshp

  # Convert
  py scripts/convert_wrs2_shp_to_geojson.py path\to\WRS2.shp --out data/WRS2.geojson

Notes:
  - This keeps the original coordinate reference system. If your shapefile is not WGS84 (EPSG:4326),
    use QGIS to reproject first, or ensure the .prj references WGS 84.
  - Properties are preserved, including PATH/ROW fields.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    import shapefile  # pyshp
except ImportError:
    print(
        "Missing dependency: pyshp. Install with: py -m pip install pyshp",
        file=sys.stderr,
    )
    raise


def read_prj(prj_path: Path) -> str | None:
    try:
        if prj_path.exists():
            return prj_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    return None


def shp_to_geojson(shp_path: Path, out_path: Path) -> None:
    r = shapefile.Reader(shp_path)
    fields = [f[0] for f in r.fields if f[0] != "DeletionFlag"]
    features = []
    for sr in r.shapeRecords():
        geom = sr.shape.__geo_interface__
        rec = (
            sr.record.as_dict()
            if hasattr(sr.record, "as_dict")
            else {k: sr.record[i] for i, k in enumerate(fields)}
        )
        features.append({"type": "Feature", "geometry": geom, "properties": rec})

    fc = {"type": "FeatureCollection", "features": features}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fc), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert WRS-2 Shapefile to GeoJSON (no GDAL)"
    )
    p.add_argument("shapefile", help="Path to WRS-2 .shp file")
    p.add_argument("--out", default="data/WRS2.geojson", help="Output GeoJSON path")
    return p


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    shp_path = Path(args.shapefile)
    if not shp_path.exists():
        print(f"Shapefile not found: {shp_path}", file=sys.stderr)
        return 2
    prj = read_prj(shp_path.with_suffix(".prj"))
    if prj and ("WGS_1984" in prj or "WGS 84" in prj or "4326" in prj):
        pass
    else:
        print(
            "Warning: .prj not found or not WGS84 (EPSG:4326). Consider reprojecting via QGIS if needed."
        )
    out_path = Path(args.out)
    shp_to_geojson(shp_path, out_path)
    print(f"Wrote GeoJSON: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

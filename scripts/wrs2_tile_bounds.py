#!/usr/bin/env python
"""
Build per-tile bounding boxes from a WRS-2 GeoJSON and store them in CSV and/or SQLite.

Usage (PowerShell):
  # From repo root; requires a WRS-2 GeoJSON with properties PATH/ROW (or wrs_path/wrs_row)
  py scripts/wrs2_tile_bounds.py data/WRS2.geojson --csv data/wrs2_tile_bounds.csv --sqlite data/wrs2.sqlite

Notes:
  - No heavy geo deps; plain JSON processing to compute bboxes.
  - Supports Polygon and MultiPolygon geometries.
  - Table name in SQLite: wrs2_tile_bounds (tile_id TEXT PRIMARY KEY, path INT, row INT, min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from typing import Any, Dict, Iterable, List, Tuple
from os import path as _os_path


def _coords_from_geom(geom: Dict[str, Any]) -> Iterable[Tuple[float, float]]:
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not gtype or coords is None:
        return []
    if gtype == "Polygon":
        # coords: [ [ [lon,lat], ... ] , [hole], ... ]
        for ring in coords:
            for x, y in ring:
                yield float(x), float(y)
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                for x, y in ring:
                    yield float(x), float(y)
    else:
        return []


def _get_path_row(props: Dict[str, Any]) -> Tuple[int, int]:
    # Try common property name variants
    keys = [
        ("PATH", "ROW"),
        ("path", "row"),
        ("WRS_PATH", "WRS_ROW"),
        ("wrs_path", "wrs_row"),
    ]
    for kp, kr in keys:
        if kp in props and kr in props:
            return int(props[kp]), int(props[kr])
    # Fallback: PR or pr as concatenated string '089078'
    for k in ("PR", "pr"):
        if k in props:
            s = str(props[k]).strip()
            if len(s) == 6 and s.isdigit():
                return int(s[:3]), int(s[3:])
    raise KeyError("Could not determine WRS-2 path/row from feature properties")


def process_geojson(path_geojson: str) -> List[Dict[str, Any]]:
    if not _os_path.exists(path_geojson):
        raise FileNotFoundError(
            f"GeoJSON not found: {path_geojson}. See README-create-bbox.md for how to obtain WRS-2 and export to GeoJSON."
        )
    with open(path_geojson, "r", encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj.get("features", [])
    rows: List[Dict[str, Any]] = []
    for ft in feats:
        try:
            p, r = _get_path_row(ft.get("properties", {}))
        except Exception:
            continue
        xs: List[float] = []
        ys: List[float] = []
        for x, y in _coords_from_geom(ft.get("geometry", {})):
            xs.append(x)
            ys.append(y)
        if not xs:
            continue
        min_lon, max_lon = min(xs), max(xs)
        min_lat, max_lat = min(ys), max(ys)
        tile_id = f"{p:03d}{r:03d}"
        rows.append(
            {
                "tile_id": tile_id,
                "path": p,
                "row": r,
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
            }
        )
    return rows


def _read_shapefile(path_shp: str) -> List[Dict[str, Any]]:
    try:
        import shapefile  # pyshp
    except ImportError:
        raise RuntimeError(
            "Reading Shapefile requires 'pyshp'. Install with: py -m pip install pyshp"
        )

    if not _os_path.exists(path_shp):
        raise FileNotFoundError(f"Shapefile not found: {path_shp}")

    r = shapefile.Reader(path_shp)
    fields = [f[0] for f in r.fields if f[0] != "DeletionFlag"]
    rows: List[Dict[str, Any]] = []

    def props_to_tile(pr: Dict[str, Any]) -> Tuple[int, int] | None:
        # Normalize keys to handle case differences
        lower = {k.lower(): v for k, v in pr.items()}
        # Name like '091_078' or '91_91'
        for k in ("name", "Name"):
            if k in pr:
                s = str(pr[k]).strip()
                for sep in ("_", " "):
                    if sep in s:
                        a, b = s.split(sep, 1)
                        if a.strip().isdigit() and b.strip().isdigit():
                            return int(a), int(b)
        # Direct tile id field
        for k in ("tile_id", "tileid", "tile"):
            if k in lower:
                s = str(lower[k]).strip().replace("_", "")
                if len(s) == 6 and s.isdigit():
                    return int(s[:3]), int(s[3:])
        # Path/Row variants
        candidates = [("path", "row"), ("wrs_path", "wrs_row"), ("PATH", "ROW")]
        for kp, kr in candidates:
            pv = pr.get(kp) if kp in pr else pr.get(kp.upper()) or pr.get(kp.lower())
            rv = pr.get(kr) if kr in pr else pr.get(kr.upper()) or pr.get(kr.lower())
            if pv is not None and rv is not None:
                try:
                    return int(pv), int(rv)
                except Exception:
                    pass
        # Concatenated PR variants
        for k in ("PR", "pr", "pathrow", "PATHROW", "PATH_ROW", "PathRow"):
            if k in pr:
                s = str(pr[k]).strip().replace("_", "")
                if len(s) == 6 and s.isdigit():
                    return int(s[:3]), int(s[3:])
        # Generic: look for any field whose value is a 6-digit numeric (prefer keys containing tile/pr/pathrow)
        preferred_keys = [
            k
            for k in pr.keys()
            if any(x in k.lower() for x in ["tile", "pr", "pathrow"])
        ]
        for k in preferred_keys + list(pr.keys()):
            try:
                s = str(pr[k]).strip().replace("_", "")
            except Exception:
                continue
            if len(s) == 6 and s.isdigit():
                return int(s[:3]), int(s[3:])
        # Parse from PopupInfo HTML blob if present
        try:
            import re

            info = pr.get("PopupInfo") or pr.get("popupinfo") or lower.get("popupinfo")
            if info:
                m_path = re.search(r"PATH[^0-9]*([0-9]{1,3})", str(info))
                m_row = re.search(r"ROW[^0-9]*([0-9]{1,3})", str(info))
                if m_path and m_row:
                    return int(m_path.group(1)), int(m_row.group(1))
        except Exception:
            pass
        return None

    for sr in r.shapeRecords():
        rec_map = (
            sr.record.as_dict()
            if hasattr(sr.record, "as_dict")
            else {k: sr.record[i] for i, k in enumerate(fields)}
        )
        pr = props_to_tile(rec_map)
        if not pr:
            continue
        p, rrow = pr
        xs: List[float] = []
        ys: List[float] = []
        geom = sr.shape.__geo_interface__
        for x, y in _coords_from_geom(geom):
            xs.append(float(x))
            ys.append(float(y))
        if not xs:
            continue
        min_lon, max_lon = min(xs), max(xs)
        min_lat, max_lat = min(ys), max(ys)
        tile_id = f"{p:03d}{rrow:03d}"
        rows.append(
            {
                "tile_id": tile_id,
                "path": p,
                "row": rrow,
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
            }
        )
    if not rows:
        # Diagnostic output to help map fields
        try:
            sample = r.shapeRecords()[0].record
            rec_map = (
                sample.as_dict()
                if hasattr(sample, "as_dict")
                else {k: sample[i] for i, k in enumerate(fields)}
            )
            print(
                "Warning: No tiles extracted from shapefile. Available fields:", fields
            )
            print("Sample record:", rec_map)
        except Exception:
            print("Warning: No tiles extracted and no sample record available.")
    return rows


def write_csv(rows: List[Dict[str, Any]], csv_path: str) -> None:
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "tile_id",
                "path",
                "row",
                "min_lon",
                "min_lat",
                "max_lon",
                "max_lat",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_sqlite(rows: List[Dict[str, Any]], sqlite_path: str) -> None:
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    con = sqlite3.connect(sqlite_path)
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS wrs2_tile_bounds (
                tile_id TEXT PRIMARY KEY,
                path INTEGER NOT NULL,
                row INTEGER NOT NULL,
                min_lon REAL NOT NULL,
                min_lat REAL NOT NULL,
                max_lon REAL NOT NULL,
                max_lat REAL NOT NULL
            )
            """
        )
        cur.execute("DELETE FROM wrs2_tile_bounds")
        cur.executemany(
            "INSERT INTO wrs2_tile_bounds (tile_id, path, row, min_lon, min_lat, max_lon, max_lat) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r["tile_id"],
                    int(r["path"]),
                    int(r["row"]),
                    float(r["min_lon"]),
                    float(r["min_lat"]),
                    float(r["max_lon"]),
                    float(r["max_lat"]),
                )
                for r in rows
            ],
        )
        con.commit()
    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build WRS-2 per-tile bounding boxes from GeoJSON or Shapefile"
    )
    p.add_argument(
        "input_path", help="Path to WRS-2 GeoJSON (.geojson) or Shapefile (.shp)"
    )
    p.add_argument(
        "--csv",
        dest="csv_out",
        default="data/wrs2_tile_bounds.csv",
        help="Output CSV path",
    )
    p.add_argument(
        "--sqlite",
        dest="sqlite_out",
        help="Optional SQLite DB path to write table wrs2_tile_bounds",
    )
    return p


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    in_path = args.input_path
    if in_path.lower().endswith(".shp"):
        rows = _read_shapefile(in_path)
    else:
        rows = process_geojson(in_path)
    print(f"Computed {len(rows)} tile bbox rows")
    write_csv(rows, args.csv_out)
    print(f"Wrote CSV: {args.csv_out}")
    if args.sqlite_out:
        write_sqlite(rows, args.sqlite_out)
        print(f"Wrote SQLite: {args.sqlite_out} (table wrs2_tile_bounds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

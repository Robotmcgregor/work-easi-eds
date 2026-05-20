#!/usr/bin/env python
"""
Import WRS-2 per-tile bounding boxes into the app database by updating landsat_tiles.bounds_geojson
and optionally center_lat/center_lon.

Typical workflow (PowerShell):
  # 1) Build bbox CSV from WRS-2 GeoJSON
  py scripts/wrs2_tile_bounds.py data/WRS2.geojson --csv data/wrs2_tile_bounds.csv

  # 2) Import into DB (only update tiles missing bounds; also update center)
  py scripts/import_wrs2_bounds_to_db.py --csv data/wrs2_tile_bounds.csv --only-missing --update-center

Environment:
  DATABASE_URL must point to your Postgres DB, e.g.
    postgresql://eds_user:eds_password@localhost:5432/eds_database
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database.connection import get_db, init_database
from src.database.models import LandsatTile


def bbox_to_polygon(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> Dict:
    # Return GeoJSON Polygon for bbox
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ],
    }


def import_csv(
    csv_path: str, only_missing: bool, update_center: bool
) -> Dict[str, int]:
    stats = {"rows": 0, "updated": 0, "skipped": 0, "missing": 0}

    with open(csv_path, "r", encoding="utf-8") as f, get_db() as session:
        rdr = csv.DictReader(f)
        for row in rdr:
            stats["rows"] += 1
            tile_id = row["tile_id"].strip()
            min_lon = float(row["min_lon"])  # type: ignore
            min_lat = float(row["min_lat"])  # type: ignore
            max_lon = float(row["max_lon"])  # type: ignore
            max_lat = float(row["max_lat"])  # type: ignore

            tile: LandsatTile | None = (
                session.query(LandsatTile)
                .filter(LandsatTile.tile_id == tile_id)
                .first()
            )
            if not tile:
                stats["missing"] += 1
                continue

            if only_missing and tile.bounds_geojson:
                stats["skipped"] += 1
                continue

            poly = bbox_to_polygon(min_lon, min_lat, max_lon, max_lat)
            tile.bounds_geojson = json.dumps(poly)

            if update_center:
                tile.center_lon = (min_lon + max_lon) / 2.0
                tile.center_lat = (min_lat + max_lat) / 2.0

            stats["updated"] += 1

        # commit once at the end for speed
        session.commit()

    return stats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Import WRS-2 tile bboxes into landsat_tiles table"
    )
    p.add_argument(
        "--csv",
        required=True,
        help="Path to wrs2_tile_bounds.csv produced by wrs2_tile_bounds.py",
    )
    p.add_argument(
        "--only-missing",
        action="store_true",
        help="Only update tiles where bounds_geojson is NULL/empty",
    )
    p.add_argument(
        "--update-center",
        action="store_true",
        help="Also update center_lat/center_lon from bbox center",
    )
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Ensure DB is initialized (creates tables if missing)
    init_database(create_tables=True)

    stats = import_csv(args.csv, args.only_missing, args.update_center)
    print(
        f"Processed {stats['rows']} CSV rows; updated={stats['updated']} skipped={stats['skipped']} missing_tile={stats['missing']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

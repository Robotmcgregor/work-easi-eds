#!/usr/bin/env python
"""
STAC discovery helper for Landsat via LandsatLook STAC server.

Examples (PowerShell):
  py scripts/stac_discovery.py search-bbox --start 2023-07-01 --end 2023-07-31 --min-lon 146 --min-lat -28 --max-lon 148.5 --max-lat -26 --limit 10
  py scripts/stac_discovery.py search-recent --days 30 --limit 20
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.stac_client import STACClient
from src.utils.tile_lookup import get_tile_bbox


def _date_range(start: str, end: str) -> str:
    # Validate and format STAC datetime range with explicit times to ensure server filtering
    s = datetime.strptime(start, "%Y-%m-%d").date().isoformat()
    e = datetime.strptime(end, "%Y-%m-%d").date().isoformat()
    return f"{s}T00:00:00Z/{e}T23:59:59Z"


def cmd_search_bbox(args: argparse.Namespace) -> int:
    client = STACClient()
    bbox = [args.min_lon, args.min_lat, args.max_lon, args.max_lat]
    # Use CQL2 filter for robust server-side filtering
    collections = args.collections
    start_end = _date_range(args.start, args.end).split("/")
    start_iso, end_iso = start_end[0], start_end[1]
    # s_intersects on bbox is specified using the "bbox" field in CQL2 with geometry property
    filter_obj = {
        "op": "and",
        "args": [
            {"op": "between", "args": [{"property": "datetime"}, start_iso, end_iso]},
            {
                "op": "s_intersects",
                "args": [
                    {"property": "geometry"},
                    {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [bbox[0], bbox[1]],
                                [bbox[2], bbox[1]],
                                [bbox[2], bbox[3]],
                                [bbox[0], bbox[3]],
                                [bbox[0], bbox[1]],
                            ]
                        ],
                    },
                ],
            },
            {"op": "<", "args": [{"property": "eo:cloud_cover"}, 100]},
        ],
    }
    res = client.search_cql2(
        collections=collections, filter_obj=filter_obj, limit=args.limit
    )
    feats = res.get("features", [])
    print(f"Found {len(feats)} STAC item(s)")
    for it in feats:
        print(it.get("id"), it.get("properties", {}).get("datetime"))
    return 0


def cmd_search_recent(args: argparse.Namespace) -> int:
    from datetime import timedelta, date

    client = STACClient()
    end = date.today()
    start = end - timedelta(days=args.days)
    start_iso = f"{start.isoformat()}T00:00:00Z"
    end_iso = f"{end.isoformat()}T23:59:59Z"
    collections = args.collections
    filter_obj = {
        "op": "and",
        "args": [
            {"op": "between", "args": [{"property": "datetime"}, start_iso, end_iso]},
            {"op": "<", "args": [{"property": "eo:cloud_cover"}, 100]},
        ],
    }
    res = client.search_cql2(
        collections=collections, filter_obj=filter_obj, limit=args.limit
    )
    feats = res.get("features", [])
    print(f"Found {len(feats)} recent STAC item(s)")
    for it in feats:
        print(it.get("id"), it.get("properties", {}).get("datetime"))
    return 0


def _parse_tile(tile: str) -> tuple[int, int]:
    t = tile.strip()
    if "_" in t:
        p, r = t.split("_", 1)
    else:
        if len(t) != 6:
            raise ValueError("Tile must be 6 digits (PPPRRR) or PPP_RRR")
        p, r = t[:3], t[3:]
    return int(p), int(r)


def cmd_search_tile(args: argparse.Namespace) -> int:
    client = STACClient()
    path, row = _parse_tile(args.tile_id)
    collections = args.collections
    start_end = _date_range(args.start, args.end).split("/")
    start_iso, end_iso = start_end[0], start_end[1]
    filter_obj = {
        "op": "and",
        "args": [
            {"op": "between", "args": [{"property": "datetime"}, start_iso, end_iso]},
            {"op": "=", "args": [{"property": "landsat:wrs_path"}, path]},
            {"op": "=", "args": [{"property": "landsat:wrs_row"}, row]},
            {"op": "<", "args": [{"property": "eo:cloud_cover"}, args.cloud_lt]},
        ],
    }
    res = client.search_cql2(
        collections=collections, filter_obj=filter_obj, limit=args.limit
    )
    feats = res.get("features", [])
    print(f"Found {len(feats)} STAC item(s) for tile {args.tile_id}")
    for it in feats:
        props = it.get("properties", {})
        print(
            it.get("id"), props.get("datetime"), f"cloud={props.get('eo:cloud_cover')}"
        )
    return 0


def cmd_search_bbox_tile(args: argparse.Namespace) -> int:
    client = STACClient()
    bbox = get_tile_bbox(args.tile_id)
    if not bbox:
        print(
            f"No bbox found in DB for tile {args.tile_id}. Run bbox import (see README-create-bbox.md)."
        )
        return 2
    min_lon, min_lat, max_lon, max_lat = bbox
    start_end = _date_range(args.start, args.end).split("/")
    start_iso, end_iso = start_end[0], start_end[1]
    collections = args.collections
    filter_obj = {
        "op": "and",
        "args": [
            {"op": "between", "args": [{"property": "datetime"}, start_iso, end_iso]},
            {
                "op": "s_intersects",
                "args": [
                    {"property": "geometry"},
                    {
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
                    },
                ],
            },
            {"op": "<", "args": [{"property": "eo:cloud_cover"}, 100]},
        ],
    }
    res = client.search_cql2(
        collections=collections, filter_obj=filter_obj, limit=args.limit
    )
    feats = res.get("features", [])
    print(f"Found {len(feats)} STAC item(s) for tile {args.tile_id}")
    for it in feats:
        props = it.get("properties", {})
        print(
            it.get("id"), props.get("datetime"), f"cloud={props.get('eo:cloud_cover')}"
        )
    return 0


def cmd_collections(args: argparse.Namespace) -> int:
    client = STACClient()
    cols = client.list_collections()
    coll_list = cols.get("collections", [])
    print(f"Found {len(coll_list)} collection(s)")
    for c in coll_list:
        print(c.get("id"), "-", c.get("title") or "")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Landsat STAC discovery")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_bbox = sub.add_parser(
        "search-bbox", help="Search Landsat STAC by bbox and date range"
    )
    p_bbox.add_argument("--start", required=True)
    p_bbox.add_argument("--end", required=True)
    p_bbox.add_argument("--min-lon", type=float, dest="min_lon", required=True)
    p_bbox.add_argument("--min-lat", type=float, dest="min_lat", required=True)
    p_bbox.add_argument("--max-lon", type=float, dest="max_lon", required=True)
    p_bbox.add_argument("--max-lat", type=float, dest="max_lat", required=True)
    p_bbox.add_argument(
        "--collections", nargs="+", help="STAC collections (omit to search all)"
    )
    p_bbox.add_argument("--limit", type=int, default=10)
    p_bbox.set_defaults(func=cmd_search_bbox)

    p_recent = sub.add_parser("search-recent", help="List recent Landsat STAC items")
    p_recent.add_argument("--days", type=int, default=30)
    p_recent.add_argument(
        "--collections", nargs="+", help="STAC collections (omit to search all)"
    )
    p_recent.add_argument("--limit", type=int, default=20)
    p_recent.set_defaults(func=cmd_search_recent)

    p_tile = sub.add_parser(
        "search-tile", help="Search by WRS-2 tile (PPPRRR or PPP_RRR) and date range"
    )
    p_tile.add_argument("tile_id")
    p_tile.add_argument("--start", required=True)
    p_tile.add_argument("--end", required=True)
    p_tile.add_argument("--cloud-lt", type=int, default=100, dest="cloud_lt")
    p_tile.add_argument(
        "--collections", nargs="+", help="STAC collections (omit to search all)"
    )
    p_tile.add_argument("--limit", type=int, default=20)
    p_tile.set_defaults(func=cmd_search_tile)

    p_cols = sub.add_parser("collections", help="List available STAC collection IDs")
    p_cols.set_defaults(func=cmd_collections)

    p_bbox_tile = sub.add_parser(
        "search-bbox-tile", help="Search by DB bbox for tile and date range"
    )
    p_bbox_tile.add_argument("tile_id")
    p_bbox_tile.add_argument("--start", required=True)
    p_bbox_tile.add_argument("--end", required=True)
    p_bbox_tile.add_argument(
        "--collections", nargs="+", help="STAC collections (omit to search all)"
    )
    p_bbox_tile.add_argument("--limit", type=int, default=20)
    p_bbox_tile.set_defaults(func=cmd_search_bbox_tile)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

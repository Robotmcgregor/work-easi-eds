#!/usr/bin/env python
"""
USGS CLI - Lightweight wrapper exposing only USGS-related commands from eds_cli.py

Commands:
  - usgs-login
  - usgs-search
  - usgs-download

This script reuses the command handlers implemented in scripts/eds_cli.py to avoid duplication.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.eds_cli import (
    cmd_usgs_login,
    cmd_usgs_search,
    cmd_usgs_download,
    cmd_usgs_search_bbox,
    cmd_usgs_search_recent,
    cmd_usgs_search_bbox_tile,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="USGS CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser(
        "usgs-login", help="Test USGS M2M login using .env or flags"
    )
    p_login.add_argument("--username", help="USGS username (overrides .env)")
    p_login.add_argument("--password", help="USGS password (overrides .env)")
    p_login.add_argument(
        "--token", help="USGS application token (overrides .env USGS_TOKEN)"
    )
    p_login.add_argument("--endpoint", help="USGS M2M endpoint override")
    p_login.set_defaults(func=cmd_usgs_login)

    p_search = sub.add_parser(
        "usgs-search", help="Search USGS M2M by WRS-2 tile and date range"
    )
    p_search.add_argument("tile_id")
    p_search.add_argument("--start", required=True)
    p_search.add_argument("--end", required=True)
    p_search.add_argument(
        "--dataset", help="Dataset name (e.g., LANDSAT_8_C2_L1, LANDSAT_9_C2_L1)"
    )
    p_search.add_argument("--node", default="EE", help="Node (default EE)")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.set_defaults(func=cmd_usgs_search)

    p_dl = sub.add_parser(
        "usgs-download",
        help="Download from USGS M2M for a tile and date range (TOA: *_C2_L1)",
    )
    p_dl.add_argument("tile_id")
    p_dl.add_argument("--start", required=True)
    p_dl.add_argument("--end", required=True)
    p_dl.add_argument(
        "--dataset", help="Dataset name (default from config; e.g., LANDSAT_8_C2_L1)"
    )
    p_dl.add_argument("--node", default="EE")
    p_dl.add_argument("--limit", type=int, default=10)
    p_dl.add_argument("--dest", default="data/cache")
    p_dl.set_defaults(func=cmd_usgs_download)

    p_bbox = sub.add_parser(
        "usgs-search-bbox", help="Search by bounding box and date range"
    )
    p_bbox.add_argument("--dataset", help="Dataset name or id")
    p_bbox.add_argument("--node", default="EE")
    p_bbox.add_argument("--start", required=True)
    p_bbox.add_argument("--end", required=True)
    p_bbox.add_argument("--min-lon", type=float, dest="min_lon", required=True)
    p_bbox.add_argument("--min-lat", type=float, dest="min_lat", required=True)
    p_bbox.add_argument("--max-lon", type=float, dest="max_lon", required=True)
    p_bbox.add_argument("--max-lat", type=float, dest="max_lat", required=True)
    p_bbox.add_argument("--limit", type=int, default=50)
    p_bbox.set_defaults(func=cmd_usgs_search_bbox)

    p_recent = sub.add_parser(
        "usgs-search-recent", help="List recent scenes globally (no spatial filter)"
    )
    p_recent.add_argument("--dataset", help="Dataset name or id")
    p_recent.add_argument("--node", default="EE")
    p_recent.add_argument("--days", type=int, default=14)
    p_recent.add_argument("--limit", type=int, default=50)
    p_recent.set_defaults(func=cmd_usgs_search_recent)

    p_bbox_tile = sub.add_parser(
        "usgs-search-bbox-tile", help="Search by tile_id using DB bbox and date range"
    )
    p_bbox_tile.add_argument("tile_id")
    p_bbox_tile.add_argument("--dataset", help="Dataset name or id")
    p_bbox_tile.add_argument("--node", default="EE")
    p_bbox_tile.add_argument("--start", required=True)
    p_bbox_tile.add_argument("--end", required=True)
    p_bbox_tile.add_argument("--limit", type=int, default=50)
    p_bbox_tile.set_defaults(func=cmd_usgs_search_bbox_tile)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

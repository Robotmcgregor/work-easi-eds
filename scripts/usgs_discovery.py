#!/usr/bin/env python
"""
USGS M2M discovery helpers: list datasets and probe search for a WRS-2 tile.

Usage examples (PowerShell):
  py scripts/usgs_discovery.py datasets --filter landsat
  py scripts/usgs_discovery.py search-wrs2 089078 --start 2023-07-01 --end 2023-07-31 --dataset LANDSAT_8_C2_L1

Reads USGS credentials and endpoint from .env or environment.
"""
from __future__ import annotations

import os
import sys
import argparse
import requests
from datetime import datetime

# Load .env if available
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

BASE = (os.environ.get("USGS_M2M_ENDPOINT") or "https://m2m.cr.usgs.gov/api/api/json/stable/").rstrip('/') + '/'
USERNAME = os.environ.get("USGS_USERNAME", "")
TOKEN = os.environ.get("USGS_TOKEN", "")
PASSWORD = os.environ.get("USGS_PASSWORD", "")


def _login() -> str:
    if TOKEN:
        r = requests.post(BASE + "login-token", json={"username": USERNAME, "token": TOKEN}, timeout=30)
        r.raise_for_status()
        return r.json()["data"]
    r = requests.post(BASE + "login", json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def cmd_datasets(args: argparse.Namespace) -> int:
    api_key = _login()
    # Try datasets endpoint with filter; fall back to dataset-search
    tried = []
    payloads = []
    filt = (args.filter or "").strip()
    # Common payload forms observed in M2M
    payloads.append({"node": args.node, "onlyPublic": False, "datasetName": filt})
    payloads.append({"node": args.node, "onlyPublic": False})
    for ep in ("datasets", "dataset-search"):
        url = BASE + ep
        for pl in payloads:
            tried.append({"url": url, "payload": pl})
            resp = requests.post(url, headers={"X-Auth-Token": api_key}, json=pl, timeout=60)
            if resp.status_code == 404:
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            items = (data.get("data") or [])
            if isinstance(items, dict):
                items = items.get("results") or []
            if items:
                for it in items[: args.limit]:
                    name = it.get("datasetName") or it.get("collectionName") or it.get("name")
                    dsid = it.get("datasetId") or it.get("id")
                    print(f"{name} | id={dsid}")
                _ = requests.post(BASE + "logout", headers={"X-Auth-Token": api_key}, json={}, timeout=30)
                return 0
    print("No datasets returned; tried:")
    for t in tried:
        print(t)
    _ = requests.post(BASE + "logout", headers={"X-Auth-Token": api_key}, json={}, timeout=30)
    return 1


def cmd_search_wrs2(args: argparse.Namespace) -> int:
    api_key = _login()
    p = int(args.tile_id[:3]); r = int(args.tile_id[3:6])
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    filter_types = ["WRS2", "Wrs2", "Wrs2PathRow"]
    for ft in filter_types:
        payload = {
            "datasetName": args.dataset,
            "node": args.node,
            "maxResults": args.limit,
            "startingNumber": 1,
            "temporalFilter": {"startDate": start.strftime('%Y-%m-%d'), "endDate": end.strftime('%Y-%m-%d')},
            "cloudCoverFilter": {"min": 0, "max": 100},
            "includeUnknownCloudCover": True,
            "spatialFilter": {"filterType": ft, "path": str(p), "row": str(r)},
            "sortOrder": "DESC",
        }
        for ep in ("search", "scene-search"):
            url = BASE + ep
            resp = requests.post(url, headers={"X-Auth-Token": api_key, "Content-Type": "application/json"}, json=payload, timeout=60)
            if resp.status_code == 404:
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            results = (data.get("data", {}) or {}).get("results", [])
            if results:
                print(f"Found {len(results)} scene(s) via {ep} + {ft}")
                for s in results[: args.limit]:
                    print(s.get('entityId') or s.get('entity_id'), s.get('displayId') or s.get('display_id'))
                _ = requests.post(BASE + "logout", headers={"X-Auth-Token": api_key}, json={}, timeout=30)
                return 0
    print("No scenes found across filter variants.")
    _ = requests.post(BASE + "logout", headers={"X-Auth-Token": api_key}, json={}, timeout=30)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="USGS discovery helpers")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ds = sub.add_parser("datasets", help="List datasets; optionally filter by name fragment")
    p_ds.add_argument("--filter", help="Filter string, e.g., landsat")
    p_ds.add_argument("--node", default="EE")
    p_ds.add_argument("--limit", type=int, default=50)
    p_ds.set_defaults(func=cmd_datasets)

    p_sw = sub.add_parser("search-wrs2", help="Search scenes by WRS-2 path/row/date")
    p_sw.add_argument("tile_id")
    p_sw.add_argument("--start", required=True)
    p_sw.add_argument("--end", required=True)
    p_sw.add_argument("--dataset", required=True)
    p_sw.add_argument("--node", default="EE")
    p_sw.add_argument("--limit", type=int, default=10)
    p_sw.set_defaults(func=cmd_search_wrs2)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

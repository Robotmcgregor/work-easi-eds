
#!/usr/bin/env python
"""
Summarize TOA (Landsat Collection 2 Level-1) availability per Australian tile for a given date range.

This uses STAC CQL2 filtering on wrs_path/wrs_row (avoids bbox issues) and counts items per tile.

Examples (PowerShell):
  # Last 2 years per tile, write CSV summary
  py scripts/toa_availability.py --years-back 2 --csv data/aus_lsat_tile_summary.csv --limit 200

  # Fixed date range and custom STAC endpoint (Planetary Computer)
  py scripts/toa_availability.py --start 2023-07-01 --end 2025-06-30 --stac-base https://planetarycomputer.microsoft.com/api/stac/v1 --csv data/aus_lsat_tile_summary.csv

Notes:
  - Default STAC endpoint is LandsatLook. You can override with --stac-base.
  - We query the combined collection 'landsat-c2l1' (Collection 2 Level-1) by default (TOA).
  - Limit applies per tile. For two years, 200 is typically sufficient per path/row.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import csv
import sys
from typing import Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database.connection import get_db
from src.database.models import LandsatTile
from src.utils.stac_client import STACClient
from src.utils.tile_lookup import get_tile_bbox


def _parse_dates(args: argparse.Namespace) -> Tuple[str, str]:
    if args.start and args.end:
        try:
            s = datetime.strptime(args.start, "%Y-%m-%d").date()
            e = datetime.strptime(args.end, "%Y-%m-%d").date()
        except Exception:
            raise SystemExit("Start/End must be YYYY-MM-DD")
    else:
        days = int(round(float(args.years_back) * 365))
        e = date.today()
        s = e - timedelta(days=max(1, days))
    start_iso = f"{s.isoformat()}T00:00:00Z"
    end_iso = f"{e.isoformat()}T23:59:59Z"
    return start_iso, end_iso


def _filter_for_tile(path: int, row: int, start_iso: str, end_iso: str, collections: Optional[List[str]] = None):
    clauses: List[dict] = [
        {"op": "between", "args": [{"property": "datetime"}, start_iso, end_iso]},
        {"op": "=", "args": [{"property": "landsat:wrs_path"}, int(path)]},
        {"op": "=", "args": [{"property": "landsat:wrs_row"}, int(row)]},
        {"op": "<", "args": [{"property": "eo:cloud_cover"}, 100]},
    ]
    if collections:
        clauses.append({"op": "in", "args": [{"property": "collection"}, list(collections)]})
    return {"op": "and", "args": clauses}


@dataclass
class TileSummary:
    tile_id: str
    path: int
    row: int
    count: int
    first_date: Optional[str]
    last_date: Optional[str]


def iter_au_tiles() -> Iterable[LandsatTile]:
    with get_db() as session:
        # Assume landsat_tiles table contains AU tiles only in this deployment; keep simple ordering
        for t in session.query(LandsatTile).order_by(LandsatTile.path, LandsatTile.row).all():
            yield t


def summarize_tile(client: STACClient, tile: LandsatTile, start_iso: str, end_iso: str, collections: List[str], limit: int) -> TileSummary:
    filt = _filter_for_tile(tile.path, tile.row, start_iso, end_iso, collections)
    res = client.search_cql2(collections=collections, filter_obj=filt, limit=limit)
    feats = res.get("features", []) or []
    # Sort by datetime
    def _dt(it):
        try:
            return it.get("properties", {}).get("datetime") or ""
        except Exception:
            return ""
    feats_sorted = sorted(feats, key=_dt)
    first_dt = feats_sorted[0]["properties"].get("datetime") if feats_sorted else None
    last_dt = feats_sorted[-1]["properties"].get("datetime") if feats_sorted else None
    return TileSummary(tile_id=tile.tile_id, path=tile.path, row=tile.row, count=len(feats), first_date=first_dt, last_date=last_dt)


def write_csv(summaries: List[TileSummary], csv_path: str) -> None:
    out_dir = Path(csv_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tile_id", "path", "row", "count", "first_date", "last_date"])
        for s in summaries:
            w.writerow([s.tile_id, s.path, s.row, s.count, s.first_date or "", s.last_date or ""])


def _parse_tile_id(tile: str) -> Tuple[int, int]:
    t = tile.strip()
    if "_" in t:
        p, r = t.split("_", 1)
    else:
        if len(t) != 6 or not t.isdigit():
            raise ValueError("tile_id must be 6 digits (PPPRRR) or PPP_RRR")
        p, r = t[:3], t[3:]
    return int(p), int(r)


def _infer_sensor(item: dict) -> str:
    props = item.get("properties", {})
    plat = (props.get("platform") or "").lower()
    if "landsat-5" in plat:
        return "L5"
    if "landsat-7" in plat:
        return "L7"
    if "landsat-8" in plat:
        return "L8"
    if "landsat-9" in plat:
        return "L9"
    sid = item.get("id") or ""
    if sid.startswith("LT05"):
        return "L5"
    if sid.startswith("LE07"):
        return "L7"
    if sid.startswith("LC08"):
        return "L8"
    if sid.startswith("LC09"):
        return "L9"
    return "L?"


def _acq_date_from_item(item: dict) -> str:
    """Extract acquisition date as YYYY-MM-DD, preferring product/scene id pattern over properties.datetime."""
    props = item.get("properties", {})
    pid = props.get("landsat:landsat_product_id") or props.get("landsat:scene_id") or item.get("id") or ""
    import re
    m = re.search(r"_(\d{8})_", str(pid))
    if m:
        ymd = m.group(1)
        return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    dt = props.get("datetime") or ""
    return dt[:10] if isinstance(dt, str) and len(dt) >= 10 else ""


def cmd_list_tile_items(args: argparse.Namespace) -> int:
    start_iso, end_iso = _parse_dates(args)
    path, row = _parse_tile_id(args.tile_id)
    client = STACClient(base_url=args.stac_base)
    collections = _collections_for_server(args.stac_base, args.sensors, args.collections)

    # Build base filter (time + path/row + cloud); we'll query per collection to avoid cross-collection bleed-through
    base_filt = _filter_for_tile(path, row, start_iso, end_iso, None)
    feats: List[dict] = []
    # Prefer standard search with 'query' on Earth Search to ensure collection/path/row are respected
    is_earthsearch = ("earth-search" in (args.stac_base or "")) or ("element84" in (args.stac_base or ""))
    bbox = None if getattr(args, 'no_bbox', False) else get_tile_bbox(args.tile_id)
    if getattr(args, 'only_bbox', False):
        dt_range = f"{start_iso}/{end_iso}"
        if collections:
            for coll in collections:
                res = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit, query=None)
                feats.extend(res.get("features", []) or [])
        else:
            res = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit, query=None)
            feats.extend(res.get("features", []) or [])
    elif collections:
        for coll in collections:
            if is_earthsearch:
                dt_range = f"{start_iso}/{end_iso}"
                # Try landsat:* keys
                res = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                     query={"landsat:wrs_path": {"eq": int(path)}, "landsat:wrs_row": {"eq": int(row)}})
                feats.extend(res.get("features", []) or [])
                # Also try plain wrs_* keys (used by some catalogs)
                res2 = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                      query={"wrs_path": {"eq": int(path)}, "wrs_row": {"eq": int(row)}})
                feats.extend(res2.get("features", []) or [])
                # And try namespaced wrs:path/wrs:row
                res3 = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                      query={"wrs:path": {"eq": int(path)}, "wrs:row": {"eq": int(row)}})
                feats.extend(res3.get("features", []) or [])
                # And landsat:path/landsat:row variants
                res4 = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                      query={"landsat:path": {"eq": int(path)}, "landsat:row": {"eq": int(row)}})
                feats.extend(res4.get("features", []) or [])
                continue
            else:
                res = client.search_cql2(collections=[coll], filter_obj=base_filt, limit=args.limit)
            feats.extend(res.get("features", []) or [])
    else:
        if is_earthsearch:
            dt_range = f"{start_iso}/{end_iso}"
            res = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                 query={"landsat:wrs_path": {"eq": int(path)}, "landsat:wrs_row": {"eq": int(row)}})
            feats.extend(res.get("features", []) or [])
            res2 = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                  query={"wrs_path": {"eq": int(path)}, "wrs_row": {"eq": int(row)}})
            feats.extend(res2.get("features", []) or [])
            res3 = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                  query={"wrs:path": {"eq": int(path)}, "wrs:row": {"eq": int(row)}})
            feats.extend(res3.get("features", []) or [])
            res4 = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                  query={"landsat:path": {"eq": int(path)}, "landsat:row": {"eq": int(row)}})
            feats.extend(res4.get("features", []) or [])
            # already extended; skip cql2
            pass
        else:
            res = client.search_cql2(collections=None, filter_obj=base_filt, limit=args.limit)
            feats.extend(res.get("features", []) or [])
    # Filter to Landsat by ID prefix as a final guard (removes Sentinel spillover)
    allowed_prefixes = []
    for s in (args.sensors or []):
        s = s.lower()
        if s == "l5": allowed_prefixes.append("LT05")
        elif s == "l7": allowed_prefixes.append("LE07")
        elif s == "l8": allowed_prefixes.append("LC08")
        elif s == "l9": allowed_prefixes.append("LC09")
    if allowed_prefixes:
        feats = [it for it in feats if any((it.get("id") or "").startswith(p) for p in allowed_prefixes)]

    # Normalize rows
    rows: List[Tuple[str, int, int, str, str, str, str, float]] = []
    for it in feats:
        props = it.get("properties", {})
        acq = _acq_date_from_item(it)
        year = acq[:4] if len(acq) >= 4 else ""
        sensor = _infer_sensor(it)
        cloud = props.get("eo:cloud_cover")
        try:
            cloud_f = float(cloud) if cloud is not None else float("nan")
        except Exception:
            cloud_f = float("nan")
        coll = (it.get("collection") or (collections[0] if collections else ""))
        rows.append((args.tile_id, path, row, year, sensor, acq, coll, it.get("id") or "", cloud_f))

    # Sort by datetime
    rows.sort(key=lambda r: r[5])

    # Print
    print(f"Found {len(rows)} item(s) for tile {args.tile_id}")
    for r in rows:
        tile_id, p, rw, year, sensor, dt, coll, scene_id, cloud = r
        cloud_txt = "" if cloud != cloud else f" cloud={cloud:.2f}"
        print(f"{tile_id},{p:03d},{rw:03d},{year},{sensor},{dt},{coll},{scene_id}{cloud_txt}")

    # CSV output
    if args.csv:
        out_dir = Path(args.csv).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["tile_id", "path", "row", "year", "sensor", "acq_date", "collection", "scene_id", "cloud_cover"])
            for r in rows:
                w.writerow(list(r))
        print(f"Wrote CSV: {args.csv}")
    return 0


def _collections_for_server(base_url: str, sensors: Optional[List[str]], explicit_collections: Optional[List[str]]) -> List[str]:
    # If user provided collections explicitly, honor them
    if explicit_collections:
        return explicit_collections
    # Normalize sensors
    sensors = [s.lower() for s in (sensors or [])]
    # Heuristics for known servers
    is_earthsearch = "earth-search" in base_url or "element84" in base_url
    is_pc = "planetarycomputer" in base_url
    # Default collection when nothing specified
    if not sensors:
        if is_earthsearch:
            # Combined would require listing multiple; default to L8+L9 (modern)
            return ["landsat-8-c2-l1", "landsat-9-c2-l1"]
        else:
            return ["landsat-c2l1"]
    # Build collections per sensor
    cols: List[str] = []
    for s in sensors:
        if is_earthsearch:
            if s in ("l5", "landsat5", "landsat-5"):
                cols.append("landsat-5-c2-l1")
            elif s in ("l7", "landsat7", "landsat-7"):
                cols.append("landsat-7-c2-l1")
            elif s in ("l8", "landsat8", "landsat-8"):
                cols.append("landsat-8-c2-l1")
            elif s in ("l9", "landsat9", "landsat-9"):
                cols.append("landsat-9-c2-l1")
        else:
            # LandsatLook typically aggregates under landsat-c2l1; no clear per-sensor split
            # We'll return the aggregate once if any Landsat sensor requested
            if "landsat-c2l1" not in cols:
                cols.append("landsat-c2l1")
    # Deduplicate while preserving order
    seen = set(); out: List[str] = []
    for c in cols:
        if c not in seen:
            out.append(c); seen.add(c)
    return out


def _ensure_item_with_assets(client: STACClient, base_url: str, item: dict) -> dict:
    # If assets present, return as-is; else try fetching by collection/items/id
    if isinstance(item, dict) and item.get("assets"):
        return item
    coll = item.get("collection")
    item_id = item.get("id")
    if not coll or not item_id:
        return item
    import requests
    url = f"{base_url.rstrip('/')}/collections/{coll}/items/{item_id}"
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception:
        return item


def _select_assets_for_toa(item: dict, also_angles: bool, also_qa: bool) -> List[Tuple[str, str]]:
    # Returns list of (filename, href)
    assets = item.get("assets", {}) or {}
    selected: List[Tuple[str, str]] = []
    # Pick MTL first
    for k, a in assets.items():
        href = a.get("href") if isinstance(a, dict) else None
        if not href:
            continue
        kl = str(k).lower()
        if "mtl" in kl and href.lower().endswith("mtl.txt"):
            fname = href.split("?")[0].rsplit("/", 1)[-1]
            selected.append((fname, href))
            break
    # Optionally angles
    if also_angles:
        for k, a in assets.items():
            href = a.get("href") if isinstance(a, dict) else None
            if not href:
                continue
            kl = str(k).lower()
            if kl.startswith("ang") or kl == "ang" or href.lower().endswith("_ANG.txt"):
                fname = href.split("?")[0].rsplit("/", 1)[-1]
                selected.append((fname, href))
                break
    # Optionally QA (pixel and radsat)
    if also_qa:
        for qa_key in ("qa_pixel", "qa_radSat", "qa_radsat"):
            for k, a in assets.items():
                href = a.get("href") if isinstance(a, dict) else None
                if not href:
                    continue
                if str(k).lower() == qa_key:
                    fname = href.split("?")[0].rsplit("/", 1)[-1]
                    selected.append((fname, href))
                    break
    return selected


def _download_file(url: str, dest_path: Path) -> str:
    import requests, os
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
    return str(dest_path)


def _default_bands_for_sensor(sensor: str, include_thermal: bool) -> List[str]:
    s = (sensor or "").upper()
    bands: List[str] = []
    if s in ("L8", "L9"):
        bands = ["B2", "B3", "B4", "B5", "B6", "B7"]
        if include_thermal:
            bands += ["B10", "B11"]
    elif s in ("L7", "L5"):
        bands = ["B1", "B2", "B3", "B4", "B5", "B7"]
        if include_thermal:
            bands += ["B6"]
    else:
        bands = ["B2", "B3", "B4", "B5", "B6", "B7"]
    return bands


def _parse_bands_arg(bands_arg: Optional[List[str]]) -> List[str]:
    if not bands_arg:
        return []
    out: List[str] = []
    for tok in bands_arg:
        for b in tok.replace(",", " ").split():
            b = b.strip().upper()
            if b:
                out.append(b)
    # Dedup preserve order
    seen=set(); res=[]
    for b in out:
        if b not in seen:
            res.append(b); seen.add(b)
    return res


def _select_band_assets(item: dict, desired_bands: List[str]) -> List[Tuple[str, str]]:
    assets = item.get("assets", {}) or {}
    selected: List[Tuple[str, str]] = []
    if not assets or not desired_bands:
        return selected
    dbset = set(b.upper() for b in desired_bands)
    for k, a in assets.items():
        href = a.get("href") if isinstance(a, dict) else None
        if not href:
            continue
        keyu = str(k).upper()
        fname = href.split("?")[0].rsplit("/", 1)[-1]
        fnameu = fname.upper()
        for b in list(dbset):
            # Match by asset key equal to band id OR filename containing _B{n}.TIF
            if keyu == b or ("_"+b+".") in fnameu or ("_"+b+"_") in fnameu:
                selected.append((fname, href))
                break
    return selected


def cmd_download_tile_metadata(args: argparse.Namespace) -> int:
    # Reuse list-tile search logic, then download MTL (and optional ANG/QA)
    start_iso, end_iso = _parse_dates(args)
    path, row = _parse_tile_id(args.tile_id)
    client = STACClient(base_url=args.stac_base)
    collections = _collections_for_server(args.stac_base, args.sensors, args.collections)

    # Gather items using Earth Search or LandsatLook paths like in list-tile
    feats: List[dict] = []
    is_earthsearch = ("earth-search" in (args.stac_base or "")) or ("element84" in (args.stac_base or ""))
    bbox = None if getattr(args, 'no_bbox', False) else get_tile_bbox(args.tile_id)
    dt_range = f"{start_iso}/{end_iso}"
    if collections:
        for coll in collections:
            if is_earthsearch:
                res = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                     query={"landsat:wrs_path": {"eq": int(path)}, "landsat:wrs_row": {"eq": int(row)}})
                feats.extend(res.get("features", []) or [])
                res2 = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                      query={"wrs_path": {"eq": int(path)}, "wrs_row": {"eq": int(row)}})
                feats.extend(res2.get("features", []) or [])
            else:
                base_filt = _filter_for_tile(path, row, start_iso, end_iso, None)
                res = client.search_cql2(collections=[coll], filter_obj=base_filt, limit=args.limit)
                feats.extend(res.get("features", []) or [])
    else:
        if is_earthsearch:
            res = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=args.limit,
                                 query={"landsat:wrs_path": {"eq": int(path)}, "landsat:wrs_row": {"eq": int(row)}})
            feats.extend(res.get("features", []) or [])
        else:
            base_filt = _filter_for_tile(path, row, start_iso, end_iso, None)
            res = client.search_cql2(collections=None, filter_obj=base_filt, limit=args.limit)
            feats.extend(res.get("features", []) or [])

    # Deduplicate by id
    seen = set(); items = []
    for it in feats:
        iid = it.get("id")
        if iid and iid not in seen:
            items.append(it); seen.add(iid)

    # Download selection
    dest_root = Path(args.dest)
    csv_rows: List[Tuple[str, str]] = []
    count = 0
    for it in items:
        full = _ensure_item_with_assets(client, args.stac_base, it)
        scene_id = full.get("id") or "unknown"
        files = _select_assets_for_toa(full, also_angles=bool(args.also_angles), also_qa=bool(args.also_qa))
        # Determine desired bands
        sensor = _infer_sensor(full)
        desired = _parse_bands_arg(getattr(args, 'bands', None))
        if not desired:
            desired = _default_bands_for_sensor(sensor, include_thermal=bool(args.thermal))
        band_files = _select_band_assets(full, desired)
        files.extend(band_files)
        if not files:
            continue
        scene_dir = dest_root / args.tile_id / scene_id
        for fname, href in files:
            out_path = scene_dir / fname
            try:
                local = _download_file(href, out_path)
                csv_rows.append((scene_id, local))
                count += 1
                print(local)
            except Exception as e:
                print(f"Download failed for {scene_id}:{fname}: {e}")

    print(f"Downloaded {count} file(s) to {dest_root}")
    if args.csv:
        p = Path(args.csv)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["scene_id", "local_path"])
            for r in csv_rows:
                w.writerow(list(r))
        print(f"Wrote CSV: {args.csv}")
    return 0


def _search_items_for_tile(base_url: str, client: STACClient, collections: List[str], tile_id: str, path: int, row: int, start_iso: str, end_iso: str, limit: int, use_bbox: bool, only_bbox: bool) -> List[dict]:
    feats: List[dict] = []
    is_earthsearch = ("earth-search" in (base_url or "")) or ("element84" in (base_url or ""))
    bbox = get_tile_bbox(tile_id) if use_bbox and not only_bbox else (get_tile_bbox(tile_id) if only_bbox else None)
    dt_range = f"{start_iso}/{end_iso}"
    if only_bbox:
        if collections:
            for coll in collections:
                res = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit, query=None)
                feats.extend(res.get("features", []) or [])
        else:
            res = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit, query=None)
            feats.extend(res.get("features", []) or [])
        return feats

    if collections:
        for coll in collections:
            if is_earthsearch:
                res = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                     query={"landsat:wrs_path": {"eq": int(path)}, "landsat:wrs_row": {"eq": int(row)}})
                feats.extend(res.get("features", []) or [])
                res2 = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                      query={"wrs_path": {"eq": int(path)}, "wrs_row": {"eq": int(row)}})
                feats.extend(res2.get("features", []) or [])
                res3 = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                      query={"wrs:path": {"eq": int(path)}, "wrs:row": {"eq": int(row)}})
                feats.extend(res3.get("features", []) or [])
                res4 = client.search(collections=[coll], bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                      query={"landsat:path": {"eq": int(path)}, "landsat:row": {"eq": int(row)}})
                feats.extend(res4.get("features", []) or [])
            else:
                base_filt = _filter_for_tile(path, row, start_iso, end_iso, None)
                res = client.search_cql2(collections=[coll], filter_obj=base_filt, limit=limit)
                feats.extend(res.get("features", []) or [])
    else:
        if is_earthsearch:
            res = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                 query={"landsat:wrs_path": {"eq": int(path)}, "landsat:wrs_row": {"eq": int(row)}})
            feats.extend(res.get("features", []) or [])
            res2 = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                  query={"wrs_path": {"eq": int(path)}, "wrs_row": {"eq": int(row)}})
            feats.extend(res2.get("features", []) or [])
            res3 = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                  query={"wrs:path": {"eq": int(path)}, "wrs:row": {"eq": int(row)}})
            feats.extend(res3.get("features", []) or [])
            res4 = client.search(collections=None, bbox=list(bbox) if bbox else None, datetime_range=dt_range, limit=limit,
                                  query={"landsat:path": {"eq": int(path)}, "landsat:row": {"eq": int(row)}})
            feats.extend(res4.get("features", []) or [])
        else:
            base_filt = _filter_for_tile(path, row, start_iso, end_iso, None)
            res = client.search_cql2(collections=None, filter_obj=base_filt, limit=limit)
            feats.extend(res.get("features", []) or [])
    return feats


def cmd_bulk_download(args: argparse.Namespace) -> int:
    start_iso, end_iso = _parse_dates(args)
    client = STACClient(base_url=args.stac_base)
    collections = _collections_for_server(args.stac_base, args.sensors, args.collections)

    dest_root = Path(args.dest)
    manifest_rows: List[Tuple[str, str, str]] = []  # tile_id, scene_id, local_path
    summary_rows: List[Tuple[str, int, int]] = []   # tile_id, items_found, files_downloaded
    processed = 0
    tiles_with_data = 0

    for tile in iter_au_tiles():
        processed += 1
        if args.max_tiles and processed > args.max_tiles:
            break
        path, row = tile.path, tile.row
        feats = _search_items_for_tile(args.stac_base, client, collections, tile.tile_id, path, row, start_iso, end_iso, args.per_tile_limit, use_bbox=not args.no_bbox, only_bbox=bool(args.only_bbox))
        # Optional fallback STAC base if nothing found
        if (not feats) and getattr(args, 'fallback_stac', None):
            try:
                fb_base = args.fallback_stac
                fb_client = STACClient(base_url=fb_base)
                fb_cols = _collections_for_server(fb_base, args.sensors, args.collections)
                feats = _search_items_for_tile(fb_base, fb_client, fb_cols, tile.tile_id, path, row, start_iso, end_iso, args.per_tile_limit, use_bbox=not args.no_bbox, only_bbox=bool(args.only_bbox))
            except Exception as e:
                print(f"Fallback search failed for {tile.tile_id}: {e}")
        # Dedup by id
        seen=set(); items=[]
        for it in feats:
            iid = it.get("id")
            if iid and iid not in seen:
                items.append(it); seen.add(iid)
        if not items:
            summary_rows.append((tile.tile_id, 0, 0))
            continue
        # Limit per-tile
        items = items[: args.per_tile_limit]
        tiles_with_data += 1
        files_downloaded = 0
        for it in items:
            full = _ensure_item_with_assets(client, args.stac_base, it)
            scene_id = full.get("id") or "unknown"
            # Select assets
            base_files = _select_assets_for_toa(full, also_angles=bool(args.also_angles), also_qa=bool(args.also_qa))
            sensor = _infer_sensor(full)
            desired = _parse_bands_arg(getattr(args, 'bands', None))
            if not desired:
                desired = _default_bands_for_sensor(sensor, include_thermal=bool(args.thermal))
            band_files = _select_band_assets(full, desired)
            files = base_files + band_files
            if not files:
                continue
            scene_dir = dest_root / tile.tile_id / scene_id
            for fname, href in files:
                out_path = scene_dir / fname
                try:
                    local = _download_file(href, out_path)
                    manifest_rows.append((tile.tile_id, scene_id, local))
                    files_downloaded += 1
                    print(local)
                except Exception as e:
                    print(f"Download failed for {tile.tile_id}:{scene_id}:{fname}: {e}")
        summary_rows.append((tile.tile_id, len(items), files_downloaded))
        if args.first_n_tiles and tiles_with_data >= args.first_n_tiles:
            break

    # Write manifests
    if args.manifest_csv:
        p = Path(args.manifest_csv); p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["tile_id", "scene_id", "local_path"])
            for r in manifest_rows:
                w.writerow(list(r))
        print(f"Wrote manifest CSV: {args.manifest_csv}")
    if args.summary_csv:
        p = Path(args.summary_csv); p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["tile_id", "items_found", "files_downloaded"])
            for r in summary_rows:
                w.writerow(list(r))
        print(f"Wrote summary CSV: {args.summary_csv}")
    print(f"Bulk download complete. Tiles with data: {tiles_with_data}; Files downloaded: {sum(x[2] for x in summary_rows)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Summarize TOA (Landsat C2 L1) availability per AU tile via STAC")
    sub = p.add_subparsers(dest="cmd", required=False)

    # Default (summary for all tiles)
    p.add_argument("--start", help="Start date YYYY-MM-DD")
    p.add_argument("--end", help="End date YYYY-MM-DD")
    p.add_argument("--years-back", type=float, default=2.0, dest="years_back", help="If start/end not given, look back this many years (default 2)")
    p.add_argument("--stac-base", default="https://landsatlook.usgs.gov/stac-server", help="STAC API base URL")
    p.add_argument("--collections", nargs="+", help="Explicit STAC collection IDs (overrides --sensors)")
    p.add_argument("--sensors", nargs="+", choices=["l5","l7","l8","l9"], help="Landsat sensors to include (maps to server collections)")
    p.add_argument("--limit", type=int, default=200, help="Max items to fetch per tile (sufficient for ~2 years)")
    p.add_argument("--csv", help="Optional path to write CSV summary, e.g., data/aus_lsat_tile_summary.csv")
    p.add_argument("--max-tiles", type=int, help="Optional cap on number of tiles to process (for testing)")

    # Subcommand: list items for a single tile
    p_list = sub.add_parser("list-tile", help="List per-item TOA rows for one tile (one row per scene)")
    p_list.add_argument("tile_id", help="Tile ID PPPRRR or PPP_RRR")
    p_list.add_argument("--start", help="Start date YYYY-MM-DD")
    p_list.add_argument("--end", help="End date YYYY-MM-DD")
    p_list.add_argument("--years-back", type=float, default=2.0, dest="years_back", help="If start/end not given, look back this many years (default 2)")
    p_list.add_argument("--stac-base", default="https://earth-search.aws.element84.com/v1", help="STAC API base URL")
    p_list.add_argument("--collections", nargs="+", help="Explicit STAC collection IDs (overrides --sensors)")
    p_list.add_argument("--sensors", nargs="+", choices=["l5","l7","l8","l9"], default=["l5","l7","l8","l9"], help="Sensors to include")
    p_list.add_argument("--limit", type=int, default=500, help="Max items to fetch for the tile")
    p_list.add_argument("--no-bbox", action="store_true", help="Do not apply tile bbox spatial filter (use only path/row)")
    p_list.add_argument("--only-bbox", action="store_true", help="Use only bbox + datetime filter (ignore path/row)")
    p_list.add_argument("--csv", help="Optional CSV path to write per-item rows")
    p_list.set_defaults(func=cmd_list_tile_items)

    # Subcommand: download minimal TOA metadata (MTL) per scene for one tile
    p_dl = sub.add_parser("download-tile", help="Download TOA-needed metadata (MTL) for a tile over a date range")
    p_dl.add_argument("tile_id", help="Tile ID PPPRRR or PPP_RRR")
    p_dl.add_argument("--start", help="Start date YYYY-MM-DD")
    p_dl.add_argument("--end", help="End date YYYY-MM-DD")
    p_dl.add_argument("--years-back", type=float, default=2.0, dest="years_back", help="If start/end not given, look back this many years (default 2)")
    p_dl.add_argument("--stac-base", default="https://landsatlook.usgs.gov/stac-server", help="STAC API base URL")
    p_dl.add_argument("--collections", nargs="+", help="Explicit STAC collection IDs (overrides --sensors)")
    p_dl.add_argument("--sensors", nargs="+", choices=["l5","l7","l8","l9"], help="Sensors to include")
    p_dl.add_argument("--limit", type=int, default=2000, help="Max items to fetch for the tile")
    p_dl.add_argument("--no-bbox", action="store_true", help="Do not apply tile bbox spatial filter (use only path/row)")
    p_dl.add_argument("--dest", default="data/landsat_toa", help="Destination directory for downloads")
    p_dl.add_argument("--also-angles", action="store_true", help="Also download ANG file if available")
    p_dl.add_argument("--also-qa", action="store_true", help="Also download QA_PIXEL/QA_RADSAT if available")
    p_dl.add_argument("--bands", nargs="+", help="Band IDs to download (e.g., B2 B3 B4 B5 B6 B7). If omitted, choose typical reflectance bands per sensor.")
    p_dl.add_argument("--thermal", action="store_true", help="Include thermal bands (e.g., B10/B11 for L8/9 or B6 for L7/5)")
    p_dl.add_argument("--csv", help="Optional CSV mapping scene_id -> local file path")
    p_dl.set_defaults(func=cmd_download_tile_metadata)

    # Subcommand: bulk download across many AU tiles
    p_bulk = sub.add_parser("bulk-download", help="Bulk download TOA-ready assets across many tiles")
    p_bulk.add_argument("--start", help="Start date YYYY-MM-DD")
    p_bulk.add_argument("--end", help="End date YYYY-MM-DD")
    p_bulk.add_argument("--years-back", type=float, default=2.0, dest="years_back", help="If start/end not given, look back this many years (default 2)")
    p_bulk.add_argument("--stac-base", default="https://landsatlook.usgs.gov/stac-server", help="Primary STAC API base URL")
    p_bulk.add_argument("--fallback-stac", help="Optional fallback STAC base URL used when a tile returns zero items on the primary")
    p_bulk.add_argument("--collections", nargs="+", help="Explicit STAC collection IDs (overrides --sensors)")
    p_bulk.add_argument("--sensors", nargs="+", choices=["l5","l7","l8","l9"], help="Sensors to include (maps to server collections)")
    p_bulk.add_argument("--per-tile-limit", type=int, default=500, dest="per_tile_limit", help="Max items to download per tile")
    p_bulk.add_argument("--first-n-tiles", type=int, dest="first_n_tiles", help="Stop after downloading from this many tiles with data (useful for sampling)")
    p_bulk.add_argument("--max-tiles", type=int, help="Optional cap on number of tiles to scan (process order is path/row ascending)")
    p_bulk.add_argument("--no-bbox", action="store_true", help="Do not apply tile bbox spatial filter (use only path/row)")
    p_bulk.add_argument("--only-bbox", action="store_true", help="Use only bbox + datetime filter (ignore path/row)")
    p_bulk.add_argument("--dest", default="data/landsat_toa", help="Destination directory for downloads")
    p_bulk.add_argument("--also-angles", action="store_true", help="Also download ANG file if available")
    p_bulk.add_argument("--also-qa", action="store_true", help="Also download QA_PIXEL/QA_RADSAT if available")
    p_bulk.add_argument("--bands", nargs="+", help="Band IDs to download (e.g., B2 B3 B4 B5 B6 B7). If omitted, choose typical reflectance bands per sensor.")
    p_bulk.add_argument("--thermal", action="store_true", help="Include thermal bands (e.g., B10/B11 for L8/9 or B6 for L7/5)")
    p_bulk.add_argument("--manifest-csv", dest="manifest_csv", help="Write global manifest CSV: tile_id,scene_id,local_path")
    p_bulk.add_argument("--summary-csv", dest="summary_csv", help="Write per-tile summary CSV: tile_id,items_found,files_downloaded")
    p_bulk.set_defaults(func=cmd_bulk_download)

    return p


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    # If subcommand provided, dispatch
    if hasattr(args, "func"):
        return args.func(args)

    # Default: summary across all tiles
    start_iso, end_iso = _parse_dates(args)
    client = STACClient(base_url=args.stac_base)
    collections = _collections_for_server(args.stac_base, args.sensors, args.collections)

    summaries: List[TileSummary] = []
    total = 0
    for t in iter_au_tiles():
        total += 1
        if args.max_tiles and total > args.max_tiles:
            break
        try:
            s = summarize_tile(client, t, start_iso, end_iso, collections, args.limit)
            summaries.append(s)
            print(f"{s.tile_id} ({s.path:03d}/{s.row:03d}) -> {s.count} items" + (f" [{s.first_date} .. {s.last_date}]" if s.count > 0 else ""))
        except Exception as e:
            print(f"{t.tile_id} ({t.path:03d}/{t.row:03d}) -> ERROR: {e}")

    print(f"Processed {len(summaries)} tile(s)")
    if args.csv:
        write_csv(summaries, args.csv)
        print(f"Wrote CSV: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

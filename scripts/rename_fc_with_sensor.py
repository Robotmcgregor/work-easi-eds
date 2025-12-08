#!/usr/bin/env python
"""Rename FC files to include sensor (LS8/LS9) in the prefix based on STAC platform lookup.

Existing naming (generic FC):
  ga_ls_fc_<path><row>_<YYYYMMDD>_fc3ms.tif
  ga_ls_fc_<path><row>_<YYYYMMDD>_fc3ms_clr.tif

Target naming (sensor‑explicit):
  ga_ls8c_fc_<path><row>_<YYYYMMDD>_fc3ms.tif
  ga_ls9c_fc_<path><row>_<YYYYMMDD>_fc3ms_clr.tif

Rules:
  - Only rename if platform resolves to landsat-8 or landsat-9 via STAC search on collection ga_ls_fc_3.
  - Skip if file already matches sensor‑prefixed pattern.
  - Provide --dry-run to preview planned renames without modifying files.
  - Cache platform per (pathrow,date) in memory to avoid repeat STAC calls.
  - Optional --cache-json to persist platform results for reuse.
  - Optional --limit to cap number of files processed (for testing).

Usage dry-run (PowerShell):
  C:\ProgramData\anaconda3\envs\slats\python.exe scripts\rename_fc_with_sensor.py \
    --root D:\data\lsat --tile 094_076 --dry-run --limit 10

Then perform actual rename:
  C:\ProgramData\anaconda3\envs\slats\python.exe scripts\rename_fc_with_sensor.py \
    --root D:\data\lsat --tile 094_076 --cache-json data\\compat\\files\\p094r076\\fc_platform_cache.json

STAC lookup strategy:
  - time range: exact day YYYY-MM-DD/YYYY-MM-DD
  - collection: ga_ls_fc_3
  - filter features whose properties.title contains "_<pathrow>_" and date.
  - choose first matching feature; read properties.platform.

Limitations:
  - If no matching STAC feature found, file is skipped.
  - Assumes public DEA STAC endpoint availability.
  - Does not validate reflectance quality; purely a provenance enhancement.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List, Tuple

STAC_ROOT = "https://explorer.dea.ga.gov.au/stac"
FC_COLLECTION = "ga_ls_fc_3"
PLAT_ALLOWED = {"landsat-8": "ls8c", "landsat-9": "ls9c"}

FC_REGEX = re.compile(
    r"^ga_ls_fc_(?P<pathrow>\d{6})_(?P<date>\d{8})_(?P<suffix>fc3ms(?:_clr)?\.tif)$",
    re.IGNORECASE,
)
ALREADY_REGEX = re.compile(
    r"^ga_ls(8|9)c_fc_(?P<pathrow>\d{6})_(?P<date>\d{8})_(?P<suffix>fc3ms(?:_clr)?\.tif)$",
    re.IGNORECASE,
)


@dataclass
class FCFile:
    path: Path
    pathrow: str
    date: str  # YYYYMMDD
    suffix: str  # fc3ms.tif or fc3ms_clr.tif


def find_fc_files(root: Path, tile: str) -> List[FCFile]:
    tile_dir = root / tile
    if not tile_dir.exists():
        return []
    out: List[FCFile] = []
    for tif in tile_dir.rglob("*.tif"):
        name = tif.name
        if ALREADY_REGEX.match(name):  # Already sensor-coded; skip
            continue
        m = FC_REGEX.match(name)
        if m:
            out.append(
                FCFile(
                    path=tif,
                    pathrow=m.group("pathrow"),
                    date=m.group("date"),
                    suffix=m.group("suffix"),
                )
            )
    return out


def stac_search_fc(pathrow: str, date: str, search_days: int = 0) -> Optional[str]:
    """Query STAC for the FC collection around a date, return platform or None.

    If search_days > 0 we expand the window ±search_days to improve hit rate
    for dates where FC product was generated on a nearby day.
    """
    from datetime import datetime, timedelta

    tgt = datetime.strptime(date, "%Y%m%d")
    start = tgt - timedelta(days=search_days)
    end = tgt + timedelta(days=search_days)
    time_range = f"{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
    url = f"{STAC_ROOT}/search?collection={FC_COLLECTION}&time={time_range}&limit=200"
    try:
        with urllib.request.urlopen(url, timeout=40) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None
    feats = data.get("features", [])
    # Pick closest date match for target pathrow
    best: Tuple[int, str] | None = None  # (abs day diff, platform)
    for f in feats:
        props = f.get("properties", {})
        title = props.get("title", "")
        plat = props.get("platform")
        if plat not in PLAT_ALLOWED:
            continue
        # Pathrow token check
        if f"_{pathrow}_" not in title:
            continue
        # Extract date from title (YYYY-MM-DD)
        m = re.search(r"(19|20)\d{2}-\d{2}-\d{2}", title)
        if not m:
            continue
        feat_dt = datetime.strptime(m.group(0), "%Y-%m-%d")
        diff = abs((feat_dt - tgt).days)
        if best is None or diff < best[0]:
            best = (diff, plat)
    return best[1] if best else None


def build_new_name(platform: str, pathrow: str, date: str, suffix: str) -> str:
    sensor_token = PLAT_ALLOWED[platform]  # ls8c or ls9c
    return f"ga_{sensor_token}_fc_{pathrow}_{date}_{suffix}".lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Rename FC files to sensor-coded prefixes (landsat-8/9)"
    )
    ap.add_argument(
        "--root", required=True, help="Root data directory (e.g. D:\\data\\lsat)"
    )
    ap.add_argument("--tile", required=True, help="Tile PPP_RRR (e.g. 094_076)")
    ap.add_argument("--dry-run", action="store_true", help="Preview renames only")
    ap.add_argument(
        "--limit", type=int, help="Limit number of files processed (for testing)"
    )
    ap.add_argument(
        "--cache-json", help="Optional JSON cache of platform lookups (read/write)"
    )
    ap.add_argument(
        "--search-days",
        type=int,
        default=0,
        help="Expand STAC search window ±days for platform resolution",
    )
    ap.add_argument(
        "--min-date",
        help="Skip files with dates earlier than this YYYYMMDD (e.g. 20130501)",
    )
    ap.add_argument(
        "--fallback-by-date",
        action="store_true",
        help="If STAC platform not resolved, infer sensor by date thresholds (>=20210928 -> LS9, >=20130701 -> LS8)",
    )
    ap.add_argument(
        "--only-uncoded",
        action="store_true",
        help="Process only files without sensor prefix (default true)",
    )
    args = ap.parse_args(argv)

    root = Path(args.root)
    cache: Dict[str, str] = {}
    if args.cache_json and Path(args.cache_json).exists():
        try:
            cache = json.loads(Path(args.cache_json).read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    fc_files = find_fc_files(root, args.tile)
    if args.limit:
        fc_files = fc_files[: args.limit]
    if not fc_files:
        print("[INFO] No FC files needing sensor rename found.")
        return 0

    planned: List[Tuple[str, str, str]] = []  # (old, new, platform)
    for fcf in fc_files:
        key = f"{fcf.pathrow}_{fcf.date}"
        if args.min_date and fcf.date < args.min_date:
            print(f"[SKIP] {fcf.path.name}: date {fcf.date} < min-date {args.min_date}")
            continue
        platform = cache.get(key)
        if not platform:
            platform = stac_search_fc(fcf.pathrow, fcf.date, args.search_days)
            if platform:
                cache[key] = platform
        if not platform:
            if args.fallback_by_date:
                # Date-based heuristic: Landsat 8 operational mid-2013; Landsat 9 post late 2021
                if fcf.date >= "20210928":
                    platform = "landsat-9"
                    cache[key] = platform
                    print(
                        f"[FALLBACK] {fcf.path.name}: assigned landsat-9 by date heuristic"
                    )
                elif fcf.date >= "20130701":
                    platform = "landsat-8"
                    cache[key] = platform
                    print(
                        f"[FALLBACK] {fcf.path.name}: assigned landsat-8 by date heuristic"
                    )
                else:
                    print(
                        f"[SKIP] {fcf.path.name}: platform not resolved and date < 20130701 (pre-LS8)"
                    )
                    continue
            else:
                print(f"[SKIP] {fcf.path.name}: platform not resolved")
                continue
        new_name = build_new_name(platform, fcf.pathrow, fcf.date, fcf.suffix)
        if fcf.path.name.lower() == new_name:
            continue
        planned.append((str(fcf.path), new_name, platform))

    if not planned:
        print("[INFO] No rename operations required.")
    else:
        print(f"[PLAN] {len(planned)} rename(s):")
        for old, new, plat in planned:
            print(f"  {plat:10s} :: {Path(old).name} -> {new}")
        if not args.dry_run:
            for old, new, plat in planned:
                p_old = Path(old)
                p_new = p_old.parent / new
                try:
                    p_old.rename(p_new)
                except Exception as e:
                    print(f"[ERR] Rename failed {p_old} -> {p_new}: {e}")
            print("[DONE] Renames applied.")

    if args.cache_json:
        try:
            Path(args.cache_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.cache_json).write_text(
                json.dumps(cache, indent=2), encoding="utf-8"
            )
            print(f"[CACHE] Wrote platform cache {args.cache_json}")
        except Exception as e:
            print(f"[WARN] Could not write cache file: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

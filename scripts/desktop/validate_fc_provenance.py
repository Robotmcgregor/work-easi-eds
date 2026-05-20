#!/usr/bin/env python
"""
Validate FC file provenance for a tile directory and flag any non-LS8/LS9 items.

- Scans D:\data\lsat\<PPP_RRR> (or --root) for ga_ls_fc_*_fc3ms(.tif|_clr.tif)
- Resolves platform via DEA STAC for the FC date and tile; if unknown, falls back
  to SR search within ±N days to infer LS8/LS9.
- Reports findings and can optionally move or delete non-LS8/LS9 files.

Examples (PowerShell):
  python scripts\validate_fc_provenance.py --tile 094_076 --root D:\data\lsat --out data\fc_094_076_provenance.csv
  python scripts\validate_fc_provenance.py --tile 094_076 --root D:\data\lsat --action move --quarantine-dir _quarantine
"""
from __future__ import annotations

import argparse
import os
import re
import csv
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from functools import lru_cache
import shutil
import urllib.request


DEA_STAC_ROOTS = [
    "https://explorer.dea.ga.gov.au/stac",
    "https://explorer.sandbox.dea.ga.gov.au/stac",
]
FC_COLLECTION = "ga_ls_fc_3"
SR_COLLECTIONS = ["ga_ls9c_ard_3", "ga_ls8c_ard_3"]
WORLD_BBOX = [-180.0, -90.0, 180.0, 90.0]


def build_stac_search_url(
    base_url: str,
    collection: str,
    bbox: List[float],
    time_range: str,
    limit: int = 2000,
) -> str:
    bbox_s = ",".join(str(x) for x in bbox)
    return (
        f"{base_url.rstrip('/')}/search?collection={collection}"
        f"&time={time_range}"
        f"&bbox={bbox_s}"
        f"&limit={limit}"
    )


def extract_feature_pathrow_from_assets(feature: Dict[str, Any]) -> Optional[str]:
    for asset_name, asset in feature.get("assets", {}).items():
        if asset_name in ("bs", "pv", "npv", "oa_fmask", "nbart_green"):
            href = asset.get("href") or ""
            parts = href.split("/")
            for i, seg in enumerate(parts):
                if seg.isdigit() and len(seg) == 3 and i + 1 < len(parts):
                    nxt = parts[i + 1]
                    if nxt.isdigit() and len(nxt) == 3:
                        return f"{seg}/{nxt}"
    return None


def parse_iso_date(s: str) -> Optional[str]:
    try:
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return s
    except Exception:
        pass
    return None


@lru_cache(maxsize=4096)
def resolve_fc_platform_for_tile_date(
    path: str, row: str, ymd: str, search_days: int = 7
) -> Optional[str]:
    iso = parse_iso_date(ymd)
    if not iso:
        return None
    date_str = iso
    time_range = f"{date_str}/{date_str}"
    data = None
    for base in DEA_STAC_ROOTS:
        try:
            url = build_stac_search_url(
                base, FC_COLLECTION, WORLD_BBOX, time_range, limit=2000
            )
            with urllib.request.urlopen(url) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception:
            data = None
            continue
    if data is None:
        return None

    target_pr = f"{int(path):03d}/{int(row):03d}"
    for feat in data.get("features", []):
        pr = extract_feature_pathrow_from_assets(feat)
        if pr == target_pr:
            return feat.get("properties", {}).get("platform")

    # Fallback to SR-based inference within ±search_days
    try:
        from datetime import datetime, timedelta

        d0 = datetime.strptime(date_str, "%Y-%m-%d")
        start = (d0 - timedelta(days=search_days)).strftime("%Y-%m-%d")
        end = (d0 + timedelta(days=search_days)).strftime("%Y-%m-%d")
        time_range_sr = f"{start}/{end}"

        nearest = {
            "landsat-8": None,
            "landsat-9": None,
        }
        for coll in SR_COLLECTIONS:
            data_sr = None
            for base in DEA_STAC_ROOTS:
                try:
                    url_sr = build_stac_search_url(
                        base, coll, WORLD_BBOX, time_range_sr, limit=2000
                    )
                    with urllib.request.urlopen(url_sr) as resp:
                        data_sr = json.loads(resp.read().decode("utf-8"))
                    break
                except Exception:
                    data_sr = None
                    continue
            if data_sr is None:
                continue
            for feat in data_sr.get("features", []):
                pr = extract_feature_pathrow_from_assets(feat)
                if pr != target_pr:
                    continue
                props = feat.get("properties", {})
                plat = props.get("platform")
                dt = props.get("datetime", "").split("T")[0]
                if plat not in ("landsat-8", "landsat-9") or not dt:
                    continue
                try:
                    d = datetime.strptime(dt, "%Y-%m-%d")
                    diff = abs((d - d0).days)
                except Exception:
                    continue
                prev = nearest[plat]
                if prev is None or diff < prev[0]:
                    nearest[plat] = (diff, dt)

        candidates = []
        for plat in ("landsat-9", "landsat-8"):
            if nearest[plat] is not None:
                candidates.append((nearest[plat][0], plat))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    except Exception:
        return None


def extract_platform_from_metadata(tif_path: Path) -> Optional[str]:
    """Try to extract platform from GeoTIFF metadata tags, return 'landsat-8'/'landsat-9' or None."""
    try:
        import rasterio

        with rasterio.open(tif_path) as ds:
            tags = ds.tags() or {}
            # Common keys we might encounter
            keys = [
                "platform",
                "satellite",
                "mission",
                "SPACECRAFT_NAME",
                "landsat:platform",
                "landsat:mission",
                "sensor",
                "INSTRUMENT",
                "SENSOR_ID",
                "SPACECRAFT_ID",
            ]
            vals = []
            for k in keys:
                v = tags.get(k)
                if v:
                    vals.append(str(v).lower())
            comb = " ".join(vals)
            if not comb:
                return None
            if (
                "landsat-9" in comb
                or "landsat 9" in comb
                or "ls9" in comb
                or "oli-2" in comb
            ):
                return "landsat-9"
            if (
                "landsat-8" in comb
                or "landsat 8" in comb
                or "ls8" in comb
                or "oli" in comb
            ):
                return "landsat-8"
            # Explicit L7/L5 identification if present
            if (
                "landsat-7" in comb
                or "landsat 7" in comb
                or "etm+" in comb
                or "etm" in comb
            ):
                return "landsat-7"
            if "landsat-5" in comb or "landsat 5" in comb or "tm" in comb:
                return "landsat-5"
    except Exception:
        return None
    return None


def infer_platform_from_local_sr(
    tile_dir: Path, path: str, row: str, ymd: str, search_days: int = 7
) -> Optional[str]:
    """Offline fallback: look for local SR files (ga_ls8c_ard_/ga_ls9c_ard_) near the date within ±N days.
    Return 'landsat-8'/'landsat-9' or None.
    """
    try:
        from datetime import datetime, timedelta

        target = datetime.strptime(ymd, "%Y%m%d")
        # Search recursively under tile for SR files with same pathrow and nearby dates
        pr = f"{path}{row}"
        sr8 = list(tile_dir.rglob(f"ga_ls8c_ard_{pr}_*_srb*.tif"))
        sr9 = list(tile_dir.rglob(f"ga_ls9c_ard_{pr}_*_srb*.tif"))

        def nearest_delta(files: List[Path]) -> Optional[int]:
            best = None
            for p in files:
                m = re.search(r"_(\d{8})_srb", p.name)
                if not m:
                    continue
                try:
                    d = datetime.strptime(m.group(1), "%Y%m%d")
                except Exception:
                    continue
                diff = abs((d - target).days)
                if best is None or diff < best:
                    best = diff
            return best

        d8 = nearest_delta(sr8)
        d9 = nearest_delta(sr9)
        # Only accept if within window
        cands = []
        if d8 is not None and d8 <= search_days:
            cands.append((d8, "landsat-8"))
        if d9 is not None and d9 <= search_days:
            cands.append((d9, "landsat-9"))
        if not cands:
            return None
        cands.sort(key=lambda x: x[0])
        return cands[0][1]
    except Exception:
        return None


def parse_fc_filename(name: str) -> Optional[Tuple[str, str, str, bool]]:
    # Supports both fc3ms and fc3ms_clr names
    # ga_ls_fc_094076_20240819_fc3ms.tif
    # ga_ls_fc_094076_20240819_fc3ms_clr.tif
    m = re.match(
        r"^ga_ls_fc_(\d{3})(\d{3})_(\d{8})_fc3ms(_clr)?\.tif$", name, re.IGNORECASE
    )
    if not m:
        return None
    path, row, ymd, clr = m.group(1), m.group(2), m.group(3), bool(m.group(4))
    return path, row, ymd, clr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate FC provenance (LS8/LS9-only)")
    ap.add_argument("--tile", required=True, help="PPP_RRR, e.g., 094_076")
    ap.add_argument(
        "--root", default=r"D:\\data\\lsat", help="Root dir containing tile folder"
    )
    ap.add_argument("--out", help="Optional CSV report path")
    ap.add_argument(
        "--action",
        choices=["report", "move", "delete"],
        default="report",
        help="What to do with non-LS8/LS9 items (default report)",
    )
    ap.add_argument(
        "--quarantine-dir",
        default="_quarantine",
        help="Folder name under tile to move non-LS8/9 files when --action move",
    )
    ap.add_argument(
        "--search-days",
        type=int,
        default=7,
        help="SR fallback window in days (default 7)",
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="Optional cap on files to check"
    )

    args = ap.parse_args(argv)

    tile_dir = Path(args.root) / args.tile
    if not tile_dir.exists():
        print(f"Tile directory not found: {tile_dir}")
        return 2

    fc_files = sorted([p for p in tile_dir.rglob("*.tif") if parse_fc_filename(p.name)])
    if not fc_files:
        print("No FC files found to validate.")
        return 0

    print(f"Validating {len(fc_files)} FC file(s) in {tile_dir}...")
    rows: List[Dict[str, str]] = []
    bad: List[Path] = []
    checked = 0

    for p in fc_files:
        if args.limit and checked >= args.limit:
            break
        info = parse_fc_filename(p.name)
        if not info:
            continue
        path, row, ymd, is_clr = info
        # 1) Try STAC FC + SR fallback
        plat = resolve_fc_platform_for_tile_date(
            path, row, ymd, search_days=args.search_days
        )
        # 2) Try GeoTIFF metadata if still unknown
        if not plat:
            plat = extract_platform_from_metadata(p)
        # 3) Try local SR presence if still unknown
        if not plat:
            plat = infer_platform_from_local_sr(
                tile_dir, path, row, ymd, search_days=args.search_days
            )
        status = "OK" if plat in ("landsat-8", "landsat-9") else "NON-LS8-9"
        rows.append(
            {
                "tile": args.tile,
                "pathrow": f"{path}{row}",
                "date": ymd,
                "filename": p.name,
                "platform": plat or "unknown",
                "status": status,
                "fullpath": str(p),
            }
        )
        if status != "OK" and not is_clr:
            # Only operate on base fc3ms; leave clr variants paired
            bad.append(p)
        checked += 1

    # Take action on non-LS8/9
    moved = deleted = 0
    if args.action == "move" and bad:
        qdir = tile_dir / args.quarantine_dir
        qdir.mkdir(parents=True, exist_ok=True)
        for b in bad:
            dest = qdir / b.name
            try:
                shutil.move(str(b), str(dest))
                moved += 1
            except Exception as e:
                print(f"[ERR] move failed {b} -> {e}")
    elif args.action == "delete" and bad:
        for b in bad:
            try:
                b.unlink(missing_ok=True)
                deleted += 1
            except Exception as e:
                print(f"[ERR] delete failed {b} -> {e}")

    # CSV output
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "tile",
                    "pathrow",
                    "date",
                    "filename",
                    "platform",
                    "status",
                    "fullpath",
                ],
            )
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"Wrote report: {out}")

    total = len(rows)
    non_ok = len([r for r in rows if r["status"] != "OK"])
    print(f"Checked: {total}, LS8/9: {total - non_ok}, Non-LS8/9: {non_ok}")
    if args.action == "move":
        print(f"Moved: {moved}")
    elif args.action == "delete":
        print(f"Deleted: {deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

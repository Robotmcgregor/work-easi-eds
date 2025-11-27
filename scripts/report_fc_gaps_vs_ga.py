#!/usr/bin/env python
"""
Report missing GA Fractional Cover (FC) scenes by comparing DEA STAC vs your S3 contents OR your local drive for a tile.

You provide a geographic bbox for the tile (WGS84 lon/lat) and a seasonal window, and the script:
- Queries DEA STAC for ga_ls_fc_3 within the time span
- Filters scenes whose month is within your seasonal window
- Lists your S3 keys for the tile
- Compares per-date presence and writes a CSV: PRESENT_BOTH, MISSING_IN_S3, ONLY_IN_S3

Usage (PowerShell):
  # 10 years seasonal window July..October ending 2025, with bbox (minx,miny,maxx,maxy)
    # Compare against S3
    python scripts\report_fc_gaps_vs_ga.py --tile 089_080 --bbox 140.0,-27.0,141.0,-26.0 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --no-base-prefix --csv data\fc_gaps_089_080.csv

    # Compare against local root (e.g. D:\data\lsat) instead of S3
    python scripts\report_fc_gaps_vs_ga.py --tile 089_080 --bbox 140.0,-27.0,141.0,-26.0 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --local-root D:\data\lsat --csv data\fc_gaps_local_089_080.csv

Notes:
- BBOX is required (or extend this script to accept a WRS2 shapefile to derive it).
- Requires internet access to DEA STAC (https://explorer.dea.ga.gov.au/stac)
"""
from __future__ import annotations

import argparse
import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional, Dict, Set, Tuple, Any
import re

import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Defer importing S3Client to runtime only when S3 is actually used to avoid
# importing the full src package (which pulls in dotenv) for local-only runs.
import os
import re

RE_DATE_IN_NAME = re.compile(r"_(\d{8})(?:_|\.|$)")
RE_FC_LOCAL = re.compile(r"^ga_ls_fc_(?P<pr>\d{6})_(?P<ymd>\d{8})_fc3ms(?:_clr)?\.tif$", re.IGNORECASE)

# Optional .env loader so flags with defaults from env pick up values without manual export
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore[assignment]

def _load_env_if_present() -> None:
    """Load environment variables from a nearby .env file if python-dotenv is available.
    Search order: repo/.env, repo/../.env, CWD/.env. Does not override existing env vars.
    """
    if load_dotenv is None:
        return
    candidates = [ROOT / ".env", ROOT.parent / ".env", Path.cwd() / ".env"]
    for p in candidates:
        try:
            if p.exists():
                load_dotenv(dotenv_path=p, override=False)  # type: ignore[misc]
                break
        except Exception:
            # Non-fatal if .env cannot be read
            pass


def _season_months(start_mm: int, end_mm: int) -> List[int]:
    if 1 <= start_mm <= 12 and 1 <= end_mm <= 12:
        if start_mm <= end_mm:
            return list(range(start_mm, end_mm + 1))
        return list(range(start_mm, 13)) + list(range(1, end_mm + 1))
    raise ValueError("Months must be in 1..12")


def _candidate_prefixes(tile: str, base_prefix: Optional[str]) -> List[str]:
    tile = tile.strip()
    if '_' not in tile and len(tile) == 6 and tile.isdigit():
        tile_pp_rr = f"{tile[:3]}_{tile[3:]}"
    else:
        tile_pp_rr = tile
    prefixes = [f"{tile}/", f"{tile_pp_rr}/"]
    prefixes = list(dict.fromkeys(prefixes))
    if base_prefix:
        return [f"{base_prefix}/{p}" for p in prefixes]
    return prefixes


def _s3_fc_dates(s3: Any, prefixes: List[str]) -> Set[str]:
    dates: Set[str] = set()
    for pfx in prefixes:
        for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
            base = os.path.basename(key).lower()
            if base.endswith("_fc3ms.tif") or base.endswith("_fc3ms_clr.tif"):
                m = RE_DATE_IN_NAME.search(base)
                if m:
                    dates.add(m.group(1))
    return dates


def _stac_search_fc(bbox: str, start_date: str, end_date: str) -> Dict:
    """Query DEA STAC for ga_ls_fc_3 using GET first, then POST fallback.

    Uses STAC /search endpoint. Some servers require `collections` (plural) and
    may prefer POST with a JSON body. We'll try a GET with `collections` and
    then a POST with a full JSON payload if GET fails.
    """
    root_url = "https://explorer.dea.ga.gov.au/stac"
    bbox_clean = bbox.replace(" ", "")
    # Try GET with `collections`
    get_url = (
        f"{root_url}/search?collections=ga_ls_fc_3"
        f"&datetime={start_date}/{end_date}"
        f"&bbox={bbox_clean}"
        f"&limit=10000"
    )
    try:
        with urllib.request.urlopen(get_url, timeout=60) as url:
            return json.loads(url.read().decode())
    except urllib.error.HTTPError as e:
        # Fallback to POST if GET not accepted
        pass
    except Exception:
        # Non-HTTP errors also fall back to POST
        pass

    # POST fallback
    try:
        # Parse bbox into floats to ensure valid JSON payload
        parts = [float(x) for x in bbox_clean.split(",")]
        body = {
            "collections": ["ga_ls_fc_3"],
            "datetime": f"{start_date}/{end_date}",
            "bbox": parts,
            "limit": 10000,
        }
        req = urllib.request.Request(
            f"{root_url}/search",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as url:
            return json.loads(url.read().decode())
    except Exception as e:
        raise RuntimeError(f"DEA STAC request failed (GET and POST). Check bbox/time. Underlying error: {e}")


def _ym_from_iso(iso_date: str) -> Tuple[str, str]:
    # ISO 'YYYY-MM-DD' -> (YYYY, YYYYMM)
    yyyy = iso_date[:4]
    yyyymm = iso_date[:4] + iso_date[5:7]
    return yyyy, yyyymm


def main(argv=None) -> int:
    # Ensure env defaults (S3_BUCKET, AWS_REGION, etc.) are loaded from .env before reading os.getenv
    _load_env_if_present()
    ap = argparse.ArgumentParser(description="Report FC gaps vs DEA for a tile")
    ap.add_argument("--tile", required=True, help="PPP_RRR or PPPRRR")
    ap.add_argument("--bbox", required=True, help="minx,miny,maxx,maxy in WGS84")
    ap.add_argument("--start-yyyymm", required=True)
    ap.add_argument("--end-yyyymm", required=True)
    ap.add_argument("--span-years", type=int, default=10)
    ap.add_argument("--csv", required=True, help="Output CSV path")

    # Optional: compare GA vs local instead of S3
    ap.add_argument("--local-root", help="Local root folder (e.g., D:\\data\\lsat). If provided, S3 is not used.")

    ap.add_argument("--bucket", default=os.getenv("S3_BUCKET", ""))
    ap.add_argument("--region", default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "")))
    ap.add_argument("--profile", default=os.getenv("AWS_PROFILE", ""))
    ap.add_argument("--endpoint", default=os.getenv("S3_ENDPOINT_URL", ""))
    ap.add_argument("--role-arn", dest="role_arn", default=os.getenv("S3_ROLE_ARN", ""))
    ap.add_argument("--base-prefix", default=os.getenv("S3_BASE_PREFIX", ""))
    ap.add_argument("--no-base-prefix", action="store_true")

    args = ap.parse_args(argv)

    # Compute seasonal months and years
    s_mon = int(args.start_yyyymm[4:]); e_mon = int(args.end_yyyymm[4:])
    months = _season_months(s_mon, e_mon)
    e_year = int(args.end_yyyymm[:4])
    years = list(range(e_year - (args.span_years - 1), e_year + 1))

    # Date span for STAC query (full span; we'll filter months)
    start_date = f"{years[0]}-01-01"  # safe envelope
    end_date   = f"{years[-1]}-12-31"

    # STAC query
    data_fc = _stac_search_fc(args.bbox, start_date, end_date)
    features = data_fc.get("features", [])

    # Build GA set of YYYYMMDD where month is in window
    ga_dates: Set[str] = set()
    rows = []
    for feat in features:
        iso = feat.get("properties", {}).get("datetime", "").split("T")[0]
        if not iso:
            continue
        yyyy, yyyymm = _ym_from_iso(iso)
        mm = int(yyyymm[4:])
        if mm in months and int(yyyy) in years:
            ymd = iso.replace('-', '')
            ga_dates.add(ymd)

    # Dates present locally or in S3
    if args.local_root:
        # Scan local
        want_tile = args.tile if '_' in args.tile else f"{args.tile[:3]}_{args.tile[3:]}"
        local_dates: Set[str] = set()
        for dirpath, dirnames, filenames in os.walk(args.local_root):
            # Restrict to this tile's top-level folder when possible
            p = Path(dirpath)
            if Path(args.local_root) == p.parent and p.name != want_tile:
                continue
            for fn in filenames:
                if RE_FC_LOCAL.match(fn):
                    m = RE_DATE_IN_NAME.search(fn)
                    if m:
                        local_dates.add(m.group(1))
        s_dates = local_dates
    else:
        base_prefix = None if args.no_base_prefix else (args.base_prefix or None)
        if not args.bucket:
            print("[WARN] No S3 bucket provided; reporting GA dates only.")
            s_dates = set()
        else:
            # Import S3Client lazily to avoid requiring dotenv/boto3 unless needed
            try:
                from src.utils.s3_client import S3Client
            except Exception as e:
                raise RuntimeError("S3 comparison requested but failed to import S3 client. Ensure project deps installed.") from e
            s3 = S3Client(bucket=args.bucket, region=args.region or "", profile=args.profile or "",
                          endpoint_url=args.endpoint or "", role_arn=args.role_arn or "")
            prefixes = _candidate_prefixes(args.tile, base_prefix)
            s_dates = _s3_fc_dates(s3, prefixes)

    # Compare
    all_dates = sorted(ga_dates | s_dates)
    out_rows = []
    for d in all_dates:
        in_ga = d in ga_dates
        in_s3 = d in s_dates
        if in_ga and in_s3:
            status = "PRESENT_BOTH"
        elif in_ga and not in_s3:
            status = "MISSING_IN_S3"
        else:
            status = "ONLY_IN_S3"
        out_rows.append({
            "tile": args.tile,
            "date": d,
            "year": d[:4],
            "yearmonth": d[:6],
            "status": status,
        })

    # Write CSV
    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tile", "date", "year", "yearmonth", "status"])
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"Wrote gap report: {out}")
    print(f"Summary: total={len(out_rows)} missing_in_s3={sum(1 for r in out_rows if r['status']=='MISSING_IN_S3')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

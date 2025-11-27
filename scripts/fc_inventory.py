#!/usr/bin/env python
"""
Inventory GA Fractional Cover (FC) files in S3 for a tile.

Matches common DEA FC file endings:
- *_fc3ms.tif
- *_fc3ms_clr.tif

Outputs a CSV (optional) with columns: tile, date, year, yearmonth, key, filename

Example (PowerShell):
    # Inventory filtered FC keys and write CSV
    python scripts\fc_inventory.py 090084 --bucket <BUCKET> --base-prefix <BASE_PREFIX> --region <REGION> --profile <PROFILE> --csv data\fc_090084.csv

    # Debug: print raw S3 keys under the tile prefixes
    python scripts\fc_inventory.py 090084 --list-raw --limit 200

    # Ignore any env S3_BASE_PREFIX (scan from bucket root)
    python scripts\fc_inventory.py 090084 --no-base-prefix --list-raw --limit 200
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.s3_client import S3Client
try:
    from dotenv import load_dotenv, find_dotenv  # optional
    _DOTENV_AVAILABLE = True
except Exception:
    _DOTENV_AVAILABLE = False


def _candidate_prefixes(tile_id: str, base_prefix: Optional[str]) -> List[str]:
    no_us = f"{tile_id}/"
    with_us = f"{tile_id[:3]}_{tile_id[3:]}/" if len(tile_id) == 6 and tile_id.isdigit() else f"{tile_id}/"
    prefixes = [no_us, with_us]
    prefixes = list(dict.fromkeys(prefixes))
    if base_prefix:
        return [f"{base_prefix}/{p}" for p in prefixes]
    return prefixes


def _parse_date_from_key(key: str) -> Tuple[Optional[int], Optional[str]]:
    # Try filename _YYYYMMDD_ or _YYYYMMDD.tif
    fname = os.path.basename(key)
    m = re.search(r"_(\d{8})(?:_|\.tif$)", fname)
    if m:
        ymd = m.group(1)
        return int(ymd[:4]), ymd[:6]
    # Fallback to path segments .../YYYY/YYYYMM/
    parts = key.split('/')
    year = None
    yearmonth = None
    for i, seg in enumerate(parts):
        if len(seg) == 4 and seg.isdigit() and (seg.startswith('19') or seg.startswith('20')):
            year = int(seg)
            if i + 1 < len(parts) and len(parts[i+1]) == 6 and parts[i+1].isdigit():
                yearmonth = parts[i+1]
            break
    return year, yearmonth


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="List GA FC fc3ms(_clr) files in S3 for a tile; optional raw listing for debugging")
    ap.add_argument("tile_id", help="Tile id, e.g., 090084")
    ap.add_argument("--bucket", help="S3 bucket (defaults to env S3_BUCKET if not provided)")
    ap.add_argument("--region", help="AWS region (defaults to AWS_REGION/AWS_DEFAULT_REGION)")
    ap.add_argument("--profile", help="AWS profile (defaults to AWS_PROFILE)")
    ap.add_argument("--endpoint", help="S3 endpoint URL (optional; S3_ENDPOINT_URL)")
    ap.add_argument("--role-arn", dest="role_arn", help="Assume role ARN (optional; S3_ROLE_ARN)")
    ap.add_argument("--base-prefix", help="Base prefix under bucket (defaults to S3_BASE_PREFIX)")
    ap.add_argument("--limit", type=int, help="Optional cap on rows")
    ap.add_argument("--list-raw", action="store_true", help="Print raw S3 keys under the candidate tile prefixes (for debugging)")
    ap.add_argument("--verbose", action="store_true", help="Print resolved config and prefixes")
    ap.add_argument("--no-base-prefix", action="store_true", help="Ignore S3_BASE_PREFIX and scan from bucket root")
    ap.add_argument("--csv", help="Write CSV output to this path")
    args = ap.parse_args(argv)
    # Load .env so AWS_* variables become available to the process
    if _DOTENV_AVAILABLE:
        try:
            load_dotenv(find_dotenv())
        except Exception:
            pass
    else:
        # Fallback: minimal .env loader (no extra dependency). Only sets vars not already present.
        env_path = ROOT / ".env"
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip(); v = v.strip()
                        if k and (k not in os.environ):
                            os.environ[k] = v
            except Exception:
                pass

    # Resolve settings from args -> env
    bucket = args.bucket or os.getenv("S3_BUCKET")
    if not bucket:
        raise SystemExit("--bucket not provided and S3_BUCKET not set in environment")
    region = args.region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or ""
    profile = args.profile or os.getenv("AWS_PROFILE") or ""
    endpoint = args.endpoint or os.getenv("S3_ENDPOINT_URL") or ""
    role_arn = args.role_arn or os.getenv("S3_ROLE_ARN") or ""
    if args.no_base_prefix:
        base_prefix = None
    elif args.base_prefix is not None:
        # Allow explicitly passing empty string to force root
        base_prefix = args.base_prefix if args.base_prefix != "" else None
    else:
        base_prefix = os.getenv("S3_BASE_PREFIX") or None

    s3 = S3Client(bucket=bucket, region=region, profile=profile, endpoint_url=endpoint, role_arn=role_arn)
    prefixes = _candidate_prefixes(args.tile_id, base_prefix)

    if args.verbose or args.list_raw:
        print("Config:")
        print(f"  bucket   : {bucket}")
        print(f"  region   : {region or '(default)'}")
        if endpoint:
            print(f"  endpoint : {endpoint}")
        if profile:
            print(f"  profile  : {profile}")
        print(f"  basePref : {base_prefix if base_prefix else '(none)'}")
        print("Candidate prefixes to scan:")
        for p in prefixes:
            print(f"  - {p}")

    # Optional: raw listing for debugging
    if args.list_raw:
        total_raw = 0
        cap = args.limit or 200
        for pfx in prefixes:
            print(f"[RAW] Listing up to {cap} keys under: s3://{bucket}/{pfx}")
            try:
                printed = 0
                for key in s3.list_prefix(pfx, recursive=True, max_keys=cap):
                    print(f"[RAW] {key}")
                    total_raw += 1
                    printed += 1
                if printed == 0:
                    print("[RAW] (no keys)")
            except Exception as e:
                print(f"[RAW] Warn: failed to list {pfx}: {e}")
        print(f"[RAW] Total keys printed: {total_raw}")

    rows = []
    for pfx in prefixes:
        try:
            for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
                # Accept both fc3ms and fc3ms_clr endings
                if re.search(r"_(fc3ms(?:_clr)?)\.tif{1,2}$", os.path.basename(key), flags=re.IGNORECASE):
                    year, yearmonth = _parse_date_from_key(key)
                    rows.append((args.tile_id, year or "", yearmonth or "", key, os.path.basename(key)))
                    if args.limit and len(rows) >= args.limit:
                        break
            if args.limit and len(rows) >= args.limit:
                break
        except Exception as e:
            print(f"Warn: listing failed for {pfx}: {e}")
            continue

    # Sort by key to give stable order, or by (year, yearmonth)
    rows.sort(key=lambda r: (str(r[1]), str(r[2]), r[4]))

    print(f"Found {len(rows)} FC fc3ms(_clr) file(s) for tile {args.tile_id}")
    for r in rows:
        print(r[3])

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        import csv
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["tile", "year", "yearmonth", "key", "filename"])
            for r in rows:
                w.writerow(list(r))
        print(f"Wrote CSV: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

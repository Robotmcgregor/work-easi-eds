#!/usr/bin/env python
r"""
Download GA FMASK rasters from your S3 bucket for a tile.

Matches filenames like:
- ga_lsXc_ard_<PPP_RRR>_<YYYYMMDD>_fmask.tif
- ga_ls9c_ard_<PPP_RRR>_<YYYYMMDD>_fmask.tif  (and similar for ls8c/ls7e/ls5t)

Output folder structure:
  D:\\data\\lsat\\<PPP_RRR>\\<YYYY>\\<YYYYMM>\\<filename>.tif

Examples:
  python scripts\download_fmask_from_s3.py --tile 089_080 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --dry-run --no-base-prefix
  python scripts\download_fmask_from_s3.py --tile 089_080 --dates 20160106,20170124 --dest D:\\data\\lsat --no-base-prefix
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Set

import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.s3_client import S3Client

RE_FMASK = re.compile(r"_fmask\.tif$", re.IGNORECASE)


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


def _parse_year_month_from_name(name: str):
    m = re.search(r"_(\d{8})(?:_|\.tif{1,2}$)", name)
    if m:
        ymd = m.group(1)
        return ymd[:4], ymd[:6]
    return None, None


def _season_months(start_mm: int, end_mm: int) -> List[int]:
    if 1 <= start_mm <= 12 and 1 <= end_mm <= 12:
        if start_mm <= end_mm:
            return list(range(start_mm, end_mm + 1))
        return list(range(start_mm, 13)) + list(range(1, end_mm + 1))
    raise ValueError("Months must be in 1..12")


def _collect_fmask_by_ym(s3: S3Client, prefixes: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    seen: Set[str] = set()
    for pfx in prefixes:
        for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
            base = os.path.basename(key)
            if RE_FMASK.search(base):
                if key in seen:
                    continue
                seen.add(key)
                _, ym = _parse_year_month_from_name(base)
                if not ym:
                    parts = key.split('/')
                    for i, seg in enumerate(parts):
                        if len(seg) == 4 and seg.isdigit():
                            if i + 1 < len(parts) and len(parts[i+1]) == 6 and parts[i+1].isdigit():
                                ym = parts[i+1]
                            break
                if ym and len(ym) == 6 and ym.isdigit():
                    out.setdefault(ym, []).append(key)
    return out


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download FMASK files from S3 for a tile")
    ap.add_argument("--tile", required=True, help="Tile PPP_RRR or PPPRRR")
    ap.add_argument("--dates", help="Comma-separated YYYYMMDD list (explicit mode)")
    ap.add_argument("--start-yyyymm", help="Seasonal mode: start YYYYMM")
    ap.add_argument("--end-yyyymm", help="Seasonal mode: end YYYYMM")
    ap.add_argument("--span-years", type=int, default=10, help="Years back including end year")
    ap.add_argument("--dest", default=r"D:\\data\\lsat", help="Destination root directory")
    ap.add_argument("--dry-run", action="store_true", help="Print matches only")
    ap.add_argument("--limit", type=int, default=None, help="Cap on downloads")

    ap.add_argument("--bucket", default=os.getenv("S3_BUCKET", ""))
    ap.add_argument("--region", default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "")))
    ap.add_argument("--profile", default=os.getenv("AWS_PROFILE", ""))
    ap.add_argument("--endpoint", default=os.getenv("S3_ENDPOINT_URL", ""))
    ap.add_argument("--role-arn", dest="role_arn", default=os.getenv("S3_ROLE_ARN", ""))
    ap.add_argument("--base-prefix", default=os.getenv("S3_BASE_PREFIX", ""))
    ap.add_argument("--no-base-prefix", action="store_true")

    args = ap.parse_args(argv)
    if not args.bucket:
        raise SystemExit("--bucket not provided and S3_BUCKET not set in environment")

    base_prefix = None if args.no_base_prefix else (args.base_prefix or None)
    s3 = S3Client(bucket=args.bucket, region=args.region or "", profile=args.profile or "",
                  endpoint_url=args.endpoint or "", role_arn=args.role_arn or "")
    prefixes = _candidate_prefixes(args.tile, base_prefix)

    dest_root = Path(args.dest)
    downloads = 0
    pr_folder = args.tile if '_' in args.tile else f"{args.tile[:3]}_{args.tile[3:]}"

    # Determine mode
    dates: List[str] = []
    seasonal = False
    if args.dates:
        dates = [d.strip() for d in args.dates.split(',') if d.strip()]
    else:
        if not (args.start_yyyymm and args.end_yyyymm):
            raise SystemExit("Provide --dates OR both --start-yyyymm and --end-yyyymm")
        s_mon = int(args.start_yyyymm[4:]); e_mon = int(args.end_yyyymm[4:])
        months = _season_months(s_mon, e_mon)
        e_year = int(args.end_yyyymm[:4])
        years = list(range(e_year - (args.span_years - 1), e_year + 1))
        allowed_ym = {f"{y}{m:02d}" for y in years for m in months}
        seasonal = True

    if seasonal:
        by_ym = _collect_fmask_by_ym(s3, prefixes)
        for ym in sorted(by_ym):
            if ym not in allowed_ym:
                continue
            for key in sorted(by_ym[ym]):
                if args.limit and downloads >= args.limit:
                    break
                year = ym[:4]
                yearmonth = ym
                dest_dir = dest_root / pr_folder / year / yearmonth
                _ensure_dir(dest_dir)
                dest_path = dest_dir / os.path.basename(key)
                if args.dry_run:
                    print(f"[HIT] {key} -> {dest_path}")
                    downloads += 1
                    continue
                try:
                    s3.download(key, str(dest_path), overwrite=False)
                    print(f"[OK] {key} -> {dest_path}")
                    downloads += 1
                except Exception as e:
                    print(f"[ERR] {key}: {e}")
    else:
        for date in dates:
            if args.limit and downloads >= args.limit:
                break
            found = None
            for pfx in prefixes:
                for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
                    base = os.path.basename(key).lower()
                    if base.endswith("_fmask.tif") and date in base:
                        found = key; break
                if found:
                    break
            if not found:
                print(f"[MISS] {args.tile} {date}")
                continue
            year = date[:4]; yearmonth = date[:6]
            dest_dir = dest_root / pr_folder / year / yearmonth
            _ensure_dir(dest_dir)
            dest_path = dest_dir / os.path.basename(found)
            if args.dry_run:
                print(f"[HIT] {found} -> {dest_path}")
                downloads += 1
                continue
            try:
                s3.download(found, str(dest_path), overwrite=False)
                print(f"[OK] {found} -> {dest_path}")
                downloads += 1
            except Exception as e:
                print(f"[ERR] {found}: {e}")

    print(f"Done. Matched {downloads} file(s).{' (dry-run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

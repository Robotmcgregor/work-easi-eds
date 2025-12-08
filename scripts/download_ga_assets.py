#!/usr/bin/env python
"""
Download GA Fractional Cover (FC) and Surface Reflectance (SR) assets from S3 for a tile and date(s).

This helps prepare local inputs for the SLATS-compat builder.

Examples (PowerShell):
  # Download FC for specific dates
  python scripts\download_ga_assets.py fc --tile 089_080 --dates 20160106,20170124,20180228,20190114,20190530,20190802 --dest data\source

  # Download SR bands (srb2..srb7) for two dates into per-date folders
  python scripts\download_ga_assets.py sr --tile 089_080 --dates 20190530,20190802 --dest data\source

Bucket/region/profile are read from environment (.env) or can be overridden with flags.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Optional

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.s3_client import S3Client


def _candidate_prefixes(tile: str, base_prefix: Optional[str]) -> List[str]:
    tile = tile.strip()
    if "_" not in tile and len(tile) == 6 and tile.isdigit():
        tile_pp_rr = f"{tile[:3]}_{tile[3:]}"
    else:
        tile_pp_rr = tile
    prefixes = [f"{tile}/", f"{tile_pp_rr}/"]
    prefixes = list(dict.fromkeys(prefixes))
    if base_prefix:
        return [f"{base_prefix}/{p}" for p in prefixes]
    return prefixes


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _download_fc(
    s3: S3Client, prefixes: List[str], tile: str, dates: List[str], dest_root: Path
) -> int:
    downloaded = 0
    for date in dates:
        target_suffixes = [f"_{date}_fc3ms.tif", f"_{date}_fc3ms_clr.tif"]
        found_key = None
        for pfx in prefixes:
            for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
                base = os.path.basename(key).lower()
                if any(base.endswith(suf) for suf in target_suffixes):
                    found_key = key
                    break
            if found_key:
                break
        if not found_key:
            print(f"[fc] Not found for {tile} {date}")
            continue
        scene = f"p{tile.replace('_','r')}"  # "089_080" -> "p089r080"
        dest_dir = dest_root / scene / "fc"
        _ensure_dir(dest_dir)
        dest_path = dest_dir / os.path.basename(found_key)
        try:
            s3.download(found_key, str(dest_path), overwrite=False)
            print(str(dest_path))
            downloaded += 1
        except Exception as e:
            print(f"[fc] Download failed {found_key}: {e}")
    return downloaded


def _download_sr(
    s3: S3Client, prefixes: List[str], tile: str, dates: List[str], dest_root: Path
) -> int:
    downloaded = 0
    for date in dates:
        scene = f"p{tile.replace('_','r')}"
        dest_dir = dest_root / scene / "sr" / date
        _ensure_dir(dest_dir)
        wanted = [f"_srb{b}.tif" for b in range(2, 8)]
        found = {w: None for w in wanted}
        for pfx in prefixes:
            for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
                base = os.path.basename(key).lower()
                if date in base and any(base.endswith(w) for w in wanted):
                    suf = next(w for w in wanted if base.endswith(w))
                    found[suf] = key
        any_found = False
        for suf, key in found.items():
            if key:
                try:
                    s3.download(
                        key, str(dest_dir / os.path.basename(key)), overwrite=False
                    )
                    print(str(dest_dir / os.path.basename(key)))
                    downloaded += 1
                    any_found = True
                except Exception as e:
                    print(f"[sr] Download failed {key}: {e}")
        if not any_found:
            print(f"[sr] No SR bands found for {tile} {date}")
    return downloaded


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Download GA FC or SR assets from S3 for a tile/date list"
    )
    sub = ap.add_subparsers(dest="mode", required=True)

    ap_fc = sub.add_parser("fc", help="Download Fractional Cover fc3ms files")
    ap_fc.add_argument(
        "--tile", required=True, help="Tile prefix PPP_RRR or PPPRRR (e.g., 089_080)"
    )
    ap_fc.add_argument("--dates", required=True, help="Comma-separated YYYYMMDD list")
    ap_fc.add_argument("--dest", default="data/source", help="Destination root")

    ap_sr = sub.add_parser("sr", help="Download Surface Reflectance srb2..srb7 files")
    ap_sr.add_argument(
        "--tile", required=True, help="Tile prefix PPP_RRR or PPPRRR (e.g., 089_080)"
    )
    ap_sr.add_argument("--dates", required=True, help="Comma-separated YYYYMMDD list")
    ap_sr.add_argument("--dest", default="data/source", help="Destination root")

    # Common S3 args
    for p in (ap_fc, ap_sr):
        p.add_argument("--bucket", default=os.getenv("S3_BUCKET", ""))
        p.add_argument(
            "--region",
            default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "")),
        )
        p.add_argument("--profile", default=os.getenv("AWS_PROFILE", ""))
        p.add_argument("--endpoint", default=os.getenv("S3_ENDPOINT_URL", ""))
        p.add_argument(
            "--role-arn", dest="role_arn", default=os.getenv("S3_ROLE_ARN", "")
        )
        p.add_argument("--base-prefix", default=os.getenv("S3_BASE_PREFIX", ""))

    args = ap.parse_args(argv)
    if not args.bucket:
        raise SystemExit("--bucket not provided and S3_BUCKET not set in environment")

    s3 = S3Client(
        bucket=args.bucket,
        region=args.region or "",
        profile=args.profile or "",
        endpoint_url=args.endpoint or "",
        role_arn=args.role_arn or "",
    )

    prefixes = _candidate_prefixes(args.tile, args.base_prefix or None)
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    dest_root = Path(args.dest)

    if args.mode == "fc":
        n = _download_fc(s3, prefixes, args.tile, dates, dest_root)
        print(f"Downloaded {n} FC file(s)")
    elif args.mode == "sr":
        n = _download_sr(s3, prefixes, args.tile, dates, dest_root)
        print(f"Downloaded {n} SR file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

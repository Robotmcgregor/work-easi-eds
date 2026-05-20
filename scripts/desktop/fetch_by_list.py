#!/usr/bin/env python
"""
Fetch files listed by edsadhoc_timeserieschange_d.py --reportinputs from S3.

Usage (PowerShell):
  # Generate the list of required inputs without running processing
  # python scripts/edsadhoc_timeserieschange_d.py --scene p090r084 --era e1516 --reportinputs data/inputs_p090r084_e1516.txt

  # Fetch those inputs from S3 to a local folder, finding keys by filename within the per-tile prefix
  # python scripts/fetch_by_list.py data/inputs_p090r084_e1516.txt --bucket <BUCKET> --base-prefix <BASE_PREFIX> --dest data/slats_cache

This helper searches under base-prefix/<PPP_RRR>/ recursively for keys ending with each filename.
If the scene name cannot be parsed, you can override the tile prefix with --tile.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional, Tuple, List

ROOT = Path(__file__).resolve().parent.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.s3_client import S3Client


def _parse_scene_from_filename(filename: str) -> Optional[str]:
    # Expect patterns like lztmre_p090r084_20150103_db8mz.img -> scene p090r084
    import re

    m = re.search(r"_(p\d{3}r\d{3})_", filename.lower())
    return m.group(1) if m else None


def _tile_from_scene(scene: str) -> Optional[str]:
    # scene p090r084 -> tile '090_084'
    try:
        p = int(scene[1:4])
        r = int(scene[5:8])
        return f"{p:03d}_{r:03d}"
    except Exception:
        return None


def _find_key_for_filename(
    s3: S3Client, base_prefix: str, tile_prefix: str, filename: str
) -> Optional[str]:
    search_prefix = f"{base_prefix}/{tile_prefix}" if base_prefix else tile_prefix
    if not search_prefix.endswith("/"):
        search_prefix += "/"
    # List recursively and find any key that ends with the filename
    for key in s3.list_prefix(search_prefix, recursive=True, max_keys=None):
        if key.endswith("/" + filename) or key.endswith("\\" + filename):
            return key
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch inputs listed by --reportinputs from S3"
    )
    ap.add_argument("list_file", help="Path to file produced by --reportinputs")
    ap.add_argument("--bucket", required=True, help="S3 bucket name")
    ap.add_argument("--region", help="AWS region")
    ap.add_argument("--profile", help="AWS profile")
    ap.add_argument("--endpoint", help="S3 endpoint URL (optional)")
    ap.add_argument("--role-arn", dest="role_arn", help="Assume role ARN (optional)")
    ap.add_argument(
        "--base-prefix", default="", help="Base prefix under bucket (e.g., slats/proj)"
    )
    ap.add_argument(
        "--tile", help="Tile prefix PPP_RRR override if scene parsing fails"
    )
    ap.add_argument(
        "--dest", default="data/slats_cache", help="Local destination root directory"
    )
    ap.add_argument(
        "--limit", type=int, help="Optional cap on number of files to fetch"
    )
    args = ap.parse_args(argv)

    s3 = S3Client(
        bucket=args.bucket,
        region=args.region or "",
        profile=args.profile or "",
        endpoint_url=args.endpoint or "",
        role_arn=args.role_arn or "",
    )
    os.makedirs(args.dest, exist_ok=True)

    with open(args.list_file, "r", encoding="utf-8") as f:
        wanted = [ln.strip() for ln in f if ln.strip()]

    downloaded = 0
    missing: List[str] = []
    for i, full in enumerate(wanted, 1):
        if args.limit and downloaded >= args.limit:
            break
        fname = os.path.basename(full)
        scene = _parse_scene_from_filename(fname)
        tile = args.tile or (_tile_from_scene(scene) if scene else None)
        if not tile:
            missing.append(full)
            continue
        key = _find_key_for_filename(s3, args.base_prefix, tile, fname)
        if not key:
            missing.append(full)
            continue
        dest_path = os.path.join(args.dest, tile, fname)
        try:
            s3.download(key, dest_path, overwrite=False)
            print(dest_path)
            downloaded += 1
        except Exception as e:
            print(f"Download failed for {key}: {e}")
    print(f"Downloaded {downloaded} file(s)")
    if missing:
        print("Missing (not found in S3 under base-prefix/tile):")
        for m in missing:
            print(m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

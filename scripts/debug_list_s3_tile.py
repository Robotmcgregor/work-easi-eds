#!/usr/bin/env python
"""Quick diagnostic: list up to N keys for a tile under a bucket/base-prefix combination.

Examples (PowerShell):
  python scripts\debug_list_s3_tile.py --bucket eia-satellite --base-prefix landsat --tile 089_080 --limit 50

If you have static keys in .env they are auto-loaded. Profile is ignored if keys present.
"""
from __future__ import annotations
import os, argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Optional .env load
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore
if load_dotenv:
    for candidate in [ROOT / ".env", ROOT.parent / ".env", Path.cwd() / ".env"]:
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)
            break

import importlib.util


def _load_s3client_dynamic():
    root = Path(__file__).resolve().parent.parent
    mod_path = root / "src" / "utils" / "s3_client.py"
    spec = importlib.util.spec_from_file_location("eds_s3_client_dbg", str(mod_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load S3 client module from {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    import sys as _sys

    _sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, "S3Client")


def candidate_prefixes(tile: str, base_prefix: str | None):
    tile = tile.strip()
    if "_" not in tile and len(tile) == 6 and tile.isdigit():
        tile_pp_rr = f"{tile[:3]}_{tile[3:]}"
    else:
        tile_pp_rr = tile
    # Potential directory styles we try:
    #   <tile> (089080 or 089_080)
    #   <tile without underscore> (if underscore version given)
    #   with YEAR subfolders (scan a small list of candidate years)
    #   with YEAR/YEARMM
    years = []
    try:
        # Heuristic: recent decade
        import datetime as _dt

        cy = _dt.datetime.utcnow().year
        years = list(range(cy, cy - 12, -1))
    except Exception:
        years = []

    variants = []
    # base tile forms
    variants.append(tile)
    variants.append(tile_pp_rr)
    if tile_pp_rr.replace("_", "") not in variants:
        variants.append(tile_pp_rr.replace("_", ""))

    prefixes = []
    for v in variants:
        prefixes.append(f"{v}/")
        for y in years:
            prefixes.append(f"{v}/{y}/")
    # Deduplicate while preserving order
    prefixes = list(dict.fromkeys(prefixes))
    if base_prefix:
        return [f"{base_prefix}/{p}" for p in prefixes]
    return prefixes


def main(argv=None):
    ap = argparse.ArgumentParser(description="List sample S3 keys for a tile")
    ap.add_argument("--bucket", default=os.getenv("S3_BUCKET", ""), required=False)
    ap.add_argument("--base-prefix", default=os.getenv("S3_BASE_PREFIX", ""))
    ap.add_argument("--tile", required=True)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument(
        "--region", default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", ""))
    )
    ap.add_argument("--endpoint", default=os.getenv("S3_ENDPOINT_URL", ""))
    ap.add_argument("--role-arn", default=os.getenv("S3_ROLE_ARN", ""))
    args = ap.parse_args(argv)

    if not args.bucket:
        print("[ERR] No bucket provided (set S3_BUCKET in .env or pass --bucket)")
        return 1

    # If static keys present ignore profile
    profile = (
        ""
        if (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))
        else os.getenv("AWS_PROFILE", "")
    )
    S3Client = _load_s3client_dynamic()
    s3 = S3Client(
        bucket=args.bucket,
        region=args.region or "",
        profile=profile,
        endpoint_url=args.endpoint or "",
        role_arn=args.role_arn or "",
    )
    prefixes = candidate_prefixes(args.tile, args.base_prefix or None)

    print("Config:")
    print(f"  bucket   : {args.bucket}")
    print(f"  region   : {args.region or '(default)'}")
    print(f"  basePref : {args.base_prefix or '(none)'}")
    print(f"  prefixes : {', '.join(prefixes)}")
    shown = 0
    for pfx in prefixes:
        print(f"\n[LIST] {pfx}")
        for key in s3.list_prefix(pfx, recursive=True, max_keys=args.limit):
            print(f"  {key}")
            shown += 1
            if shown >= args.limit:
                break
        if shown >= args.limit:
            break
    if shown == 0:
        print("[INFO] No keys listed (prefix may be empty or inaccessible)")
    else:
        print(f"\n[INFO] Displayed {shown} key(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

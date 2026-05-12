#!/usr/bin/env python
r"""
Download GA Fractional Cover (FC) stacks from your S3 bucket for a tile.

Two modes:
1) Explicit dates: --dates 20160106,20170124
2) Seasonal window across years: --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10
     → collects all FC files whose year-month falls in [07..10] for the last 10 years up to 2025.

- Scans your bucket/prefix for keys ending with _fc3ms.tif or _fc3ms_clr.tif
- Writes to Windows-friendly layout by default:
        D:\\data\\lsat\\<PPP_RRR>\\<YYYY>\\<YYYYMM>\\<filename>
    e.g. D:\\data\\lsat\\089_080\\2016\\201601\\ga_ls_fc_089080_20160106_fc3ms.tif

Examples (PowerShell):
    # Dry-run first (no downloads, prints matches) for explicit dates
    python scripts\download_fc_from_s3.py --tile 089_080 --dates 20160106,20170124 --dry-run --no-base-prefix

        # Seasonal window across the last 10 years (inclusive of end year)
        python scripts\download_fc_from_s3.py --tile 089_080 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --dry-run --no-base-prefix

    # Then actually download
        python scripts\download_fc_from_s3.py --tile 089_080 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --dest D:\\data\\lsat --no-base-prefix

        # Write a CSV report of identified keys and actions taken
        python scripts\download_fc_from_s3.py --tile 089_080 --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 --dry-run --csv data\fc_089_080_season.csv

Bucket/region/profile read from env (.env) or flags.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict, Any

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# IMPORTANT: avoid importing the top-level 'src' package here because src/__init__.py
# imports 'database' which requires SQLAlchemy. This script only needs the S3 client.
# Dynamically load src/utils/s3_client.py by file path to bypass package __init__ side-effects.
import importlib.util
import urllib.request
import json
from functools import lru_cache


def _load_s3client_from_file() -> Any:
    s3_path = ROOT / "src" / "utils" / "s3_client.py"
    if not s3_path.exists():
        raise RuntimeError(f"Cannot locate s3_client module at {s3_path}")
    spec = importlib.util.spec_from_file_location("_s3_client_module", str(s3_path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to create module spec for s3_client")
    mod = importlib.util.module_from_spec(spec)
    import sys as _sys

    _sys.modules[spec.name] = mod  # Register so dataclasses can resolve module
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    if not hasattr(mod, "S3Client"):
        raise RuntimeError("s3_client module does not define S3Client")
    return getattr(mod, "S3Client")


S3Client = _load_s3client_from_file()

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


def _parse_year_month_from_name(name: str) -> Tuple[Optional[str], Optional[str]]:
    # Look for _YYYYMMDD_ or _YYYYMMDD.tif in basename
    m = re.search(r"_(\d{8})(?:_|\.tif{1,2}$)", name)
    if m:
        ymd = m.group(1)
        return ymd[:4], ymd[:6]
    return None, None


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _season_months(start_mm: int, end_mm: int) -> List[int]:
    """Return list of month numbers in seasonal window (inclusive). Supports wrap-around.
    Example: (7, 10) -> [7,8,9,10]; (11, 2) -> [11,12,1,2]
    """
    if 1 <= start_mm <= 12 and 1 <= end_mm <= 12:
        if start_mm <= end_mm:
            return list(range(start_mm, end_mm + 1))
        return list(range(start_mm, 13)) + list(range(1, end_mm + 1))
    raise ValueError("Months must be in 1..12")


def _collect_fc_keys_by_yearmonth(s3: Any, prefixes: List[str]) -> Dict[str, List[str]]:
    """Scan prefixes once and bucket matching fc3ms(_clr) keys by yearmonth string YYYYMM.
    Returns dict: {YYYYMM: [keys...]}
    """
    by_ym: Dict[str, List[str]] = {}
    seen: Set[str] = set()
    for pfx in prefixes:
        for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
            base = os.path.basename(key).lower()
            if base.endswith("_fc3ms.tif") or base.endswith("_fc3ms_clr.tif"):
                if key in seen:
                    continue
                seen.add(key)
                _, ym = _parse_year_month_from_name(base)
                if not ym:
                    # fallback to path segments .../YYYY/YYYYMM/
                    parts = key.split("/")
                    for i, seg in enumerate(parts):
                        if len(seg) == 4 and seg.isdigit():
                            if (
                                i + 1 < len(parts)
                                and len(parts[i + 1]) == 6
                                and parts[i + 1].isdigit()
                            ):
                                ym = parts[i + 1]
                            break
                if ym and len(ym) == 6 and ym.isdigit():
                    by_ym.setdefault(ym, []).append(key)
    return by_ym


# --- DEA STAC provenance check (LS8/LS9 enforcement) -----------------------------------------
_DEA_STAC_ROOTS = [
    "https://explorer.dea.ga.gov.au/stac",
    "https://explorer.sandbox.dea.ga.gov.au/stac",
]
_FC_COLLECTION = "ga_ls_fc_3"
_SR_COLLECTIONS = ["ga_ls9c_ard_3", "ga_ls8c_ard_3"]
_WORLD_BBOX = [-180.0, -90.0, 180.0, 90.0]


def _build_stac_search_url(
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


def _extract_feature_pathrow_from_assets(feature: Dict[str, Any]) -> Optional[str]:
    # Parse any likely asset URL to discover the path/row segments
    candidate_assets = {
        # FC bands
        "bs",
        "pv",
        "npv",
        # SR common assets
        "oa_fmask",
        "nbart_blue",
        "nbart_green",
        "nbart_red",
        "nbart_nir",
        "nbart_swir_1",
        "nbart_swir_2",
    }
    for asset_name, asset in feature.get("assets", {}).items():
        if asset_name in candidate_assets:
            href = asset.get("href") or ""
            parts = href.split("/")
            for i, seg in enumerate(parts):
                if seg.isdigit() and len(seg) == 3 and i + 1 < len(parts):
                    nxt = parts[i + 1]
                    if nxt.isdigit() and len(nxt) == 3:
                        return f"{seg}/{nxt}"
    return None


def _parse_iso_date(s: str) -> Optional[str]:
    try:
        # Return YYYY-MM-DD
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
    """Return platform string (e.g., 'landsat-8' or 'landsat-9') for a given tile/date FC, else None.

    Uses DEA STAC search on ga_ls_fc_3 for the exact date and filters items by path/row from asset URLs.
    Fallback: if FC platform cannot be resolved, search SR (LS8/LS9) within ±search_days and infer platform
    from nearest SR presence for the same tile.
    """
    iso = _parse_iso_date(ymd)
    if not iso:
        return None
    date_str = iso
    time_range = f"{date_str}/{date_str}"
    data = None
    last_err = None
    for base in _DEA_STAC_ROOTS:
        try:
            url = _build_stac_search_url(
                base, _FC_COLLECTION, _WORLD_BBOX, time_range, limit=2000
            )
            with urllib.request.urlopen(url) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:
            last_err = e
            data = None
            continue
    if data is None:
        return None

    target_pr = f"{int(path):03d}/{int(row):03d}"
    for feat in data.get("features", []):
        pr = _extract_feature_pathrow_from_assets(feat)
        if pr == target_pr:
            return feat.get("properties", {}).get("platform")

    # Fallback to SR-based inference within ±search_days
    try:
        # Build a small time window around the date
        from datetime import datetime, timedelta

        d0 = datetime.strptime(date_str, "%Y-%m-%d")
        start = (d0 - timedelta(days=search_days)).strftime("%Y-%m-%d")
        end = (d0 + timedelta(days=search_days)).strftime("%Y-%m-%d")
        time_range_sr = f"{start}/{end}"

        nearest = {
            "landsat-8": None,  # (abs_days, iso_date)
            "landsat-9": None,
        }

        for coll in _SR_COLLECTIONS:
            data_sr = None
            for base in _DEA_STAC_ROOTS:
                try:
                    url_sr = _build_stac_search_url(
                        base, coll, _WORLD_BBOX, time_range_sr, limit=2000
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
                pr = _extract_feature_pathrow_from_assets(feat)
                if pr != target_pr:
                    continue
                props = feat.get("properties", {})
                plat = props.get("platform")
                dt = props.get("datetime", "").split("T")[0]
                if not plat or plat not in ("landsat-8", "landsat-9") or not dt:
                    continue
                try:
                    d = datetime.strptime(dt, "%Y-%m-%d")
                    diff = abs((d - d0).days)
                except Exception:
                    continue
                prev = nearest[plat]
                if prev is None or diff < prev[0]:
                    nearest[plat] = (diff, dt)

        # Choose the platform with the closest SR date; tie-break prefers L9 (newer)
        cand = []
        for plat in ("landsat-9", "landsat-8"):
            if nearest[plat] is not None:
                cand.append((nearest[plat][0], plat))
        if not cand:
            return None
        cand.sort(key=lambda x: x[0])
        return cand[0][1]
    except Exception:
        return None


def main(argv=None) -> int:
    # Ensure env defaults (S3_BUCKET, AWS_REGION, etc.) are loaded from .env before reading os.getenv
    _load_env_if_present()
    ap = argparse.ArgumentParser(
        description="Download FC fc3ms files from S3 for a tile/date list"
    )
    ap.add_argument(
        "--tile", required=True, help="Tile PPP_RRR or PPPRRR, e.g., 089_080"
    )

    # Selection modes
    ap.add_argument(
        "--dates", help="Comma-separated YYYYMMDD list (explicit date mode)"
    )
    ap.add_argument(
        "--start-yyyymm", help="Seasonal mode: start YYYYMM (months only considered)"
    )
    ap.add_argument(
        "--end-yyyymm", help="Seasonal mode: end YYYYMM (defines end year for span)"
    )
    ap.add_argument(
        "--span-years",
        type=int,
        default=10,
        help="Years back including end year (default 10)",
    )

    ap.add_argument(
        "--dest", default=r"D:\\data\\lsat", help="Destination root directory"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Print matches; do not download"
    )
    ap.add_argument("--limit", type=int, default=None, help="Optional cap on downloads")
    ap.add_argument(
        "--csv", help="Write a CSV report of identified and downloaded items"
    )
    ap.add_argument(
        "--csv-include-expected",
        action="store_true",
        help="For seasonal mode, include rows for expected YYYYMM with no matches",
    )
    ap.add_argument(
        "--on-exists",
        choices=["skip", "overwrite"],
        default="skip",
        help="If file exists locally: skip (default) or overwrite",
    )

    # S3 config
    ap.add_argument("--bucket", default=os.getenv("S3_BUCKET", ""))
    ap.add_argument(
        "--region", default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", ""))
    )
    ap.add_argument("--profile", default=os.getenv("AWS_PROFILE", ""))
    ap.add_argument("--endpoint", default=os.getenv("S3_ENDPOINT_URL", ""))
    ap.add_argument("--role-arn", dest="role_arn", default=os.getenv("S3_ROLE_ARN", ""))
    ap.add_argument("--base-prefix", default=os.getenv("S3_BASE_PREFIX", ""))
    ap.add_argument(
        "--no-base-prefix",
        action="store_true",
        help="Ignore S3_BASE_PREFIX and scan from bucket root",
    )

    args = ap.parse_args(argv)

    if not args.bucket:
        raise SystemExit("--bucket not provided and S3_BUCKET not set in environment")

    base_prefix = None if args.no_base_prefix else (args.base_prefix or None)

    # Parse path/row from tile for provenance checks
    tile_str = args.tile.strip()
    if "_" in tile_str:
        path_str, row_str = tile_str.split("_", 1)
    else:
        if len(tile_str) != 6 or not tile_str.isdigit():
            raise SystemExit("--tile must be PPP_RRR or PPPRRR")
        path_str, row_str = tile_str[:3], tile_str[3:]

    s3 = S3Client(
        bucket=args.bucket,
        region=args.region or "",
        profile=args.profile or "",
        endpoint_url=args.endpoint or "",
        role_arn=args.role_arn or "",
    )

    prefixes = _candidate_prefixes(args.tile, base_prefix)

    # Determine selection set: explicit dates OR seasonal window
    dates: List[str] = []
    seasonal_mode = False
    if args.dates:
        dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    else:
        if not (args.start_yyyymm and args.end_yyyymm):
            raise SystemExit("Provide --dates OR both --start-yyyymm and --end-yyyymm")
        if len(args.start_yyyymm) != 6 or len(args.end_yyyymm) != 6:
            raise SystemExit("--start-yyyymm and --end-yyyymm must be YYYYMM")
        try:
            s_year = int(args.start_yyyymm[:4])
            s_mon = int(args.start_yyyymm[4:])
            e_year = int(args.end_yyyymm[:4])
            e_mon = int(args.end_yyyymm[4:])
        except ValueError:
            raise SystemExit("Invalid YYYYMM values for seasonal mode")
        months = _season_months(s_mon, e_mon)
        years = list(range(e_year - (args.span_years - 1), e_year + 1))
        allowed_ym = {f"{y}{m:02d}" for y in years for m in months}
        seasonal_mode = True

    dest_root = Path(args.dest)
    downloads = 0
    records: List[Dict[str, str]] = []

    print("Config:")
    print(f"  bucket   : {args.bucket}")
    print(f"  region   : {args.region or '(default)'}")
    print(f"  basePref : {base_prefix if base_prefix else '(none)'}")
    if seasonal_mode:
        print(
            f"  season   : months={','.join(f'{m:02d}' for m in months)} years={years[0]}..{years[-1]}"
        )
    print("Candidate prefixes:")
    for p in prefixes:
        print(f"  - {p}")

    if seasonal_mode:
        # Scan once and filter by allowed YYYYMM set
        by_ym = _collect_fc_keys_by_yearmonth(s3, prefixes)
        # Flatten in (ym order, then filename order)
        for ym in sorted(by_ym.keys()):
            if ym not in allowed_ym:
                continue
            for found_key in sorted(by_ym[ym]):
                if args.limit and downloads >= args.limit:
                    break
                year = ym[:4]
                yearmonth = ym
                pr_folder = (
                    args.tile
                    if "_" in args.tile
                    else f"{args.tile[:3]}_{args.tile[3:]}"
                )
                dest_dir = dest_root / pr_folder / year / yearmonth
                _ensure_dir(dest_dir)
                dest_path = dest_dir / os.path.basename(found_key)
                # Try to extract the exact date from filename (YYYYMMDD)
                y, ym_guess = _parse_year_month_from_name(os.path.basename(found_key))
                ymd = None
                if ym_guess:
                    # derive date as the first 8 digits after last underscore
                    m = re.search(
                        r"_(\d{8})(?:_|\.tif{1,2}$)", os.path.basename(found_key)
                    )
                    if m:
                        ymd = m.group(1)
                # Enforce LS8/LS9-only FC by checking platform from DEA STAC
                if ymd:
                    plat = resolve_fc_platform_for_tile_date(path_str, row_str, ymd)
                else:
                    plat = None
                if plat not in ("landsat-8", "landsat-9"):
                    print(
                        f"[SKIP] non-LS8/9 FC (platform={plat or 'unknown'}) for {args.tile} {ymd or '?'} -> {found_key}"
                    )
                    records.append(
                        {
                            "mode": "seasonal",
                            "tile": args.tile,
                            "year": year,
                            "yearmonth": yearmonth,
                            "date": ymd or "",
                            "key": found_key,
                            "filename": os.path.basename(found_key),
                            "dest": str(dest_path),
                            "action": "SKIP-NON-LS8-9",
                        }
                    )
                    continue
                if args.dry_run:
                    print(f"[HIT] {found_key} -> {dest_path}")
                    downloads += 1
                    records.append(
                        {
                            "mode": "seasonal",
                            "tile": args.tile,
                            "year": year,
                            "yearmonth": yearmonth,
                            "date": ymd or "",
                            "key": found_key,
                            "filename": os.path.basename(found_key),
                            "dest": str(dest_path),
                            "action": "HIT (dry-run)",
                        }
                    )
                    continue
                # Handle existing file behaviour
                if dest_path.exists() and args.on_exists == "skip":
                    print(f"[SKIP] exists: {dest_path}")
                    records.append(
                        {
                            "mode": "seasonal",
                            "tile": args.tile,
                            "year": year,
                            "yearmonth": yearmonth,
                            "date": ymd or "",
                            "key": found_key,
                            "filename": os.path.basename(found_key),
                            "dest": str(dest_path),
                            "action": "SKIP-EXISTS",
                        }
                    )
                    continue
                try:
                    s3.download(
                        found_key,
                        str(dest_path),
                        overwrite=(args.on_exists == "overwrite"),
                    )
                    print(f"[OK] {found_key} -> {dest_path}")
                    downloads += 1
                    records.append(
                        {
                            "mode": "seasonal",
                            "tile": args.tile,
                            "year": year,
                            "yearmonth": yearmonth,
                            "date": ymd or "",
                            "key": found_key,
                            "filename": os.path.basename(found_key),
                            "dest": str(dest_path),
                            "action": "DOWNLOADED",
                        }
                    )
                except Exception as e:
                    print(f"[ERR] download failed {found_key}: {e}")
                    records.append(
                        {
                            "mode": "seasonal",
                            "tile": args.tile,
                            "year": year,
                            "yearmonth": yearmonth,
                            "date": ymd or "",
                            "key": found_key,
                            "filename": os.path.basename(found_key),
                            "dest": str(dest_path),
                            "action": f"ERROR: {e}",
                        }
                    )
        if args.csv and args.csv_include_expected:
            # Add rows for expected YYYYMMs that had no matches
            for ym in sorted(allowed_ym):
                if ym not in by_ym or not by_ym[ym]:
                    records.append(
                        {
                            "mode": "seasonal",
                            "tile": args.tile,
                            "year": ym[:4],
                            "yearmonth": ym,
                            "date": "",
                            "key": "",
                            "filename": "",
                            "dest": str(
                                (
                                    dest_root
                                    / (
                                        args.tile
                                        if "_" in args.tile
                                        else f"{args.tile[:3]}_{args.tile[3:]}"
                                    )
                                    / ym[:4]
                                    / ym
                                )
                            ),
                            "action": "EXPECTED-NOT-FOUND",
                        }
                    )
    else:
        # Explicit dates mode (original logic)
        for date in dates:
            if args.limit and downloads >= args.limit:
                break
            # Accept fc3ms or fc3ms_clr
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
                print(f"[MISS] {args.tile} {date} (no fc3ms(_clr) found)")
                if args.csv:
                    records.append(
                        {
                            "mode": "dates",
                            "tile": args.tile,
                            "year": date[:4],
                            "yearmonth": date[:6],
                            "date": date,
                            "key": "",
                            "filename": "",
                            "dest": str(
                                (
                                    dest_root
                                    / (
                                        args.tile
                                        if "_" in args.tile
                                        else f"{args.tile[:3]}_{args.tile[3:]}"
                                    )
                                    / date[:4]
                                    / date[:6]
                                )
                            ),
                            "action": "MISS",
                        }
                    )
                continue

            # Determine year/yearmonth from the filename
            year, yearmonth = _parse_year_month_from_name(os.path.basename(found_key))
            # Fallback to path parts if needed
            if not (year and yearmonth):
                parts = found_key.split("/")
                for i, seg in enumerate(parts):
                    if len(seg) == 4 and seg.isdigit():
                        year = year or seg
                        if (
                            i + 1 < len(parts)
                            and len(parts[i + 1]) == 6
                            and parts[i + 1].isdigit()
                        ):
                            yearmonth = yearmonth or parts[i + 1]
                        break
            year = year or date[:4]
            yearmonth = yearmonth or date[:6]

            # Enforce LS8/LS9-only FC by checking platform via DEA STAC
            plat = resolve_fc_platform_for_tile_date(path_str, row_str, date)
            if plat not in ("landsat-8", "landsat-9"):
                print(
                    f"[SKIP] non-LS8/9 FC (platform={plat or 'unknown'}) for {args.tile} {date} -> {found_key}"
                )
                records.append(
                    {
                        "mode": "dates",
                        "tile": args.tile,
                        "year": year,
                        "yearmonth": yearmonth,
                        "date": date,
                        "key": found_key,
                        "filename": os.path.basename(found_key),
                        "dest": str(
                            (
                                dest_root
                                / (
                                    args.tile
                                    if "_" in args.tile
                                    else f"{args.tile[:3]}_{args.tile[3:]}"
                                )
                                / year
                                / yearmonth
                            )
                        ),
                        "action": "SKIP-NON-LS8-9",
                    }
                )
                continue

            # Destination folder: D:\data\lsat\PPP_RRR\YYYY\YYYYMM
            pr_folder = (
                args.tile if "_" in args.tile else f"{args.tile[:3]}_{args.tile[3:]}"
            )
            dest_dir = dest_root / pr_folder / year / yearmonth
            _ensure_dir(dest_dir)

            dest_path = dest_dir / os.path.basename(found_key)
            if args.dry_run:
                print(f"[HIT] {found_key} -> {dest_path}")
                downloads += 1
                records.append(
                    {
                        "mode": "dates",
                        "tile": args.tile,
                        "year": year,
                        "yearmonth": yearmonth,
                        "date": date,
                        "key": found_key,
                        "filename": os.path.basename(found_key),
                        "dest": str(dest_path),
                        "action": "HIT (dry-run)",
                    }
                )
                continue
            # Handle existing file behaviour
            if dest_path.exists() and args.on_exists == "skip":
                print(f"[SKIP] exists: {dest_path}")
                records.append(
                    {
                        "mode": "dates",
                        "tile": args.tile,
                        "year": year,
                        "yearmonth": yearmonth,
                        "date": date,
                        "key": found_key,
                        "filename": os.path.basename(found_key),
                        "dest": str(dest_path),
                        "action": "SKIP-EXISTS",
                    }
                )
                continue
            try:
                s3.download(
                    found_key, str(dest_path), overwrite=(args.on_exists == "overwrite")
                )
                print(f"[OK] {found_key} -> {dest_path}")
                downloads += 1
                records.append(
                    {
                        "mode": "dates",
                        "tile": args.tile,
                        "year": year,
                        "yearmonth": yearmonth,
                        "date": date,
                        "key": found_key,
                        "filename": os.path.basename(found_key),
                        "dest": str(dest_path),
                        "action": "DOWNLOADED",
                    }
                )
            except Exception as e:
                print(f"[ERR] download failed {found_key}: {e}")
                records.append(
                    {
                        "mode": "dates",
                        "tile": args.tile,
                        "year": year,
                        "yearmonth": yearmonth,
                        "date": date,
                        "key": found_key,
                        "filename": os.path.basename(found_key),
                        "dest": str(dest_path),
                        "action": f"ERROR: {e}",
                    }
                )

    # Write CSV if requested
    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        import csv

        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "mode",
                    "tile",
                    "year",
                    "yearmonth",
                    "date",
                    "key",
                    "filename",
                    "dest",
                    "action",
                ],
            )
            w.writeheader()
            for r in records:
                w.writerow(r)
        print(f"Wrote CSV: {out}")

    print(f"Done. Matched {downloads} file(s).{' (dry-run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
r"""
Ensure SR composite and FMASK exist for a given tile and date by trying S3 first and falling back to GA.

- Looks for *_srb6.tif or *_srb7.tif and *_fmask.tif under S3 prefixes for the tile/date.
- Downloads to D:\\data\\lsat\\<PPP_RRR>\\<YYYY>\\<YYYYMM>\\.
- If not present in S3, calls external.ga_data_pull.sr_lsat_dea_data.main with --target_date to fetch from DEA and build outputs.

Requires: external/ga_data_pull/sr_lsat_dea_data.py (modified to support --target_date)
"""
from __future__ import annotations

import argparse
import os
import re
import json
import urllib.request
import time
from pathlib import Path
from typing import List, Optional, Any

import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util
from pathlib import Path

def _load_s3client_dynamic():
    """Load S3Client directly from src/utils/s3_client.py without importing the src package.
    This avoids executing src/__init__.py (which pulls heavy DB deps) when we only need S3.
    """
    root = Path(__file__).resolve().parent.parent
    mod_path = root / "src" / "utils" / "s3_client.py"
    spec = importlib.util.spec_from_file_location("eds_s3_client", str(mod_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load S3 client module from {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules so decorators (like @dataclass) can resolve module namespace
    import sys as _sys
    _sys.modules[spec.name] = mod  # type: ignore[index]
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return getattr(mod, "S3Client")

RE_SR = re.compile(r"_(?:sr6b|srb6|sr7b|srb7)\.tif$", re.IGNORECASE)
RE_FM = re.compile(r"_fmask\.tif$", re.IGNORECASE)


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
    if '_' not in tile and len(tile) == 6 and tile.isdigit():
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


def _download_from_s3(s3: Any, prefixes: List[str], tile: str, date: str, dest_root: Path) -> bool:
    found_sr = []
    found_fm = None
    for pfx in prefixes:
        for key in s3.list_prefix(pfx, recursive=True, max_keys=None):
            base = os.path.basename(key).lower()
            if date in base:
                if RE_SR.search(base):
                    found_sr.append(key)
                elif RE_FM.search(base):
                    found_fm = key
    if not found_sr and not found_fm:
        return False

    year = date[:4]; yearmonth = date[:6]
    pr_folder = tile if '_' in tile else f"{tile[:3]}_{tile[3:]}"
    dest_dir = dest_root / pr_folder / year / yearmonth
    _ensure_dir(dest_dir)

    ok = False
    for key in sorted(found_sr):
        try:
            s3.download(key, str(dest_dir / os.path.basename(key)), overwrite=False)
            print(f"[OK] SR  {key} -> {dest_dir}")
            ok = True
        except Exception as e:
            print(f"[ERR] SR  {key}: {e}")
    if found_fm:
        try:
            s3.download(found_fm, str(dest_dir / os.path.basename(found_fm)), overwrite=False)
            print(f"[OK] FM  {found_fm} -> {dest_dir}")
            ok = True or ok
        except Exception as e:
            print(f"[ERR] FM  {found_fm}: {e}")
    return ok


def main(argv=None) -> int:
    # Ensure env defaults (S3_BUCKET, AWS_REGION, etc.) are loaded from .env before reading os.getenv
    _load_env_if_present()
    ap = argparse.ArgumentParser(description="Ensure SR+FM exist for a tile/date using S3 or GA")
    ap.add_argument("--tile", required=True, help="PPP_RRR or PPPRRR (e.g., 089_080)")
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--dest", default=r"D:\\data\\lsat", help="Destination root directory")

    ap.add_argument("--bucket", default=os.getenv("S3_BUCKET", ""))
    ap.add_argument("--region", default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "")))
    ap.add_argument("--profile", default=os.getenv("AWS_PROFILE", ""))
    ap.add_argument("--endpoint", default=os.getenv("S3_ENDPOINT_URL", ""))
    ap.add_argument("--role-arn", dest="role_arn", default=os.getenv("S3_ROLE_ARN", ""))
    ap.add_argument("--base-prefix", default=os.getenv("S3_BASE_PREFIX", ""))
    ap.add_argument("--no-base-prefix", action="store_true")

    # GA fallback settings
    ap.add_argument("--cloud-threshold", type=float, default=10.0)
    ap.add_argument("--bbox", help="Optional WGS84 bbox minx,miny,maxx,maxy for GA fallback (avoids shapefile dependency)")
    ap.add_argument("--search-days", type=int, default=0, help="GA fallback: +/- days window around target date (default 0 = exact)")
    ap.add_argument("--print-stac", action="store_true", help="GA fallback: print candidate STAC item titles for debugging")

    args = ap.parse_args(argv)
    if not args.bucket:
        print("[INFO] S3 bucket not set; will skip S3 and go straight to GA fallback.")

    base_prefix = None if args.no_base_prefix else (args.base_prefix or None)
    prefixes = _candidate_prefixes(args.tile, base_prefix)

    dest_root = Path(args.dest)

    # Try S3 first
    used_s3 = False
    if args.bucket:
        try:
            # If static access keys are present, ignore any profile to avoid ProfileNotFound
            if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
                effective_profile = ""  # force direct credential usage
            else:
                effective_profile = args.profile or ""
            S3Client = _load_s3client_dynamic()
            s3 = S3Client(bucket=args.bucket, region=args.region or "", profile=effective_profile,
                          endpoint_url=args.endpoint or "", role_arn=args.role_arn or "")
            used_s3 = _download_from_s3(s3, prefixes, args.tile, args.date, dest_root)
            # Auto retry without base prefix if nothing found and a base prefix was supplied
            if (not used_s3) and base_prefix is not None:
                print("[INFO] No matches with base-prefix; retrying without base-prefix.")
                prefixes_no_base = _candidate_prefixes(args.tile, None)
                used_s3 = _download_from_s3(s3, prefixes_no_base, args.tile, args.date, dest_root)
        except Exception as e:
            print(f"[WARN] S3 path failed to initialize or access (will try GA fallback): {e}")
            used_s3 = False

    if used_s3:
        print("Done via S3.")
        return 0

    # Lightweight GA fallback implemented inline (no geopandas/s3fs required if bbox provided).
    pr = args.tile if '_' in args.tile else f"{args.tile[:3]}_{args.tile[3:]}"
    path = pr.split('_')[0]
    row  = pr.split('_')[1]
    td_norm = args.date if len(args.date) == 8 else args.date.replace('-', '')
    target_date_iso = f"{td_norm[:4]}-{td_norm[4:6]}-{td_norm[6:]}"

    bbox_clean = None
    if args.bbox:
        bbox_clean = args.bbox.replace(" ", "")
        try:
            bbox_parts = [float(x) for x in bbox_clean.split(',')]
            if len(bbox_parts) != 4:
                raise ValueError
        except Exception:
            raise SystemExit("Invalid --bbox; expected four comma-separated numbers: minx,miny,maxx,maxy")

    collections_priority = ["ga_ls9c_ard_3", "ga_ls8c_ard_3", "ga_ls7e_ard_3", "ga_ls5t_ard_3"]
    msg_bbox = f" within bbox {bbox_clean}" if bbox_clean else " (no bbox filter)"
    print(f"[GA] Inline fallback querying collections for {path}_{row} on {target_date_iso}{msg_bbox}")

    def _stac_query(collection: str) -> Optional[dict]:
        base = "https://explorer.dea.ga.gov.au/stac"
        # Build datetime range (expand if search-days > 0)
        if args.search_days and args.search_days > 0:
            from datetime import datetime, timedelta
            dt = datetime.strptime(target_date_iso, "%Y-%m-%d")
            start_dt = (dt - timedelta(days=args.search_days)).strftime("%Y-%m-%d")
            end_dt = (dt + timedelta(days=args.search_days)).strftime("%Y-%m-%d")
            dt_param = f"{start_dt}/{end_dt}"
        else:
            dt_param = f"{target_date_iso}/{target_date_iso}"
        if bbox_clean:
            url = (f"{base}/search?collections={collection}"
                   f"&datetime={dt_param}"
                   f"&bbox={bbox_clean}&limit=200")
        else:
            url = (f"{base}/search?collections={collection}"
                   f"&datetime={dt_param}"
                   f"&limit=500")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            print(f"[GA] WARN query failed for {collection}: {e}")
            return None

    feature = None
    used_collection = None
    from datetime import datetime as _dt
    target_dt = _dt.strptime(target_date_iso, "%Y-%m-%d")
    best_delta = None
    debug_candidates = []
    for col in collections_priority:
        data = _stac_query(col)
        feats = (data or {}).get("features", [])
        for f in feats:
            props_f = f.get("properties", {})
            iso = props_f.get("datetime", "").split('T')[0]
            title_prop = props_f.get("title", "")
            if args.print_stac:
                debug_candidates.append((col, iso, title_prop))
            # Require pathrow substring somewhere (underscore or not)
            pathrow_str = f"{path}{row}"
            if pathrow_str not in title_prop:
                continue
            # Date closeness
            try:
                scene_dt = _dt.strptime(iso, "%Y-%m-%d")
            except Exception:
                continue
            delta_days = abs((scene_dt - target_dt).days)
            if best_delta is None or delta_days < best_delta:
                feature = f
                used_collection = col
                best_delta = delta_days
        if feature and best_delta == 0:
            break

    if args.print_stac and debug_candidates:
        print("[GA] Candidate STAC items (collection, date, title):")
        for col, iso, t in debug_candidates[:25]:
            print(f"  {col} | {iso} | {t}")

    if not feature:
        print("[GA] No scene found within search window; consider increasing --search-days or --cloud-threshold.")
        return 1

    props = feature.get("properties", {})
    title = props.get("title", feature.get("id", "scene"))
    assets = feature.get("assets", {})
    # Identify SR (NBART) bands and fmask asset keys
    band_keys = [k for k in assets.keys() if k.startswith("nbart_")]
    band_keys_sorted = sorted(band_keys)
    fmask_key = "oa_fmask" if "oa_fmask" in assets else None
    if not band_keys_sorted:
        print("[GA] No nbart_* assets present; aborting.")
        return 1

    year = td_norm[:4]; yearmonth = td_norm[:6]
    dest_dir = dest_root / pr / year / yearmonth
    _ensure_dir(dest_dir)

    # Download each band locally
    local_band_paths: List[Path] = []
    for idx, bk in enumerate(band_keys_sorted, start=1):
        href = assets[bk].get("href")
        if not href:
            continue
        out_name = f"{title}_band{idx:02d}.tif"
        out_path = dest_dir / out_name
        if out_path.exists():
            print(f"[GA] Exists band: {out_path.name}")
        else:
            print(f"[GA] Downloading {bk} -> {out_name}")
            try:
                _download_ok = False
                if href.startswith("s3://"):
                    # Public DEA S3 assets: attempt unsigned boto3 access
                    try:
                        import boto3
                        from botocore.config import Config
                        s3_client = boto3.client("s3", config=Config(signature_version='unsigned'))
                        bucket_key = href[5:]  # strip s3://
                        bucket, key = bucket_key.split('/', 1)
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        s3_client.download_file(bucket, key, str(out_path))
                        _download_ok = True
                    except Exception as e_s3:
                        print(f"[GA] WARN unsigned S3 download failed for {bk}: {e_s3}")
                if not _download_ok:
                    # Fallback to HTTPS if provided or if s3 attempt failed and href is http(s)
                    if href.startswith("http://") or href.startswith("https://"):
                        with urllib.request.urlopen(href) as r, open(out_path, 'wb') as w:
                            w.write(r.read())
                        _download_ok = True
                if not _download_ok:
                    raise RuntimeError(f"Unsupported or inaccessible asset href: {href}")
                time.sleep(0.25)
            except Exception as e:
                print(f"[GA] ERR download {bk}: {e}")
                continue
        local_band_paths.append(out_path)

    if not local_band_paths:
        print("[GA] No bands downloaded; aborting.")
        return 1

    # Build composite using GDAL (avoid rasterio dependency)
    try:
        from osgeo import gdal
        # Open first band for georef
        first = gdal.Open(str(local_band_paths[0]))
        driver = gdal.GetDriverByName('GTiff')
        sr_count = len(local_band_paths)
        out_name = f"{title.split('_3-2-1_')[0]}_{path}{row}_{td_norm}_srb{sr_count}.tif"
        composite_path = dest_dir / out_name
        if composite_path.exists():
            print(f"[GA] Composite exists: {composite_path.name}")
        else:
            print(f"[GA] Creating composite {composite_path.name} with {sr_count} bands")
            dst = driver.Create(str(composite_path), first.RasterXSize, first.RasterYSize, sr_count, first.GetRasterBand(1).DataType, options=['COMPRESS=LZW'])
            dst.SetGeoTransform(first.GetGeoTransform())
            dst.SetProjection(first.GetProjection())
            for b_index, band_path in enumerate(local_band_paths, start=1):
                src = gdal.Open(str(band_path))
                arr = src.GetRasterBand(1).ReadAsArray()
                dst.GetRasterBand(b_index).WriteArray(arr)
                dst.GetRasterBand(b_index).SetNoDataValue(src.GetRasterBand(1).GetNoDataValue())
                src = None
            dst.FlushCache()
            dst = None
            first = None
        print(f"[GA] Composite ready: {composite_path}")
    except Exception as e:
        print(f"[GA] WARN composite build failed (GDAL missing?): {e}")
        # Leave individual bands; compat builder may fall back if adapted.

    # Download fmask if present
    if fmask_key:
        fm_href = assets[fmask_key].get('href')
        if fm_href:
            fm_name = f"{title.split('_3-2-1_')[0]}_{path}{row}_{td_norm}_fmask.tif"
            fm_path = dest_dir / fm_name
            if fm_path.exists():
                print(f"[GA] FMASK exists: {fm_path.name}")
            else:
                try:
                    with urllib.request.urlopen(fm_href) as r, open(fm_path, 'wb') as w:
                        w.write(r.read())
                    print(f"[GA] FMASK downloaded: {fm_path.name}")
                except Exception as e:
                    print(f"[GA] ERR FMASK download: {e}")
    else:
        print("[GA] No fmask asset found in feature.")

    print("Done via inline GA fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

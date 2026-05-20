#!/usr/bin/env python
"""
EDS CLI - Utilities to list S3 data, fetch inputs, and run processing.

Examples (Windows PowerShell):
  # List first 10 keys for a tile under the configured base prefix
  python scripts/eds_cli.py list-s3 090084 --limit 10

  # Fetch inputs to local cache for a tile and date range
  python scripts/eds_cli.py fetch-inputs 090084 --start 2025-10-01 --end 2025-11-03

  # Run EDS for a tile with the last 7 days (default)
  python scripts/eds_cli.py run-tile 090084 --confidence 0.7

Requires S3 configuration via env/.env: S3_BUCKET, AWS_PROFILE (or env creds), AWS_REGION, S3_BASE_PREFIX.
"""
from __future__ import annotations

import sys
from pathlib import Path
import argparse
from datetime import datetime, date

# Ensure src/ package is importable: add the repo root (parent of 'src') to sys.path
ROOT = Path(__file__).resolve().parent.parent  # repo root (contains 'src')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.config.settings import get_config
except ModuleNotFoundError:
    # Fallbacks: try current working directory's parent if structure differs
    cwd_parent = Path.cwd()
    if (cwd_parent / "src").exists() and str(cwd_parent) not in sys.path:
        sys.path.insert(0, str(cwd_parent))
    up_two = Path(__file__).resolve().parents[2]
    if (up_two / "src").exists() and str(up_two) not in sys.path:
        sys.path.insert(0, str(up_two))
    from src.config.settings import get_config


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def cmd_list_s3(args: argparse.Namespace) -> int:
    from src.utils.s3_client import S3Client

    cfg = get_config().s3
    bucket = args.bucket or cfg.bucket
    region = args.region or cfg.region
    profile = args.profile or cfg.profile
    endpoint_url = args.endpoint or cfg.endpoint_url
    role_arn = args.role_arn or cfg.role_arn
    base_prefix = (
        args.base_prefix if args.base_prefix is not None else (cfg.base_prefix or "")
    )
    if not bucket:
        print("S3 bucket not configured. Set S3_BUCKET in .env or pass --bucket.")
        return 2

    s3 = S3Client(
        bucket=bucket,
        region=region,
        profile=profile,
        endpoint_url=endpoint_url,
        role_arn=role_arn,
    )
    if args.prefix:
        prefix = args.prefix if args.prefix.endswith("/") else args.prefix + "/"
    elif base_prefix:
        prefix = f"{base_prefix}/{args.tile_id}/"
    else:
        prefix = f"{args.tile_id}/"

    print(f"Listing s3://{bucket}/{prefix} (limit {args.limit})...")
    count = 0
    try:
        for key in s3.list_prefix(
            prefix, recursive=not args.shallow, max_keys=args.limit or None
        ):
            print(key)
            count += 1
    except Exception as e:
        print("S3 list failed:", e)
        print(
            "Hint: Ensure the credentials/profile have s3:ListBucket permission for the bucket, and that the bucket policy allows listing for your principal.\n"
            "If the bucket is in another account, try --role-arn to assume a role with access. You can also omit --bucket to use USGS fallback via fetch-inputs."
        )
        return 3
    if (
        count == 0
        and args.prefix is None
        and args.tile_id.isdigit()
        and len(args.tile_id) == 6
    ):
        # Try underscore variant automatically if nothing found
        alt_suffix = f"{args.tile_id[:3]}_{args.tile_id[3:]}/"
        alt_prefix = f"{base_prefix}/{alt_suffix}" if base_prefix else alt_suffix
        print(f"No keys found. Trying underscore variant: s3://{bucket}/{alt_prefix}")
        try:
            for key in s3.list_prefix(
                alt_prefix, recursive=not args.shallow, max_keys=args.limit or None
            ):
                print(key)
                count += 1
        except Exception as e:
            print("S3 list (underscore) failed:", e)
    print(f"Total: {count}")
    return 0


def cmd_fetch_inputs(args: argparse.Namespace) -> int:
    from src.processing.data_access import DataAccessor

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    da = DataAccessor(
        bucket=args.bucket,
        region=args.region,
        profile=args.profile,
        endpoint_url=args.endpoint,
        role_arn=args.role_arn,
        base_prefix=args.base_prefix,
    )
    paths = da.ensure_local_inputs(
        args.tile_id,
        start,
        end,
        prefix=args.prefix,
        download=True,
        max_files=args.limit,
    )
    print(f"Downloaded {len(paths)} file(s)")
    for p in paths:
        print(p)
    return 0


def _parse_key_metadata(key: str):
    """Parse S3 key components we care about: tile (PPP_RRR), year, yearmonth, sensor family, type, filename."""
    import re, os

    parts = key.split("/")
    tile = parts[0] if len(parts) > 0 else ""
    year = None
    yearmonth = None
    if len(parts) >= 3 and parts[1].isdigit():
        year = int(parts[1])
        if parts[2].isdigit():
            yearmonth = parts[2]
    fname = os.path.basename(key)
    # sensor family: ga_(ls8c|ls9c|ls_fc)_ ...
    m = re.search(r"^ga_(ls\d+c|ls_fc)_", fname)
    sensor = m.group(1) if m else None
    # type: last token before extension
    t = None
    m2 = re.match(r"^(.+)_(?P<typ>[A-Za-z0-9]+)\.tif$", fname)
    if m2:
        t = m2.group("typ")
    return {
        "tile": tile,
        "year": year,
        "yearmonth": yearmonth,
        "sensor": sensor,
        "type": t,
        "filename": fname,
    }


def cmd_download_s3(args: argparse.Namespace) -> int:
    """Download S3 files for a tile with optional filters, preserving key structure under --dest."""
    from src.utils.s3_client import S3Client
    import os

    cfg = get_config().s3
    bucket = args.bucket or cfg.bucket
    region = args.region or cfg.region
    profile = args.profile or cfg.profile
    endpoint_url = args.endpoint or cfg.endpoint_url
    role_arn = args.role_arn or cfg.role_arn
    base_prefix = (
        args.base_prefix if args.base_prefix is not None else (cfg.base_prefix or "")
    )
    if not bucket:
        print("S3 bucket not configured. Set S3_BUCKET in .env or pass --bucket.")
        return 2

    s3 = S3Client(
        bucket=bucket,
        region=region,
        profile=profile,
        endpoint_url=endpoint_url,
        role_arn=role_arn,
    )

    # Build starting prefixes (support underscore variant)
    if args.prefix:
        prefixes = [args.prefix if args.prefix.endswith("/") else args.prefix + "/"]
        base_prefix_use = ""
    else:
        no_us = f"{args.tile_id}/"
        with_us = (
            f"{args.tile_id[:3]}_{args.tile_id[3:]}/"
            if len(args.tile_id) == 6 and args.tile_id.isdigit()
            else f"{args.tile_id}/"
        )
        prefixes = [no_us, with_us]
        base_prefix_use = base_prefix

    # If year provided, append year/ to narrow listing
    if args.year:
        prefixes = [
            (
                (f"{base_prefix_use}/{p}{args.year}/")
                if base_prefix_use
                else f"{p}{args.year}/"
            )
            for p in prefixes
        ]
    else:
        prefixes = [
            ((f"{base_prefix_use}/{p}") if base_prefix_use else p) for p in prefixes
        ]

    # List and filter
    keys = []
    for pfx in prefixes:
        try:
            # List all matching keys; apply download limit later after filtering
            for k in s3.list_prefix(pfx, recursive=True, max_keys=None):
                keys.append(k)
        except Exception as e:
            print(f"Warn: listing failed for {pfx}: {e}")
            continue

    # Deduplicate
    keys = list(dict.fromkeys(keys))

    sensors = set([s.lower() for s in args.sensor]) if args.sensor else None
    types = set([t.lower() for t in args.type]) if args.type else None

    selected = []
    for k in keys:
        meta = _parse_key_metadata(k)
        if args.year and meta["year"] != args.year:
            continue
        if sensors and (not meta["sensor"] or meta["sensor"].lower() not in sensors):
            continue
        if types and (not meta["type"] or meta["type"].lower() not in types):
            continue
        selected.append(k)

    if not selected:
        print("No matching keys found.")
        return 0

    os.makedirs(args.dest, exist_ok=True)
    downloaded = 0
    for k in selected[: args.limit or None]:
        dest_path = os.path.join(args.dest, k.replace("/", os.sep))
        try:
            s3.download(k, dest_path, overwrite=bool(args.overwrite))
            print(dest_path)
            downloaded += 1
        except Exception as e:
            print(f"Download failed for {k}: {e}")

    print(f"Downloaded {downloaded} file(s)")
    return 0


def _iter_local_files(root: str):
    import os

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".tif"):
                yield os.path.join(dirpath, fn)


def _parse_filename_date(fname: str):
    import re

    m = re.search(r"_(\d{8})_", fname)
    if not m:
        return None, None
    ymd = m.group(1)
    year = int(ymd[:4])
    yearmonth = ymd[:6]
    return year, yearmonth


def cmd_upload_s3(args: argparse.Namespace) -> int:
    from src.utils.s3_client import S3Client
    import os

    cfg = get_config().s3
    bucket = args.bucket or cfg.bucket
    region = args.region or cfg.region
    profile = args.profile or cfg.profile
    endpoint_url = args.endpoint or cfg.endpoint_url
    role_arn = args.role_arn or cfg.role_arn
    base_prefix = (
        args.base_prefix if args.base_prefix is not None else (cfg.base_prefix or "")
    )
    if not bucket:
        print("S3 bucket not configured. Set S3_BUCKET in .env or pass --bucket.")
        return 2
    if not os.path.isdir(args.source):
        print(f"Source directory not found: {args.source}")
        return 2

    s3 = S3Client(
        bucket=bucket,
        region=region,
        profile=profile,
        endpoint_url=endpoint_url,
        role_arn=role_arn,
    )

    tile_us = (
        f"{args.tile_id[:3]}_{args.tile_id[3:]}"
        if len(args.tile_id) == 6 and args.tile_id.isdigit()
        else args.tile_id
    )
    sensors = set([s.lower() for s in args.sensor]) if args.sensor else None
    types = set([t.lower() for t in args.type]) if args.type else None

    selected = []
    for path in _iter_local_files(args.source):
        rel = os.path.relpath(path, args.source).replace("\\", "/")
        # Expect structure like 089_078/2023/202307/filename.tif; keep whatever structure exists
        meta = _parse_key_metadata(rel)
        # If year not in relpath, try filename
        if meta["year"] is None:
            y, ym = _parse_filename_date(meta["filename"])
            meta["year"] = y
            meta["yearmonth"] = ym
        # Filter by tile if rel doesn't start with tile
        if not rel.startswith(tile_us):
            # allow if tile appears later in path
            if tile_us not in rel:
                continue
        if args.year and meta["year"] != args.year:
            continue
        if sensors and (not meta["sensor"] or meta["sensor"].lower() not in sensors):
            continue
        if types and (not meta["type"] or meta["type"].lower() not in types):
            continue
        selected.append((rel, path))

    if not selected:
        print("No matching local files found for upload.")
        return 0

    uploaded = 0
    for rel, src_path in selected[: args.limit or None]:
        key = f"{base_prefix}/{rel}" if base_prefix else rel
        if args.dry_run:
            print(f"DRY-RUN would upload: {src_path} -> s3://{bucket}/{key}")
            uploaded += 1
            continue
        try:
            ctype = "image/tiff" if src_path.lower().endswith(".tif") else None
            s3.upload(src_path, key, overwrite=bool(args.overwrite), content_type=ctype)
            print(f"s3://{bucket}/{key}")
            uploaded += 1
        except Exception as e:
            print(f"Upload failed for {src_path}: {e}")
    print(f"Uploaded {uploaded} file(s)")
    return 0


def cmd_usgs_login(args: argparse.Namespace) -> int:
    from src.config.settings import get_config
    from src.utils.m2m_client import USGSM2MClient

    cfg = get_config().usgs
    username = (args.username or cfg.username or "").strip()
    password = (args.password or cfg.password or "").strip()
    app_token = (
        getattr(args, "token", None) or getattr(cfg, "token", "") or ""
    ).strip()
    endpoint = args.endpoint or cfg.endpoint
    if not username:
        print("USGS username not set. Provide via .env USGS_USERNAME or --username.")
        return 2
    if not app_token and not password:
        print(
            "Provide either USGS_PASSWORD or USGS_TOKEN via .env, or use --password/--token flags."
        )
        return 2
    try:
        client = USGSM2MClient(
            username,
            password=None if app_token else password,
            endpoint=endpoint,
            app_token=app_token or None,
        )
        _ = client.login()
        print("Login OK (token redacted)")
        client.logout()
        return 0
    except Exception as e:
        print("USGS login failed:", e)
        return 1


def cmd_usgs_search(args: argparse.Namespace) -> int:
    from datetime import datetime as dt
    from src.config.settings import get_config
    from src.utils.m2m_client import USGSM2MClient

    cfg = get_config().usgs
    dataset = args.dataset or cfg.dataset
    node = args.node or cfg.node
    p = int(args.tile_id[:3])
    r = int(args.tile_id[3:6])
    start = dt.strptime(args.start, "%Y-%m-%d").date()
    end = dt.strptime(args.end, "%Y-%m-%d").date()
    try:
        client = USGSM2MClient(
            cfg.username,
            cfg.password,
            endpoint=cfg.endpoint,
            app_token=getattr(cfg, "token", "") or None,
        )
        client.login()
        scenes = client.search_scenes_wrs2(
            dataset, p, r, start, end, node=node, max_results=args.limit
        )
        print(f"Found {len(scenes)} scene(s)")
        for s in scenes:
            print(
                s.get("entityId") or s.get("entity_id"),
                s.get("displayId") or s.get("display_id"),
            )
        client.logout()
        return 0
    except Exception as e:
        print("USGS search failed:", e)
        return 1


def cmd_usgs_download(args: argparse.Namespace) -> int:
    from datetime import datetime as dt
    import os
    from src.config.settings import get_config
    from src.utils.m2m_client import USGSM2MClient

    cfg = get_config().usgs
    dataset = args.dataset or cfg.dataset
    node = args.node or cfg.node
    p = int(args.tile_id[:3])
    r = int(args.tile_id[3:6])
    start = dt.strptime(args.start, "%Y-%m-%d").date()
    end = dt.strptime(args.end, "%Y-%m-%d").date()
    os.makedirs(args.dest, exist_ok=True)
    try:
        client = USGSM2MClient(
            cfg.username,
            cfg.password,
            endpoint=cfg.endpoint,
            app_token=getattr(cfg, "token", "") or None,
        )
        client.login()
        scenes = client.search_scenes_wrs2(
            dataset, p, r, start, end, node=node, max_results=args.limit
        )
        if not scenes:
            print("No scenes found.")
            client.logout()
            return 0
        entity_ids = [
            s.get("entityId") or s.get("entity_id")
            for s in scenes
            if s.get("entityId") or s.get("entity_id")
        ]
        options = client.get_download_options(dataset, entity_ids, node=node)
        products = []
        for opt in options:
            if isinstance(opt, dict) and opt.get("entityId") and opt.get("products"):
                for prod in opt["products"]:
                    if prod.get("available"):
                        products.append(
                            {
                                "datasetName": dataset,
                                "entityId": opt["entityId"],
                                "productId": prod.get("id") or prod.get("productId"),
                            }
                        )
                        break
        if not products:
            print("No available products to download.")
            client.logout()
            return 0
        downloads = client.request_download(dataset, products, node=node)
        files = client.download_files(downloads, args.dest)
        print(f"Downloaded {len(files)} file(s)")
        for f in files:
            print(f)
        client.logout()
        return 0
    except Exception as e:
        print("USGS download failed:", e)
        return 1


def cmd_usgs_search_bbox(args: argparse.Namespace) -> int:
    from datetime import datetime as dt
    from src.config.settings import get_config
    from src.utils.m2m_client import USGSM2MClient

    cfg = get_config().usgs
    dataset = args.dataset or cfg.dataset
    node = args.node or cfg.node
    start = dt.strptime(args.start, "%Y-%m-%d").date()
    end = dt.strptime(args.end, "%Y-%m-%d").date()
    try:
        client = USGSM2MClient(
            cfg.username,
            cfg.password,
            endpoint=cfg.endpoint,
            app_token=getattr(cfg, "token", "") or None,
        )
        client.login()
        scenes = client.search_scenes_bbox(
            dataset,
            args.min_lon,
            args.min_lat,
            args.max_lon,
            args.max_lat,
            start,
            end,
            node=node,
            max_results=args.limit,
        )
        print(f"Found {len(scenes)} scene(s)")
        for s in scenes:
            print(
                s.get("entityId") or s.get("entity_id"),
                s.get("displayId") or s.get("display_id"),
            )
        client.logout()
        return 0
    except Exception as e:
        print("USGS bbox search failed:", e)
        return 1


def cmd_usgs_search_bbox_tile(args: argparse.Namespace) -> int:
    """Search USGS M2M using a tile's bbox looked up from DB."""
    from datetime import datetime as dt
    from src.config.settings import get_config
    from src.utils.m2m_client import USGSM2MClient
    from src.utils.tile_lookup import get_tile_bbox

    cfg = get_config().usgs
    dataset = args.dataset or cfg.dataset
    node = args.node or cfg.node
    start = dt.strptime(args.start, "%Y-%m-%d").date()
    end = dt.strptime(args.end, "%Y-%m-%d").date()
    bbox = get_tile_bbox(args.tile_id)
    if not bbox:
        print(
            f"No bbox found in DB for tile {args.tile_id}. Run wrs2 import first (see README-create-bbox.md)."
        )
        return 2
    min_lon, min_lat, max_lon, max_lat = bbox
    try:
        client = USGSM2MClient(
            cfg.username,
            cfg.password,
            endpoint=cfg.endpoint,
            app_token=getattr(cfg, "token", "") or None,
        )
        client.login()
        scenes = client.search_scenes_bbox(
            dataset,
            min_lon,
            min_lat,
            max_lon,
            max_lat,
            start,
            end,
            node=node,
            max_results=args.limit,
        )
        print(f"Found {len(scenes)} scene(s)")
        for s in scenes:
            print(
                s.get("entityId") or s.get("entity_id"),
                s.get("displayId") or s.get("display_id"),
            )
        client.logout()
        return 0
    except Exception as e:
        print("USGS bbox (tile) search failed:", e)
        return 1


def cmd_usgs_search_recent(args: argparse.Namespace) -> int:
    from src.config.settings import get_config
    from src.utils.m2m_client import USGSM2MClient

    cfg = get_config().usgs
    dataset = args.dataset or cfg.dataset
    node = args.node or cfg.node
    try:
        client = USGSM2MClient(
            cfg.username,
            cfg.password,
            endpoint=cfg.endpoint,
            app_token=getattr(cfg, "token", "") or None,
        )
        client.login()
        scenes = client.search_recent(
            dataset, days=args.days, node=node, max_results=args.limit
        )
        print(f"Found {len(scenes)} recent scene(s)")
        for s in scenes:
            print(
                s.get("entityId") or s.get("entity_id"),
                s.get("displayId") or s.get("display_id"),
            )
        client.logout()
        return 0
    except Exception as e:
        print("USGS recent search failed:", e)
        return 1


def cmd_run_tile(args: argparse.Namespace) -> int:
    from src.processing.pipeline import EDSPipelineManager, ProcessingConfig

    if args.start and args.end:
        cfg = ProcessingConfig(
            start_date=datetime.strptime(args.start, "%Y-%m-%d"),
            end_date=datetime.strptime(args.end, "%Y-%m-%d"),
            confidence_threshold=float(args.confidence),
        )
    else:
        cfg = EDSPipelineManager.create_processing_config(
            days_back=args.days_back, confidence_threshold=float(args.confidence)
        )

    res = EDSPipelineManager.run_tile_processing(args.tile_id, cfg)
    print(
        f"Success: {res.success} tile: {res.tile_id} alerts: {res.alerts_detected} time(s): {res.processing_time:.2f}"
    )
    if not res.success and res.error_message:
        print("Error:", res.error_message)
    return 0 if res.success else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="EDS CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ls = sub.add_parser("list-s3", help="List S3 keys for a tile prefix")
    p_ls.add_argument("tile_id", help="PathRow tile id, e.g., 090084")
    p_ls.add_argument("--limit", type=int, default=10, help="Maximum keys to list")
    p_ls.add_argument(
        "--prefix", help="Optional explicit prefix (overrides base-prefix + tile)"
    )
    p_ls.add_argument("--bucket", help="S3 bucket override")
    p_ls.add_argument("--region", help="AWS region override")
    p_ls.add_argument("--profile", help="AWS profile override")
    p_ls.add_argument(
        "--endpoint", help="S3 endpoint URL override (for S3-compatible stores)"
    )
    p_ls.add_argument("--role-arn", help="Assume role ARN override")
    p_ls.add_argument(
        "--base-prefix", help="Base prefix override (defaults to config.s3.base_prefix)"
    )
    p_ls.add_argument(
        "--shallow", action="store_true", help="Do not recurse into sub-prefixes"
    )
    p_ls.set_defaults(func=cmd_list_s3)

    p_fetch = sub.add_parser(
        "fetch-inputs", help="Download inputs for a tile + date range to local cache"
    )
    p_fetch.add_argument("tile_id")
    p_fetch.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p_fetch.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p_fetch.add_argument("--limit", type=int, default=100, help="Max files to download")
    p_fetch.add_argument(
        "--prefix", help="Optional explicit prefix (overrides base-prefix + tile)"
    )
    p_fetch.add_argument("--bucket", help="S3 bucket override")
    p_fetch.add_argument("--region", help="AWS region override")
    p_fetch.add_argument("--profile", help="AWS profile override")
    p_fetch.add_argument(
        "--endpoint", help="S3 endpoint URL override (for S3-compatible stores)"
    )
    p_fetch.add_argument("--role-arn", help="Assume role ARN override")
    p_fetch.add_argument(
        "--base-prefix", help="Base prefix override (defaults to config.s3.base_prefix)"
    )
    p_fetch.set_defaults(func=cmd_fetch_inputs)

    # New: download specific S3 files with filters and custom destination
    p_dl = sub.add_parser(
        "download-s3",
        help="Download S3 files for a tile with filters (year, sensor, type) and preserve S3 folder structure under --dest",
    )
    p_dl.add_argument("tile_id", help="Tile ID, e.g., 089078")
    p_dl.add_argument("--bucket", required=False, help="S3 bucket")
    p_dl.add_argument("--region", required=False, help="AWS region")
    p_dl.add_argument("--profile", help="AWS profile override")
    p_dl.add_argument(
        "--endpoint", help="S3 endpoint URL override (for S3-compatible stores)"
    )
    p_dl.add_argument("--role-arn", help="Assume role ARN override")
    p_dl.add_argument(
        "--base-prefix", help="Base prefix override (defaults to config.s3.base_prefix)"
    )
    p_dl.add_argument(
        "--prefix", help="Explicit prefix (e.g., 089_078/ or 089_078/2023/)"
    )
    p_dl.add_argument("--year", type=int, help="Filter by year, e.g., 2023")
    p_dl.add_argument(
        "--type",
        action="append",
        help="Filter by product type (repeatable), e.g., --type fc3ms --type fmask",
    )
    p_dl.add_argument(
        "--sensor",
        action="append",
        help="Filter by sensor family (repeatable): ls8c, ls9c, ls_fc",
    )
    p_dl.add_argument(
        "--limit", type=int, default=1000, help="Maximum files to download"
    )
    p_dl.add_argument(
        "--dest",
        default="data/cache",
        help="Destination root directory (preserves key structure)",
    )
    p_dl.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite local files if they already exist",
    )
    p_dl.set_defaults(func=cmd_download_s3)

    # Upload local files to S3, preserving structure under --source
    p_ul = sub.add_parser(
        "upload-s3",
        help="Upload local files to S3 preserving folder structure under --source; filter by year, sensor, type",
    )
    p_ul.add_argument(
        "tile_id",
        help="Tile ID, e.g., 089078 (underscore variant will be preserved from local path)",
    )
    p_ul.add_argument(
        "--source",
        required=True,
        help="Local source root directory (e.g., D:\\data\\lsat)",
    )
    p_ul.add_argument("--bucket", required=False, help="S3 bucket")
    p_ul.add_argument("--region", required=False, help="AWS region")
    p_ul.add_argument("--profile", help="AWS profile override")
    p_ul.add_argument(
        "--endpoint", help="S3 endpoint URL override (for S3-compatible stores)"
    )
    p_ul.add_argument("--role-arn", help="Assume role ARN override")
    p_ul.add_argument(
        "--base-prefix",
        help="Base prefix under bucket (defaults to config.s3.base_prefix)",
    )
    p_ul.add_argument("--year", type=int, help="Filter by year, e.g., 2023")
    p_ul.add_argument(
        "--type",
        action="append",
        help="Filter by product type (repeatable), e.g., --type fc3ms --type fmask",
    )
    p_ul.add_argument(
        "--sensor",
        action="append",
        help="Filter by sensor family (repeatable): ls8c, ls9c, ls_fc",
    )
    p_ul.add_argument("--limit", type=int, default=1000, help="Max files to upload")
    p_ul.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite objects in S3 if they already exist",
    )
    p_ul.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be uploaded without uploading",
    )
    p_ul.set_defaults(func=cmd_upload_s3)

    # USGS M2M helpers
    p_m2m_login = sub.add_parser(
        "usgs-login", help="Test USGS M2M login using .env or flags"
    )
    p_m2m_login.add_argument("--username", help="USGS username (overrides .env)")
    p_m2m_login.add_argument("--password", help="USGS password (overrides .env)")
    p_m2m_login.add_argument("--endpoint", help="USGS M2M endpoint override")
    p_m2m_login.add_argument(
        "--token", help="USGS application token (overrides .env USGS_TOKEN)"
    )
    p_m2m_login.set_defaults(func=cmd_usgs_login)

    p_m2m_search = sub.add_parser(
        "usgs-search", help="Search USGS M2M by WRS-2 tile and date range"
    )
    p_m2m_search.add_argument("tile_id")
    p_m2m_search.add_argument("--start", required=True)
    p_m2m_search.add_argument("--end", required=True)
    p_m2m_search.add_argument(
        "--dataset", help="Dataset name (e.g., LANDSAT_8_C2_L1, LANDSAT_9_C2_L1)"
    )
    p_m2m_search.add_argument("--node", default="EE", help="Node (default EE)")
    p_m2m_search.add_argument("--limit", type=int, default=50)
    p_m2m_search.set_defaults(func=cmd_usgs_search)

    p_m2m_dl = sub.add_parser(
        "usgs-download",
        help="Download from USGS M2M for a tile and date range (TOA: *_C2_L1)",
    )
    p_m2m_dl.add_argument("tile_id")
    p_m2m_dl.add_argument("--start", required=True)
    p_m2m_dl.add_argument("--end", required=True)
    p_m2m_dl.add_argument(
        "--dataset", help="Dataset name (default from config; e.g., LANDSAT_8_C2_L1)"
    )
    p_m2m_dl.add_argument("--node", default="EE")
    p_m2m_dl.add_argument("--limit", type=int, default=10)
    p_m2m_dl.add_argument("--dest", default="data/cache")
    p_m2m_dl.set_defaults(func=cmd_usgs_download)

    p_m2m_bbox = sub.add_parser(
        "usgs-search-bbox", help="Search USGS M2M by bounding box and date range"
    )
    p_m2m_bbox.add_argument("--dataset", help="Dataset name or id")
    p_m2m_bbox.add_argument("--node", default="EE")
    p_m2m_bbox.add_argument("--start", required=True)
    p_m2m_bbox.add_argument("--end", required=True)
    p_m2m_bbox.add_argument("--min-lon", type=float, dest="min_lon", required=True)
    p_m2m_bbox.add_argument("--min-lat", type=float, dest="min_lat", required=True)
    p_m2m_bbox.add_argument("--max-lon", type=float, dest="max_lon", required=True)
    p_m2m_bbox.add_argument("--max-lat", type=float, dest="max_lat", required=True)
    p_m2m_bbox.add_argument("--limit", type=int, default=50)
    p_m2m_bbox.set_defaults(func=cmd_usgs_search_bbox)

    p_m2m_recent = sub.add_parser(
        "usgs-search-recent", help="List recent scenes globally (no spatial filter)"
    )
    p_m2m_recent.add_argument("--dataset", help="Dataset name or id")
    p_m2m_recent.add_argument("--node", default="EE")
    p_m2m_recent.add_argument("--days", type=int, default=14)
    p_m2m_recent.add_argument("--limit", type=int, default=50)
    p_m2m_recent.set_defaults(func=cmd_usgs_search_recent)

    p_m2m_bbox_tile = sub.add_parser(
        "usgs-search-bbox-tile",
        help="Search USGS M2M by tile_id using bbox from DB and date range",
    )
    p_m2m_bbox_tile.add_argument("tile_id")
    p_m2m_bbox_tile.add_argument("--start", required=True)
    p_m2m_bbox_tile.add_argument("--end", required=True)
    p_m2m_bbox_tile.add_argument(
        "--dataset", help="Dataset name or id (e.g., LANDSAT_8_C2_L1)"
    )
    p_m2m_bbox_tile.add_argument("--node", default="EE")
    p_m2m_bbox_tile.add_argument("--limit", type=int, default=50)
    p_m2m_bbox_tile.set_defaults(func=cmd_usgs_search_bbox_tile)

    p_run = sub.add_parser("run-tile", help="Run EDS for a single tile")
    p_run.add_argument("tile_id")
    p_run.add_argument("--confidence", type=float, default=0.7)
    p_run.add_argument("--days-back", type=int, default=7)
    p_run.add_argument("--start", help="Optional explicit start date YYYY-MM-DD")
    p_run.add_argument("--end", help="Optional explicit end date YYYY-MM-DD")
    p_run.set_defaults(func=cmd_run_tile)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

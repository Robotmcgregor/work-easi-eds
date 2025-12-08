#!/usr/bin/env python
"""
S3 CLI - Lightweight wrapper exposing only S3-related commands from eds_cli.py

Commands:
  - list-s3
  - fetch-inputs
  - download-s3
  - upload-s3

This script reuses the command handlers implemented in scripts/eds_cli.py to avoid duplication.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import the existing handlers from the main CLI
from scripts.eds_cli import (
    cmd_list_s3,
    cmd_fetch_inputs,
    cmd_download_s3,
    cmd_upload_s3,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="S3 CLI")
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

    p_dl = sub.add_parser(
        "download-s3",
        help="Download S3 files for a tile with filters and preserve S3 folder structure under --dest",
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

    p_ul = sub.add_parser(
        "upload-s3",
        help="Upload local files to S3 preserving structure; filter by year/sensor/type",
    )
    p_ul.add_argument(
        "tile_id",
        help="Tile ID, e.g., 089078 (underscore variant preserved from local path)",
    )
    p_ul.add_argument("--source", required=True, help="Local source root directory")
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
        "--type", action="append", help="Filter by product type (repeatable)"
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

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""
copy_eds_tiles_to_aad.py

Copy EDS LS8/9 SR/FC/ffmask outputs from your user scratch bucket
(s3://dcceew-prod-user-scratch/<UserId>/eds/tiles/...)
into the internal AAD bucket (e.g. s3://eia-satellite/eds/tiles/...),
preserving the eds/tiles/... folder structure.

Example
-------

Copy all products for tile p104r070:

    python copy_eds_tiles_to_aad.py \
        --tile-id p104r070

Dry-run (print what *would* be copied, but do nothing):

    python copy_eds_tiles_to_aad.py \
        --tile-id p104r070 \
        --dry-run

Copy everything under your eds/tiles/, all tiles:

    python copy_eds_tiles_to_aad.py

You can also override buckets and dest prefix:

    python copy_eds_tiles_to_aad.py \
        --src-bucket dcceew-prod-user-scratch \
        --dst-bucket eia-satellite \
        --dst-root-prefix eds/tiles \
        --tile-id p104r070
"""

from __future__ import annotations

import argparse
from typing import Iterator, Dict

import boto3
from botocore.exceptions import ClientError


def get_user_prefix_from_sts() -> str:
    """
    Use STS to get UserId, e.g. "AROAXXX...:robotmcgregor".

    This matches the prefix used in:
        s3://dcceew-prod-user-scratch/<UserId>/eds/tiles/...
    """
    sts = boto3.client("sts")
    ident = sts.get_caller_identity()
    user_id = ident.get("UserId")
    if not user_id:
        raise RuntimeError("Could not get UserId from sts.get_caller_identity()")
    return user_id


def iter_source_objects(
    s3_client,
    bucket: str,
    prefix: str,
) -> Iterator[Dict]:
    """
    Iterator over all objects in `bucket` under `prefix` using a paginator.
    Yields the raw dicts from list_objects_v2 (each has 'Key', 'Size', etc).
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    page_iter = paginator.paginate(Bucket=bucket, Prefix=prefix)

    for page in page_iter:
        contents = page.get("Contents", [])
        for obj in contents:
            yield obj


def object_exists(
    s3_client,
    bucket: str,
    key: str,
) -> bool:
    """
    Check if an object exists in S3 via HEAD.

    Note: if we don't have permission to HEAD (403/AccessDenied),
    we log once and assume it does NOT exist, so copy will proceed.
    """
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response["Error"].get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            # Doesn't exist
            return False
        if code in ("403", "AccessDenied", "Forbidden"):
            # No permission to check – safest option here is to assume it
            # doesn't exist so we can still write.
            print(
                f"[CP] WARNING: no permission to HEAD s3://{bucket}/{key} "
                f"(Error code: {code}). Assuming it does not exist."
            )
            return False
        # Anything else is unexpected – re-raise
        raise


def copy_objects(
    src_bucket: str,
    dst_bucket: str,
    tile_id: str | None,
    dst_root_prefix: str,
    dry_run: bool = False,
    overwrite: bool = False,
) -> None:
    """
    Core logic:

    - Resolve user prefix from STS (USER_PREFIX)
    - Build src_prefix: USER_PREFIX/eds/tiles[/tile_id]/
    - Build dst_prefix: dst_root_prefix[/tile_id]/
    - For each object under src_prefix:
        - Map to dst_key preserving everything after src_prefix
        - Copy to dst_bucket/dst_key (unless exists and not overwrite)
    """
    s3_client = boto3.client("s3")

    user_prefix = get_user_prefix_from_sts()
    print(f"[CP] Using user prefix from STS: {user_prefix}")

    # Build source and destination prefixes
    src_prefix = f"{user_prefix}/eds/tiles/"
    if tile_id:
        src_prefix = f"{src_prefix}{tile_id}/"

    dst_prefix = dst_root_prefix.rstrip("/") + "/"
    if tile_id:
        dst_prefix = f"{dst_prefix}{tile_id}/"

    print(f"[CP] Source bucket: {src_bucket}")
    print(f"[CP] Source prefix: {src_prefix}")
    print(f"[CP] Dest bucket:   {dst_bucket}")
    print(f"[CP] Dest prefix:   {dst_prefix}")
    print(f"[CP] Dry run:       {dry_run}")
    print(f"[CP] Overwrite:     {overwrite}")
    print("")

    # Iterate over source objects
    count_total = 0
    count_copied = 0
    count_skipped_exists = 0

    for obj in iter_source_objects(s3_client, src_bucket, src_prefix):
        src_key = obj["Key"]
        count_total += 1

        # Derive dst_key by replacing the src_prefix with dst_prefix
        if not src_key.startswith(src_prefix):
            # Defensive: should not happen because we filtered by Prefix
            print(f"[CP] WARNING: key {src_key} does not start with {src_prefix}, skipping.")
            continue

        suffix = src_key[len(src_prefix) :]  # e.g. "sr/2023/202310/ls89sr_p104r070_20231002_nbart6m.tif"
        dst_key = dst_prefix + suffix

        if not overwrite and object_exists(s3_client, dst_bucket, dst_key):
            print(f"[CP] Exists in dest, skipping: s3://{dst_bucket}/{dst_key}")
            count_skipped_exists += 1
            continue

        if dry_run:
            print(f"[CP] Would copy: s3://{src_bucket}/{src_key}")
            print(f"              -> s3://{dst_bucket}/{dst_key}")
        else:
            print(f"[CP] Copying: s3://{src_bucket}/{src_key}")
            print(f"          -> s3://{dst_bucket}/{dst_key}")
            copy_source = {"Bucket": src_bucket, "Key": src_key}
            s3_client.copy(copy_source, dst_bucket, dst_key)

        count_copied += 1

    print("\n[CP] Summary")
    print(f"  Total source objects scanned: {count_total}")
    print(f"  Copied (or would copy in dry-run): {count_copied}")
    print(f"  Skipped (already existed): {count_skipped_exists}")
    print("[CP] Done.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy EDS SR/FC/ffmask products from dcceew-prod-user-scratch "
        "into eia-satellite, preserving eds/tiles/... folder structure."
    )

    parser.add_argument(
        "--src-bucket",
        default="dcceew-prod-user-scratch",
        help="Source S3 bucket (default: dcceew-prod-user-scratch)",
    )
    parser.add_argument(
        "--dst-bucket",
        default="eia-satellite",
        help="Destination S3 bucket (default: eia-satellite)",
    )
    parser.add_argument(
        "--tile-id",
        type=str,
        default=None,
        help="Optional tile ID (e.g. p104r070). If omitted, copies ALL tiles under eds/tiles.",
    )
    parser.add_argument(
        "--dst-root-prefix",
        type=str,
        default="eds/tiles",
        help="Destination root prefix under dst-bucket (default: 'eds/tiles').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="If set, do not copy anything, only print planned operations.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="If set, overwrite existing objects in destination. Default: skip existing.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    copy_objects(
        src_bucket=args.src_bucket,
        dst_bucket=args.dst_bucket,
        tile_id=args.tile_id,
        dst_root_prefix=args.dst_root_prefix,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()

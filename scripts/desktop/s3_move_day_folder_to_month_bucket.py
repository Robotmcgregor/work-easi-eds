#!/usr/bin/env python3
"""S3 key migrator: day-folder (YYYYMMDD) -> month-folder (YYYYMM).

This script scans an S3 bucket/prefix and identifies objects whose key contains
an 8-digit date folder immediately after a 4-digit year folder:

  .../<YYYY>/<YYYYMMDD>/...

It proposes (or applies) a rename to:

  .../<YYYY>/<YYYYMM>/...

Only the *folder segment* is changed; filenames are left untouched.

By default this runs in dry-run mode and prints proposed changes.
To apply changes, pass --apply.

Example:
  python scripts/s3_move_day_folder_to_month_bucket.py \
    --bucket dcceew-eds-data \
    --prefix "ARO...:robotmcgregor/eds/optimised/tiles/" \
    --dry-run

Apply:
  python scripts/s3_move_day_folder_to_month_bucket.py \
    --bucket dcceew-eds-data \
    --prefix "ARO...:robotmcgregor/eds/optimised/tiles/" \
    --apply
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional, Tuple

import boto3
from botocore.exceptions import ClientError


_YEAR_RE = re.compile(r"^\d{4}$")
_YYYYMMDD_RE = re.compile(r"^\d{8}$")


@dataclass(frozen=True)
class ProposedMove:
    old_key: str
    new_key: str


def _iter_year_dayfolder_rewrites(key: str) -> Iterator[ProposedMove]:
    """Yield ProposedMove(s) for each rewrite opportunity within a key.

    We only rewrite when a 4-digit year segment is followed by an 8-digit
    yyyymmdd segment that starts with the year.

    Example:
      tiles/p089r084/2022/20220101/file.tif
        -> tiles/p089r084/2022/202201/file.tif

    Note: A key could theoretically contain multiple such patterns; we rewrite
    all occurrences deterministically left-to-right.
    """
    parts = key.split("/")
    if len(parts) < 3:
        return

    rewritten = False
    new_parts = list(parts)

    for i in range(len(parts) - 1):
        year_seg = parts[i]
        next_seg = parts[i + 1]

        if not _YEAR_RE.fullmatch(year_seg):
            continue
        if not _YYYYMMDD_RE.fullmatch(next_seg):
            continue
        if not next_seg.startswith(year_seg):
            continue

        yyyymm = next_seg[:6]
        if yyyymm == next_seg:
            continue

        new_parts[i + 1] = yyyymm
        rewritten = True

    if rewritten:
        new_key = "/".join(new_parts)
        if new_key != key:
            yield ProposedMove(old_key=key, new_key=new_key)


def _compute_rewrite(key: str) -> Optional[ProposedMove]:
    """Compute the final rewritten key (if any) for a given key."""
    # _iter_year_dayfolder_rewrites currently yields at most one, but keep it generic.
    last: Optional[ProposedMove] = None
    for proposed in _iter_year_dayfolder_rewrites(key):
        last = proposed
    return last


def _head_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _copy_then_delete(
    s3_client,
    bucket: str,
    old_key: str,
    new_key: str,
    *,
    overwrite: bool,
    delete_source: bool,
) -> Tuple[bool, str]:
    """Copy old_key -> new_key then optionally delete old_key.

    Returns: (moved, reason)
    """
    if (not overwrite) and _head_exists(s3_client, bucket, new_key):
        return False, "target-exists"

    copy_source = {"Bucket": bucket, "Key": old_key}

    # Copy preserving metadata and content-type.
    s3_client.copy_object(
        Bucket=bucket,
        Key=new_key,
        CopySource=copy_source,
        MetadataDirective="COPY",
    )

    if delete_source:
        s3_client.delete_object(Bucket=bucket, Key=old_key)

    return True, "moved"


def iter_s3_keys(s3_client, bucket: str, prefix: str) -> Iterable[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj.get("Key")
            if key:
                yield key


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Move S3 keys from .../<YYYY>/<YYYYMMDD>/... to .../<YYYY>/<YYYYMM>/..."
    )

    ap.add_argument("--bucket", required=True, help="S3 bucket name")
    ap.add_argument(
        "--prefix",
        default="",
        help="Only scan keys under this prefix (recommended).",
    )

    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed changes only (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (copy then delete source).",
    )

    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after proposing/applying N moves (0 = no limit).",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting if the target key already exists.",
    )
    ap.add_argument(
        "--keep-source",
        action="store_true",
        help="When applying, keep the source key (copy only, no delete).",
    )
    ap.add_argument(
        "--check-target-exists",
        action="store_true",
        help="In dry-run, also check whether the target key already exists (slower).",
    )

    args = ap.parse_args()

    # default to dry-run unless --apply provided
    if not args.apply:
        args.dry_run = True

    return args


def main() -> int:
    args = parse_args()

    s3 = boto3.client("s3")

    scanned = 0
    proposed = 0
    applied = 0
    skipped_exists = 0

    print(f"[INFO] Bucket: {args.bucket}")
    print(f"[INFO] Prefix: {args.prefix!r}")
    print(f"[INFO] Mode  : {'APPLY' if args.apply else 'DRY-RUN'}")

    for key in iter_s3_keys(s3, args.bucket, args.prefix):
        scanned += 1

        rewrite = _compute_rewrite(key)
        if not rewrite:
            continue

        proposed += 1

        exists_note = ""
        if args.dry_run and args.check_target_exists:
            try:
                exists = _head_exists(s3, args.bucket, rewrite.new_key)
                exists_note = " [TARGET EXISTS]" if exists else ""
            except ClientError as e:
                exists_note = f" [TARGET CHECK ERROR: {e.response.get('Error', {}).get('Code', 'unknown')}]"

        print(f"{rewrite.old_key} -> {rewrite.new_key}{exists_note}")

        if args.apply:
            try:
                moved, reason = _copy_then_delete(
                    s3,
                    args.bucket,
                    rewrite.old_key,
                    rewrite.new_key,
                    overwrite=bool(args.overwrite),
                    delete_source=(not args.keep_source),
                )
                if moved:
                    applied += 1
                elif reason == "target-exists":
                    skipped_exists += 1
                    print(f"[SKIP] Target exists: {rewrite.new_key}")
                else:
                    print(f"[SKIP] {reason}: {rewrite.old_key}")
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "unknown")
                msg = e.response.get("Error", {}).get("Message", "")
                print(f"[ERROR] {code}: {msg} (key={rewrite.old_key})")

        if args.limit and proposed >= args.limit:
            print(f"[INFO] Limit reached: {args.limit}")
            break

    print("[SUMMARY]")
    print(f"- scanned : {scanned}")
    print(f"- proposed: {proposed}")
    if args.apply:
        print(f"- applied : {applied}")
        print(f"- skipped (target exists): {skipped_exists}")

    if args.dry_run and not args.apply:
        print("[INFO] Dry-run complete (no changes applied).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

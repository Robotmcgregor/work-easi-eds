#!/usr/bin/env python
"""
Rename FMASK files to standardized format.

Converts from: ga_ls8c_oa_3-0-0_089078_2013-07-16_final_fmask.tif
To: ga_ls8c_oa_089078_20130716_fmask.tif

Removes version numbers (3-0-0, 3-2-1), _final suffix, and converts dates.
"""

import os
import re
from pathlib import Path
import argparse


def standardize_fmask_filename(original_name):
    """Convert original GA FMASK filename to standardized format."""

    # Pattern to match: ga_ls8c_oa_3-0-0_089078_2013-07-16_final_fmask.tif
    pattern = r"^(ga_ls\d+[a-z]_oa)_\d+-\d+-\d+_(\d{6})_(\d{4})-(\d{2})-(\d{2})_final_fmask\.tif$"
    match = re.match(pattern, original_name, re.IGNORECASE)

    if match:
        sensor_prefix = match.group(1)  # ga_ls8c_oa
        pathrow = match.group(2)  # 089078
        year = match.group(3)  # 2013
        month = match.group(4)  # 07
        day = match.group(5)  # 16

        # Create standardized name
        date_standardized = f"{year}{month}{day}"  # 20130716
        new_name = f"{sensor_prefix}_{pathrow}_{date_standardized}_fmask.tif"
        return new_name

    return None


def rename_fmask_files(root_dir, dry_run=True):
    """Rename all FMASK files in the directory tree."""

    root_path = Path(root_dir)
    if not root_path.exists():
        print(f"ERROR: Directory does not exist: {root_dir}")
        return

    renamed_count = 0
    skipped_count = 0
    error_count = 0

    print(f"Scanning for FMASK files in: {root_path}")

    for fmask_file in root_path.rglob("*fmask*.tif"):
        original_name = fmask_file.name

        # Skip files that are already standardized
        if re.match(r"^ga_ls\d+[a-z]_oa_\d{6}_\d{8}_fmask\.tif$", original_name):
            print(f"[SKIP] Already standardized: {original_name}")
            skipped_count += 1
            continue

        # Generate new standardized name
        new_name = standardize_fmask_filename(original_name)

        if not new_name:
            print(f"[SKIP] Cannot parse: {original_name}")
            skipped_count += 1
            continue

        new_path = fmask_file.parent / new_name

        if new_path.exists():
            print(f"[SKIP] Target exists: {original_name} -> {new_name}")
            skipped_count += 1
            continue

        print(f"[RENAME] {original_name} -> {new_name}")

        if not dry_run:
            try:
                fmask_file.rename(new_path)
                renamed_count += 1
            except Exception as e:
                print(f"[ERROR] Failed to rename {original_name}: {e}")
                error_count += 1
        else:
            renamed_count += 1

    print(f"\n=== Summary ===")
    print(f"Files to be renamed: {renamed_count}")
    print(f"Files skipped: {skipped_count}")
    print(f"Errors: {error_count}")

    if dry_run:
        print(
            "\n[DRY RUN] No files were actually renamed. Use --execute to perform renames."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Rename FMASK files to standardized format"
    )
    parser.add_argument(
        "--root", default=r"D:\data\lsat", help="Root directory to scan"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually rename files (default is dry run)",
    )

    args = parser.parse_args()

    rename_fmask_files(args.root, dry_run=not args.execute)


if __name__ == "__main__":
    main()

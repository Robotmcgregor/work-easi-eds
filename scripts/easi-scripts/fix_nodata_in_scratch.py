#!/usr/bin/env python
"""
fix_nodata_in_scratch.py

Walk through an EDS tiles scratch tree and ensure GeoTIFF nodata metadata
is correctly set so ArcGIS/QGIS treat coded values as transparent.

Rules:
- Files starting with "ls89sr_"  → nodata = -999
- Files starting with "galsfc3_" → nodata = 255
- Other files (e.g. ffmask) are left untouched.

By default, scans:  ~/scratch/eds/tiles

Usage examples
--------------

Dry run (print what would be updated, but do nothing):

    python fix_nodata_in_scratch.py --dry-run

Actually update nodata metadata:

    python fix_nodata_in_scratch.py

Optionally point at a different root:

    python fix_nodata_in_scratch.py --root /home/jovyan/scratch/eds/tiles/p104r070
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rioxarray  # type: ignore


def parse_args() -> argparse.Namespace:
    home = Path.home()
    default_root = home / "scratch" / "eds" / "tiles"

    parser = argparse.ArgumentParser(
        description="Fix nodata metadata for SR/FC GeoTIFFs in EDS scratch."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help=f"Root directory to scan (default: {default_root})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be changed, but do not overwrite any files.",
    )
    return parser.parse_args()


def set_nodata_in_file(path: Path, nodata_value: float, dry_run: bool = False) -> None:
    """
    Open a GeoTIFF with rioxarray, set nodata metadata, and overwrite the file.

    We do NOT change the CRS or the actual pixel values; we simply add/update
    the nodata tag so viewers treat that code as transparent.
    """
    print(f"[FILE] {path}")
    try:
        da = rioxarray.open_rasterio(path, masked=False)
    except Exception as e:
        print(f"  [WARN] Could not open with rioxarray: {e}")
        return

    try:
        current_nodata = da.rio.nodata
    except Exception:
        current_nodata = None

    print(f"  [DEBUG] current nodata: {current_nodata}")
    print(f"  [DEBUG] desired nodata: {nodata_value}")

    # If it's already correct, skip to save time
    if current_nodata == nodata_value:
        print("  [SKIP] nodata already set to desired value.")
        return

    if dry_run:
        print("  [DRY-RUN] Would update nodata and rewrite file.")
        return

    # Preserve dtype
    dtype = da.dtype
    print(f"  [DEBUG] dtype={dtype}, dims={da.dims}")

    # Write nodata metadata (encoded=True = stored as this numeric code)
    da2 = da.rio.write_nodata(nodata_value, encoded=True, inplace=False)

    # Overwrite the file in place
    da2 = da2.astype(dtype)
    da2.rio.to_raster(path)
    print("  [ACTION] Updated nodata and rewrote file.")


def main() -> None:
    args = parse_args()
    root: Path = args.root
    dry_run: bool = args.dry_run

    if not root.exists():
        print(f"[ERROR] Root directory does not exist: {root}")
        return

    print(f"[INFO] Scanning for GeoTIFFs under: {root}")
    print(f"[INFO] Dry run: {dry_run}")

    # Counters for a quick summary
    total_files = 0
    updated = 0
    skipped = 0

    for tif_path in root.rglob("*.tif"):
        total_files += 1
        name = tif_path.name

        if name.startswith("ls89sr_"):
            # Surface reflectance → nodata -999
            before = updated
            set_nodata_in_file(tif_path, nodata_value=-999.0, dry_run=dry_run)
            if not dry_run and before != updated:
                updated += 1
        elif name.startswith("galsfc3_"):
            # Fractional cover → nodata 255
            before = updated
            set_nodata_in_file(tif_path, nodata_value=255.0, dry_run=dry_run)
            if not dry_run and before != updated:
                updated += 1
        else:
            # ffmask or other files; ignore
            skipped += 1
            # Uncomment if you want to see them:
            # print(f"[SKIP] Not an SR/FC composite: {tif_path}")

    print("\n[SUMMARY]")
    print(f"  Total .tif files scanned: {total_files}")
    print(f"  Potential SR/FC files:   {total_files - skipped}")
    print(f"  Dry run:                 {dry_run}")
    if not dry_run:
        print(f"  Files updated (nodata):  {updated}")


if __name__ == "__main__":
    main()

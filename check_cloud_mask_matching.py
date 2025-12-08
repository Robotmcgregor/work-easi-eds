#!/usr/bin/env python3
"""
Check cloud mask (FMASK) matching for FC files.
This script analyzes which FC files have corresponding FMASK files
and checks for dimension compatibility issues.
"""

import os
import re
from pathlib import Path
from osgeo import gdal
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from datetime import datetime


def extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract YYYYMMDD date from filename."""
    match = re.search(r"(\d{8})", filename)
    return match.group(1) if match else None


def extract_tile_from_filename(filename: str) -> Optional[str]:
    """Extract path/row from filename."""
    # For FC files: ga_ls_fc_089078_20130716_fc3ms.tif
    fc_match = re.search(r"ga_ls_fc_(\d{6})_", filename)
    if fc_match:
        return fc_match.group(1)

    # For FMASK files: ga_ls8c_oa_089078_20130716_fmask.tif
    fmask_match = re.search(r"_oa_(\d{6})_", filename)
    if fmask_match:
        return fmask_match.group(1)

    return None


def get_file_dimensions(filepath: Path) -> Tuple[int, int]:
    """Get raster dimensions (width, height)."""
    ds = gdal.Open(str(filepath))
    if not ds:
        raise ValueError(f"Cannot open file: {filepath}")
    return ds.RasterXSize, ds.RasterYSize


def get_file_center_coords(filepath: Path) -> Tuple[float, float]:
    """Get the center coordinates of a raster file."""
    ds = gdal.Open(str(filepath))
    if not ds:
        raise ValueError(f"Cannot open file: {filepath}")

    gt = ds.GetGeoTransform()
    xsize, ysize = ds.RasterXSize, ds.RasterYSize

    # Calculate center coordinates
    center_x = gt[0] + gt[1] * xsize / 2
    center_y = gt[3] + gt[5] * ysize / 2

    return center_x, center_y


def find_closest_date_match(
    target_date: str, available_dates: List[str], max_days: int = 7
) -> Tuple[Optional[str], int]:
    """Find the closest date within max_days."""
    target_dt = datetime.strptime(target_date, "%Y%m%d")

    best_match = None
    best_diff = float("inf")

    for date_str in available_dates:
        try:
            date_dt = datetime.strptime(date_str, "%Y%m%d")
            diff_days = abs((target_dt - date_dt).days)

            if diff_days <= max_days and diff_days < best_diff:
                best_diff = diff_days
                best_match = date_str
        except ValueError:
            continue

    return best_match, int(best_diff) if best_match else -1


def main():
    base_dir = Path(r"D:\data\lsat\089_078")

    if not base_dir.exists():
        print(f"Directory does not exist: {base_dir}")
        return

    print("Analyzing FC and FMASK file matching...")
    print("=" * 60)

    # Collect all FC and FMASK files
    fc_files = []
    fmask_files = []

    for file_path in base_dir.rglob("*.tif"):
        if "_fc3ms.tif" in file_path.name and "_clr" not in file_path.name:
            fc_files.append(file_path)
        elif "_fmask.tif" in file_path.name:
            fmask_files.append(file_path)

    print(f"Found {len(fc_files)} FC files")
    print(f"Found {len(fmask_files)} FMASK files")

    # Organize FMASK files by tile and date for quick lookup
    fmask_by_tile = defaultdict(lambda: defaultdict(list))

    for fmask_file in fmask_files:
        tile_id = extract_tile_from_filename(fmask_file.name)
        date = extract_date_from_filename(fmask_file.name)

        if tile_id and date:
            fmask_by_tile[tile_id][date].append(fmask_file)

    print(f"\nFMASK files organized by tile:")
    for tile_id, dates in fmask_by_tile.items():
        print(
            f"  Tile {tile_id}: {len(dates)} unique dates, {sum(len(files) for files in dates.values())} total files"
        )

    # Analyze FC files and their matching
    exact_matches = 0
    proximity_matches = 0
    no_matches = 0
    dimension_mismatches = 0
    coord_mismatches = 0

    match_results = []

    print(f"\nAnalyzing FC file matches...")
    print("-" * 50)

    for fc_file in fc_files:
        fc_tile = extract_tile_from_filename(fc_file.name)
        fc_date = extract_date_from_filename(fc_file.name)

        if not fc_tile or not fc_date:
            print(f"SKIP: Cannot parse {fc_file.name}")
            continue

        result = {
            "fc_file": fc_file,
            "fc_tile": fc_tile,
            "fc_date": fc_date,
            "fmask_file": None,
            "fmask_date": None,
            "match_type": "none",
            "date_diff": -1,
            "dimension_match": False,
            "coord_match": False,
            "fc_dims": None,
            "fmask_dims": None,
            "fc_coords": None,
            "fmask_coords": None,
            "error": None,
        }

        try:
            # Get FC file info
            result["fc_dims"] = get_file_dimensions(fc_file)
            result["fc_coords"] = get_file_center_coords(fc_file)

            # Look for matching FMASK
            fmask_match = None
            match_type = "none"
            date_diff = -1

            if fc_tile in fmask_by_tile:
                # Check exact date match first
                if fc_date in fmask_by_tile[fc_tile]:
                    fmask_candidates = fmask_by_tile[fc_tile][fc_date]
                    if fmask_candidates:
                        fmask_match = fmask_candidates[0]  # Take first if multiple
                        match_type = "exact"
                        date_diff = 0

                # If no exact match, look for proximity match
                if not fmask_match:
                    available_dates = list(fmask_by_tile[fc_tile].keys())
                    closest_date, diff_days = find_closest_date_match(
                        fc_date, available_dates, max_days=7
                    )

                    if closest_date:
                        fmask_candidates = fmask_by_tile[fc_tile][closest_date]
                        if fmask_candidates:
                            fmask_match = fmask_candidates[0]
                            match_type = "proximity"
                            date_diff = diff_days

            if fmask_match:
                result["fmask_file"] = fmask_match
                result["fmask_date"] = extract_date_from_filename(fmask_match.name)
                result["match_type"] = match_type
                result["date_diff"] = date_diff

                # Check dimensions and coordinates
                try:
                    result["fmask_dims"] = get_file_dimensions(fmask_match)
                    result["fmask_coords"] = get_file_center_coords(fmask_match)

                    # Check dimension compatibility
                    result["dimension_match"] = (
                        result["fc_dims"] == result["fmask_dims"]
                    )

                    # Check coordinate proximity (within 1000m)
                    coord_diff = (
                        (result["fc_coords"][0] - result["fmask_coords"][0]) ** 2
                        + (result["fc_coords"][1] - result["fmask_coords"][1]) ** 2
                    ) ** 0.5
                    result["coord_match"] = coord_diff < 1000

                    if match_type == "exact":
                        exact_matches += 1
                    else:
                        proximity_matches += 1

                    if not result["dimension_match"]:
                        dimension_mismatches += 1

                    if not result["coord_match"]:
                        coord_mismatches += 1

                except Exception as e:
                    result["error"] = str(e)

            else:
                no_matches += 1

        except Exception as e:
            result["error"] = str(e)

        match_results.append(result)

    # Print summary
    print(f"\n=== CLOUD MASK MATCHING SUMMARY ===")
    print(f"Total FC files analyzed: {len(fc_files)}")
    print(f"")
    print(
        f"Exact date matches:      {exact_matches:3d} ({exact_matches/len(fc_files)*100:.1f}%)"
    )
    print(
        f"Proximity matches (≤7d): {proximity_matches:3d} ({proximity_matches/len(fc_files)*100:.1f}%)"
    )
    print(
        f"No matches found:        {no_matches:3d} ({no_matches/len(fc_files)*100:.1f}%)"
    )
    print(f"")
    print(
        f"Total with FMASK data:   {exact_matches + proximity_matches:3d} ({(exact_matches + proximity_matches)/len(fc_files)*100:.1f}%)"
    )
    print(f"")
    print(f"=== COMPATIBILITY ISSUES ===")
    print(f"Dimension mismatches:    {dimension_mismatches:3d}")
    print(f"Coordinate mismatches:   {coord_mismatches:3d}")

    # Show examples of problematic matches
    print(f"\n=== DIMENSION MISMATCH EXAMPLES ===")
    dim_mismatch_count = 0
    for result in match_results:
        if result["fmask_file"] and not result["dimension_match"]:
            print(f"{result['fc_file'].name}")
            print(f"  FC dims:    {result['fc_dims']}")
            print(f"  FMASK dims: {result['fmask_dims']}")
            print(f"  FMASK file: {result['fmask_file'].name}")
            print(f"  Date diff:  {result['date_diff']} days")
            print()

            dim_mismatch_count += 1
            if dim_mismatch_count >= 5:  # Show only first 5
                if dimension_mismatches > 5:
                    print(
                        f"... and {dimension_mismatches - 5} more dimension mismatches"
                    )
                break

    # Show coordinate mismatch examples
    print(f"\n=== COORDINATE MISMATCH EXAMPLES ===")
    coord_mismatch_count = 0
    for result in match_results:
        if (
            result["fmask_file"]
            and not result["coord_match"]
            and result["dimension_match"]
        ):
            fc_coords = result["fc_coords"]
            fmask_coords = result["fmask_coords"]
            coord_diff = (
                (fc_coords[0] - fmask_coords[0]) ** 2
                + (fc_coords[1] - fmask_coords[1]) ** 2
            ) ** 0.5

            print(f"{result['fc_file'].name}")
            print(f"  FC center:    ({fc_coords[0]:.0f}, {fc_coords[1]:.0f})")
            print(f"  FMASK center: ({fmask_coords[0]:.0f}, {fmask_coords[1]:.0f})")
            print(f"  Distance:     {coord_diff:.0f}m")
            print(f"  FMASK file:   {result['fmask_file'].name}")
            print()

            coord_mismatch_count += 1
            if coord_mismatch_count >= 3:  # Show only first 3
                if coord_mismatches > 3:
                    print(f"... and {coord_mismatches - 3} more coordinate mismatches")
                break

    # Show some successful matches
    print(f"\n=== SUCCESSFUL MATCH EXAMPLES ===")
    success_count = 0
    for result in match_results:
        if (
            result["fmask_file"]
            and result["dimension_match"]
            and result["coord_match"]
            and result["match_type"] == "exact"
        ):

            print(f"{result['fc_file'].name}")
            print(f"  Dimensions: {result['fc_dims']}")
            print(f"  FMASK file: {result['fmask_file'].name}")
            print(f"  Match type: {result['match_type']}")
            print()

            success_count += 1
            if success_count >= 3:
                break


if __name__ == "__main__":
    main()

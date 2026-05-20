#!/usr/bin/env python
"""
EDS Data Preparation Script

This script ensures all required data exists for EDS processing:
1. Checks/downloads SR start and end dates from GA if missing
2. Downloads 10 years of seasonal FC data (July-Oct) from GA
3. Applies clear masks to all FC data
4. Organizes data according to EDS folder structure

Usage:
    python prepare_eds_data.py --tile 089_078 --start-date 20230720 --end-date 20240831 --dest D:\data\lsat
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_script(script_path, args_list):
    """Run a Python script with arguments and return success/failure."""
    cmd = [sys.executable, str(script_path)] + args_list

    print(f"\nRunning: {' '.join(cmd)}")
    print("=" * 80)

    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running {script_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Prepare all data required for EDS processing"
    )
    parser.add_argument("--tile", required=True, help="Tile in format 089_078")
    parser.add_argument(
        "--start-date", required=True, help="Start date in YYYYMMDD format"
    )
    parser.add_argument("--end-date", required=True, help="End date in YYYYMMDD format")
    parser.add_argument(
        "--dest", required=True, help="Destination directory (e.g., D:\\data\\lsat)"
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2014,
        help="Start year for seasonal FC data (default: 2014)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2024,
        help="End year for seasonal FC data (default: 2024)",
    )
    parser.add_argument(
        "--seasonal-months",
        nargs="+",
        type=int,
        default=[7, 8, 9, 10],
        help="Seasonal months for FC data (default: 7 8 9 10 for July-October)",
    )
    parser.add_argument(
        "--cloud-threshold",
        type=float,
        default=50,
        help="Max cloud cover % (default: 50)",
    )
    parser.add_argument(
        "--skip-sr",
        action="store_true",
        help="Skip SR date checking (assume they exist)",
    )
    parser.add_argument(
        "--skip-fc", action="store_true", help="Skip FC seasonal data download"
    )

    args = parser.parse_args()

    # Get script directory
    script_dir = Path(__file__).parent

    print(f"EDS Data Preparation for tile {args.tile}")
    print(f"Start date: {args.start_date}")
    print(f"End date: {args.end_date}")
    print(f"Destination: {args.dest}")
    print(f"FC years: {args.start_year}-{args.end_year}")
    print(f"Seasonal months: {args.seasonal_months}")

    # Step 1: Ensure SR start/end dates exist
    if not args.skip_sr:
        print(f"\n{'='*20} STEP 1: Checking SR Start/End Dates {'='*20}")

        sr_script = script_dir / "ensure_sr_dates_for_eds.py"
        sr_args = [
            "--tile",
            args.tile,
            "--start-date",
            args.start_date,
            "--end-date",
            args.end_date,
            "--dest",
            args.dest,
            "--cloud-threshold",
            str(args.cloud_threshold),
        ]

        sr_success = run_script(sr_script, sr_args)

        if not sr_success:
            print("ERROR: Failed to ensure SR start/end dates exist")
            return 1
    else:
        print("Skipping SR date checking (--skip-sr specified)")

    # Step 2: Download seasonal FC data
    if not args.skip_fc:
        print(f"\n{'='*20} STEP 2: Downloading Seasonal FC Data {'='*20}")

        fc_script = script_dir / "download_seasonal_fc_from_ga.py"
        fc_args = [
            "--tile",
            args.tile,
            "--start-year",
            str(args.start_year),
            "--end-year",
            str(args.end_year),
            "--dest",
            args.dest,
            "--cloud-threshold",
            str(args.cloud_threshold),
            "--seasonal-months",
        ] + [str(m) for m in args.seasonal_months]

        fc_success = run_script(fc_script, fc_args)

        if not fc_success:
            print("ERROR: Failed to download seasonal FC data")
            return 1
    else:
        print("Skipping FC data download (--skip-fc specified)")

    print(f"\n{'='*20} EDS Data Preparation Complete {'='*20}")
    print("All required data should now be available for EDS processing.")
    print(f"Data location: {args.dest}")

    # Summary of what should be available
    print(f"\nExpected data structure:")
    print(f"  {args.dest}/{args.tile}/")
    print(f"    ├── YYYY/YYYYMM/ (SR start/end dates)")
    print(
        f"    │   ├── ga_ls*c_ard_{args.tile.replace('_', '')}_{args.start_date}_srb*.tif"
    )
    print(
        f"    │   ├── ga_ls*c_ard_{args.tile.replace('_', '')}_{args.end_date}_srb*.tif"
    )
    print(f"    │   └── corresponding _fmask.tif files")
    print(f"    └── YYYY/YYYYMM/ (10 years seasonal FC July-Oct)")
    print(f"        ├── ga_ls_fc_{args.tile.replace('_', '')}_YYYYMMDD_fc3ms.tif")
    print(f"        └── ga_ls_fc_{args.tile.replace('_', '')}_YYYYMMDD_fc3ms_clr.tif")

    return 0


if __name__ == "__main__":
    sys.exit(main())

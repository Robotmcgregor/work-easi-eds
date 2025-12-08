#!/usr/bin/env python
"""
EDS Master Data Pipeline

Single entry point for downloading and preparing all satellite data required for EDS processing.
Orchestrates S3 downloads, GA DEA acquisition, and masking operations in the correct sequence.

Usage examples:
    python eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831
    C:\ProgramData\anaconda3\envs\slats\python.exe scripts\eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831 --span-years 10 --sr-root D:\data\lsat --fc-root D:\data\lsat --cloud-cover 50

Notes:
 - --sr-root / --fc-root are accepted as aliases for --dest for compatibility with the processing pipeline; they are optional.
 - --span-years controls how far back seasonal FC data is requested (capped by available archive starting ~2013).
 - FC end year defaults to min(current_year, end_year + 1); override with --fc-end-year if needed.
"""

import argparse
import subprocess
import sys
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def log_step(step_name, message):
    """Log a step with timestamp.

    This keeps console output consistent and easy to scan during long runs,
    and is intentionally lightweight so it works in any environment.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {step_name}: {message}")


def run_script(script_name, args_list, step_description, required=True):
    """Run a companion script with an argument list and uniform logging.

    - script_name: file expected to live alongside this script (in scripts/)
    - args_list: list of CLI tokens (already split; do not include Python path)
    - step_description: human-readable label in logs
    - required: if True, abort the pipeline on non-zero exit; otherwise continue

    Note: We deliberately avoid capture_output=True so child scripts stream
    their own logs to console, which is helpful for progress visualization.
    """
    script_path = Path(__file__).parent / script_name
    cmd = [sys.executable, str(script_path)] + args_list

    log_step("EXEC", f"{step_description}")
    log_step("CMD", f"{' '.join(cmd)}")
    print("=" * 80)

    try:
        start_time = time.time()
        result = subprocess.run(cmd, check=True, capture_output=False)
        elapsed = time.time() - start_time
        log_step("SUCCESS", f"{step_description} completed in {elapsed:.1f}s")
        return True
    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        log_step(
            "ERROR",
            f"{step_description} failed after {elapsed:.1f}s (exit code {e.returncode})",
        )

        if required:
            log_step("FATAL", "Required step failed - stopping pipeline")
            sys.exit(1)
        else:
            log_step("WARNING", "Optional step failed - continuing pipeline")
            return False
    except Exception as e:
        log_step("ERROR", f"Unexpected error in {step_description}: {e}")
        if required:
            sys.exit(1)
        return False


def validate_tile_in_database(tile_id):
    """Validate that the tile exists in the database and get its info.

    This uses a simple lookup on a `landsat_tiles` table and expects database
    connection settings via environment variables (loaded from .env if present):
      - DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME

    Returns (ok: bool, message: str)
    """
    load_dotenv()

    try:
        # Compose a standard SQLAlchemy PostgreSQL URL from environment vars.
        db_url = (
            f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@"
            f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
        )
        engine = create_engine(db_url)

        # Tile is provided like 089_078 -> path,row integers
        path, row = tile_id.split("_")

        with engine.connect() as conn:
            tile_query = """
            SELECT tile_id, path, row, bounds_geojson, status, is_active 
            FROM landsat_tiles 
            WHERE tile_id = :tile_id
              OR (path = :path AND row = :row)
            """

            # Query accepts either exact tile_id (089078) or path/row pair
            result = conn.execute(
                text(tile_query),
                {
                    "tile_id": path + row,  # 089078 format
                    "path": int(path),
                    "row": int(row),
                },
            )

            tile_data = result.fetchone()

            if not tile_data:
                return False, "Tile not found in database"

            if tile_data[5] is False:  # is_active flag false
                return False, f"Tile {tile_id} is marked as inactive"

            if tile_data[3]:  # bounds_geojson
                bounds = json.loads(tile_data[3])
                # Light sanity-check on stored bounds (should be Polygon)
                if bounds.get("type") == "Polygon" and "coordinates" in bounds:
                    return True, f"Tile {tile_id} found and active"
                else:
                    return False, "Invalid bounds geometry for tile"
            else:
                return False, "No bounds data found for tile"

    except Exception as e:
        return False, f"Database validation error: {e}"


def validate_date_format(date_str, param_name):
    """Validate date format (YYYYMMDD) and that it's a real calendar date."""
    try:
        if len(date_str) != 8 or not date_str.isdigit():
            raise ValueError(f"{param_name} must be in YYYYMMDD format")

        # Parse to check it's a valid calendar date (raises if not)
        datetime.strptime(date_str, "%Y%m%d")
        return True
    except ValueError as e:
        log_step("ERROR", f"Invalid {param_name}: {e}")
        return False


def calculate_seasonal_years(
    start_date_str, end_date_str, span_years, fc_end_year_override=None
):
    """Calculate the appropriate year range for seasonal FC data.

    fc_start_year: start_date_year - span_years (not earlier than 2013)
    fc_end_year:   end_date_year + 1 (not later than current year); can be overridden.
    """
    start_year = int(start_date_str[:4])
    end_year = int(end_date_str[:4])
    current_year = datetime.now().year
    # FC archive effectively starts around 2013 for GA products
    fc_start_year = max(2013, start_year - span_years)
    if fc_end_year_override:
        fc_end_year = int(fc_end_year_override)
    else:
        # Include one more year to cover the end-of-window season
        fc_end_year = min(current_year, end_year + 1)
    return fc_start_year, fc_end_year


def check_existing_data(tile, dest_dir):
    """Check what data already exists to optimize downloads.

    This is a quick local inventory (no network calls) used both for
    informative logging and potential future short-circuiting of steps.
    """
    tile_dir = Path(dest_dir) / tile

    existing_files = []
    if tile_dir.exists():
        existing_files = list(tile_dir.rglob("*.tif"))

    log_step("INFO", f"Found {len(existing_files)} existing files in {tile_dir}")

    # Count by type (restrict SR to Landsat 8/9 composites only)
    sr_files = [
        f
        for f in existing_files
        if (
            "_srb" in f.name
            and (f.name.startswith("ga_ls8c_ard_") or f.name.startswith("ga_ls9c_ard_"))
        )
    ]
    fc_files = [
        f for f in existing_files if "_fc3ms.tif" in f.name and "_clr" not in f.name
    ]
    fc_clr_files = [f for f in existing_files if "_fc3ms_clr.tif" in f.name]
    fmask_files = [f for f in existing_files if "_fmask.tif" in f.name]

    log_step(
        "INVENTORY",
        f"SR: {len(sr_files)}, FC: {len(fc_files)}, FC_CLR: {len(fc_clr_files)}, FMASK: {len(fmask_files)}",
    )

    return {
        "sr_files": len(sr_files),
        "fc_files": len(fc_files),
        "fc_clr_files": len(fc_clr_files),
        "fmask_files": len(fmask_files),
    }


def main():
    parser = argparse.ArgumentParser(
        description="EDS Master Data Pipeline - Download and prepare all satellite data for EDS processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python eds_master_data_pipeline.py --tile 089_078 --start-date 20230720 --end-date 20240831
  
  # Custom parameters
  python eds_master_data_pipeline.py \\
    --tile 089_078 \\
    --start-date 20230720 \\
    --end-date 20240831 \\
    --dest "E:\\satellite_data" \\
    --span-years 12 \\
    --cloud-cover 70 \\
    --search-days 14
        """,
    )

    # Required parameters (tile + date window)
    parser.add_argument(
        "--tile", required=True, help="Landsat WRS2 tile in format 089_078"
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date in YYYYMMDD format (e.g., 20230720)",
    )
    parser.add_argument(
        "--end-date", required=True, help="End date in YYYYMMDD format (e.g., 20240831)"
    )

    # Optional parameters with defaults
    # Destination roots (where data will be stored). On Windows we default to D:\data\lsat.
    parser.add_argument(
        "--dest",
        default="D:\\data\\lsat",
        help="Final destination directory (default: D:\\data\\lsat)",
    )
    # Optional temp workspace; if omitted we create a timestamped folder under C:\temp
    parser.add_argument(
        "--temp-dir",
        default=None,
        help="Temporary working directory (default: C:\\temp\\eds_processing)",
    )
    # How many years of seasonal FC to include (lookback relative to start-date)
    parser.add_argument(
        "--span-years",
        type=int,
        default=10,
        help="Years of seasonal FC data to download (default: 10)",
    )
    # Cloud cover threshold used by downloaders to filter scenes
    parser.add_argument(
        "--cloud-cover",
        type=float,
        default=50,
        help="Maximum cloud cover percentage (default: 50)",
    )
    # +/- day tolerance when matching SR to target start/end dates
    parser.add_argument(
        "--search-days",
        type=int,
        default=7,
        help="Days to search around target dates for SR (default: 7)",
    )
    # Compatibility aliases + override for the computed FC end year
    parser.add_argument(
        "--sr-root", help="Alias for --dest (logged if provided; --dest is used)"
    )
    parser.add_argument(
        "--fc-root", help="Alias for --dest (logged if provided; --dest is used)"
    )
    parser.add_argument(
        "--fc-end-year",
        help="Override computed FC end year (defaults to min(current_year, end_year+1))",
    )

    # Pipeline control
    parser.add_argument(
        "--skip-s3",
        action="store_true",
        help="Skip S3 download attempt (go straight to GA)",
    )
    parser.add_argument(
        "--skip-sr",
        action="store_true",
        help="Skip SR date checking (assume they exist)",
    )
    parser.add_argument(
        "--skip-fc", action="store_true", help="Skip FC seasonal data download"
    )
    parser.add_argument(
        "--skip-masking", action="store_true", help="Skip clear mask application"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing",
    )

    # Optional: Validate FC provenance at the end (LS8/LS9-only)
    parser.add_argument(
        "--validate-fc-provenance",
        action="store_true",
        help="After downloads and masking, run a provenance check to confirm FC is LS8/LS9-only",
    )
    parser.add_argument(
        "--prov-action",
        choices=["report", "move", "delete"],
        default="report",
        help="What to do with non-LS8/9 FC during validation (default: report)",
    )
    parser.add_argument(
        "--prov-search-days",
        type=int,
        default=7,
        help="SR fallback window (±days) used by the validator (default: 7)",
    )
    parser.add_argument(
        "--prov-quarantine-dir",
        default="_quarantine",
        help="When --prov-action move, directory under tile where files are moved (default: _quarantine)",
    )
    parser.add_argument(
        "--prov-out",
        default=None,
        help="Optional CSV report path for provenance results (default: data/fc_{tile}_provenance.csv)",
    )

    args = parser.parse_args()

    # Set up temporary directory (create a unique session folder if none provided)
    if args.temp_dir is None:
        args.temp_dir = f"C:\\temp\\eds_processing_{args.tile}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Pipeline start
    start_time = time.time()
    log_step("START", f"EDS Master Data Pipeline for tile {args.tile}")
    log_step("PARAMS", f"Dates: {args.start_date} to {args.end_date}")
    log_step("PARAMS", f"Final destination: {args.dest}")
    log_step("PARAMS", f"Temp workspace: {args.temp_dir}")
    log_step(
        "PARAMS",
        f"Span: {args.span_years} years, Cloud: {args.cloud_cover}%, Search: ±{args.search_days} days",
    )

    # Validation
    log_step("VALIDATE", "Checking parameters...")

    if not validate_date_format(args.start_date, "start-date"):
        sys.exit(1)
    if not validate_date_format(args.end_date, "end-date"):
        sys.exit(1)

    # Validate tile in database (helps catch typos and disabled tiles early)
    tile_valid, tile_msg = validate_tile_in_database(args.tile)
    if not tile_valid:
        log_step("ERROR", f"Tile validation failed: {tile_msg}")
        sys.exit(1)
    else:
        log_step("VALIDATE", tile_msg)

    # Set up directories (ensure both final destination and temp workspace exist)
    dest_path = Path(args.dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    log_step("VALIDATE", f"Final destination ready: {dest_path}")

    temp_path = Path(args.temp_dir)
    temp_path.mkdir(parents=True, exist_ok=True)
    log_step("VALIDATE", f"Temp workspace ready: {temp_path}")

    # Legacy compatibility: if sr-root/fc-root provided and differ from dest, prefer dest but log.
    if args.sr_root and args.sr_root != args.dest:
        log_step(
            "INFO",
            f"--sr-root provided ({args.sr_root}) differs from --dest ({args.dest}); using --dest for storage.",
        )
    if args.fc_root and args.fc_root != args.dest:
        log_step(
            "INFO",
            f"--fc-root provided ({args.fc_root}) differs from --dest ({args.dest}); using --dest for storage.",
        )

    # Calculate seasonal data range
    fc_start_year, fc_end_year = calculate_seasonal_years(
        args.start_date, args.end_date, args.span_years, args.fc_end_year
    )
    log_step("CALCULATE", f"FC seasonal data range: {fc_start_year}-{fc_end_year}")

    # Quick local inventory before making network calls
    existing = check_existing_data(args.tile, args.dest)

    if args.dry_run:
        log_step("DRY-RUN", "Would execute the following steps:")
        log_step("DRY-RUN", f"1. S3 FC download (skip: {args.skip_s3})")
        log_step("DRY-RUN", f"2. SR dates check (skip: {args.skip_sr})")
        log_step("DRY-RUN", f"3. GA FC download (skip: {args.skip_fc})")
        log_step("DRY-RUN", f"4. Apply masks (skip: {args.skip_masking})")
        return 0

    # Step 1: Try S3 download first (fast path)
    # This can quickly hydrate many FC months if an S3 mirror is available.
    if not args.skip_s3:
        log_step("STEP", "1/4 - Attempting S3 FC download (fast path)")
        log_step(
            "INFO",
            "S3 hydration now validates FC provenance via DEA STAC and will only download LS8/LS9-derived FC (L5/L7 items are skipped).",
        )

        # Convert dates to YYYYMM format for S3 script
        start_yyyymm = args.start_date[:6]  # YYYYMM
        end_yyyymm = args.end_date[:6]  # YYYYMM

        s3_args = [
            "--tile",
            args.tile,
            "--start-yyyymm",
            start_yyyymm,
            "--end-yyyymm",
            end_yyyymm,
            "--span-years",
            str(args.span_years),
            "--dest",
            args.dest,
            "--no-base-prefix",
        ]

        s3_success = run_script(
            "download_fc_from_s3.py", s3_args, "S3 FC download", required=False
        )

        if s3_success:
            log_step("SUCCESS", "S3 download completed - may have partial coverage")
    else:
        log_step("SKIP", "S3 download skipped per user request")

    # Step 2: Ensure SR start/end dates exist
    # This step queries GA/DEA to find acceptable SR for both endpoints of the window.
    if not args.skip_sr:
        log_step("STEP", "2/4 - Ensuring SR start/end dates exist")

        sr_args = [
            "--tile",
            args.tile,
            "--start-date",
            args.start_date,
            "--end-date",
            args.end_date,
            "--dest",
            args.dest,
            "--temp-dir",
            args.temp_dir,
            "--cloud-threshold",
            str(args.cloud_cover),
        ]

        run_script(
            "ensure_sr_dates_for_eds.py",
            sr_args,
            "SR dates verification",
            required=True,
        )
    else:
        log_step("SKIP", "SR dates check skipped per user request")

    # Step 3: Download seasonal FC data from GA (comprehensive)
    # Pull FC for seasonal months between the computed year bounds (may be many files).
    if not args.skip_fc:
        log_step("STEP", "3/4 - Downloading seasonal FC data from GA DEA")

        # Calculate months from start-date to end-date
        start_month = int(args.start_date[4:6])  # Extract month from YYYYMMDD
        end_month = int(args.end_date[4:6])  # Extract month from YYYYMMDD

        # Generate all months in the range (inclusive)
        if start_month <= end_month:
            # Same year or normal range (e.g., July to August)
            seasonal_months = [str(m) for m in range(start_month, end_month + 1)]
        else:
            # Crosses year boundary (e.g., October to March)
            seasonal_months = [
                str(m) for m in range(start_month, 13)
            ] + [  # Oct, Nov, Dec
                str(m) for m in range(1, end_month + 1)
            ]  # Jan, Feb, Mar

        # If span covers multiple years, include all 12 months for comprehensive coverage
        start_year = int(args.start_date[:4])
        end_year = int(args.end_date[:4])
        if end_year > start_year:
            seasonal_months = [str(m) for m in range(1, 13)]  # All 12 months

        log_step(
            "CALCULATE", f"Seasonal months to download: {', '.join(seasonal_months)}"
        )

        fc_args = [
            "--tile",
            args.tile,
            "--start-year",
            str(fc_start_year),
            "--end-year",
            str(fc_end_year),
            "--dest",
            args.dest,
            "--temp-dir",
            args.temp_dir,
            "--cloud-threshold",
            str(args.cloud_cover),
            "--seasonal-months",
        ] + seasonal_months

        run_script(
            "download_seasonal_fc_from_ga.py",
            fc_args,
            f"GA FC download ({fc_start_year}-{fc_end_year})",
            required=True,
        )
    else:
        log_step("SKIP", "FC seasonal download skipped per user request")

    # Step 4: Download FMASK files for FC data
    # FMASK is used to derive *clear* masks over FC imagery.
    if not args.skip_masking:
        log_step("STEP", "4/5 - Downloading FMASK files for FC clear masking")

        fmask_args = ["--tile", args.tile, "--root", args.dest]

        run_script(
            "download_fmask_for_fc.py",
            fmask_args,
            "FMASK download for FC masking",
            required=True,
        )

    # Step 5: Apply clear masks to FC data
    # This produces *_fc3ms_clr.tif files that the processing pipeline prefers.
    if not args.skip_masking:
        log_step("STEP", "5/5 - Applying clear masks to FC data")

        # Use correct arguments for derive_fc_clr.py
        mask_args = [
            "--root",
            str(args.dest),
            "--tile",
            args.tile,
            # FMASK files now downloaded
            "--search-days",
            str(args.search_days),
            "--clear-values",
            "1",
        ]

        # Check if masking script exists (it's in the repo). We accept several
        # possible script names to accommodate legacy naming.
        mask_script_names = ["mask_lsat.py", "derive_fc_clr.py", "qv_applystdmasks.py"]
        mask_script = None

        for script_name in mask_script_names:
            script_path = Path(__file__).parent / script_name
            if script_path.exists():
                mask_script = script_name
                break

        if mask_script:
            run_script(mask_script, mask_args, "Clear mask application", required=True)
        else:
            log_step(
                "WARNING", "No masking script found - FC data will not have clear masks"
            )
            log_step("INFO", f"Looked for: {mask_script_names}")
    else:
        log_step("SKIP", "Clear masking skipped per user request")

    # Optional Step 6: Validate FC provenance (LS8/LS9-only)
    if args.validate_fc_provenance and not args.dry_run:
        log_step("STEP", "6/6 - Validating FC provenance (LS8/LS9-only)")
        prov_out = args.prov_out
        if not prov_out:
            # Write to repo data/ by default
            prov_out = str(
                Path(__file__).resolve().parents[1]
                / "data"
                / f"fc_{args.tile}_provenance.csv"
            )
        prov_args = [
            "--tile",
            args.tile,
            "--root",
            args.dest,
            "--out",
            prov_out,
            "--action",
            args.prov_action,
            "--search-days",
            str(args.prov_search_days),
        ]
        if args.prov_action == "move":
            prov_args += ["--quarantine-dir", args.prov_quarantine_dir]
        run_script(
            "validate_fc_provenance.py",
            prov_args,
            "FC provenance validation",
            required=False,
        )

    # Final validation and summary
    log_step("VALIDATE", "Performing final data validation...")
    final_inventory = check_existing_data(args.tile, args.dest)

    total_time = time.time() - start_time
    log_step("COMPLETE", f"EDS data pipeline completed in {total_time:.1f}s")

    # Summary report
    print("\n" + "=" * 80)
    print("📊 FINAL DATA INVENTORY")
    print("=" * 80)
    print(f"🗂️  Tile: {args.tile}")
    print(f"📁 Location: {Path(args.dest) / args.tile}")
    print(f"📈 SR composites: {final_inventory['sr_files']}")
    print(f"🌿 FC products: {final_inventory['fc_files']}")
    print(f"✨ FC clear-masked: {final_inventory['fc_clr_files']}")
    print(f"🎭 Fmask products: {final_inventory['fmask_files']}")

    # Check if we have minimum required data for processing to proceed
    has_sr = final_inventory["sr_files"] >= 2  # start + end
    has_fc_clr = final_inventory["fc_clr_files"] > 0  # some seasonal data

    if has_sr and has_fc_clr:
        print("✅ SUCCESS: All required data types present")
        print("🚀 Ready for EDS processing!")
    else:
        print("⚠️  WARNING: Some required data may be missing")
        if not has_sr:
            print("   - Need SR composites for start/end dates")
        if not has_fc_clr:
            print("   - Need clear-masked FC seasonal data")

    print("=" * 80)

    # Cleanup temporary directory (best-effort; non-fatal if removal fails)
    if not args.dry_run:
        try:
            import shutil

            if temp_path.exists():
                shutil.rmtree(temp_path, ignore_errors=True)
                log_step("CLEANUP", f"Removed temporary directory: {temp_path}")
        except Exception as e:
            log_step("WARNING", f"Could not cleanup temp directory: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

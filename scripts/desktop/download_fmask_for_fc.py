#!/usr/bin/env python3
"""
Download FMASK files to match existing FC data.
This script looks for existing FC files and downloads corresponding FMASK files.
"""

import argparse
import json
import os
import re
import shutil
from pathlib import Path
import requests
import time
import tempfile


def download_file_with_progress(url, dest_path, max_retries=3):
    """Download a file with progress indication and retry logic."""

    # Convert S3 URLs to HTTP URLs
    if url.startswith("s3://dea-public-data/"):
        # Convert s3://dea-public-data/path to https://data.dea.ga.gov.au/path
        http_url = url.replace("s3://dea-public-data/", "https://data.dea.ga.gov.au/")
        print(f"  Converting S3 to HTTP: {http_url}")
        url = http_url

    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            with open(dest_path, "wb") as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            # Verify file was downloaded
            if dest_path.exists() and dest_path.stat().st_size > 0:
                print(f"  Downloaded: {dest_path.name} ({total_size:,} bytes)")
                return True
            else:
                print(f"  ERROR: Empty download - {dest_path.name}")
                if dest_path.exists():
                    dest_path.unlink()

        except Exception as e:
            print(f"  ERROR: Download failed (attempt {attempt + 1}): {e}")
            if dest_path.exists():
                dest_path.unlink()

            if attempt < max_retries - 1:
                print(f"  Retrying in 2 seconds...")
                time.sleep(2)

    return False


def search_stac_for_fmask(bbox, fc_date_str, path, row, search_window_days=7):
    """Search STAC for SR collections to get FMASK for dates near the FC date."""
    stac_url = "https://explorer.sandbox.dea.ga.gov.au/stac/search"

    # SR collections that might have FMASK
    sr_collections = [
        "ga_ls9c_ard_3",
        "ga_ls8c_ard_3",
        "ga_ls7e_ard_3",
        "ga_ls5t_ard_3",
    ]

    target_pathrow = f"{path.zfill(3)}{row.zfill(3)}"  # e.g., "089078"

    from datetime import datetime, timedelta

    fc_date = datetime.strptime(fc_date_str, "%Y-%m-%d")

    # Create a search window around the FC date
    start_date = fc_date - timedelta(days=search_window_days)
    end_date = fc_date + timedelta(days=search_window_days)

    date_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"

    best_match = None
    best_asset = None
    best_date_diff = float("inf")

    for collection in sr_collections:
        try:
            print(f"    Searching {collection} for {date_range}...")
            query = {
                "collections": [collection],
                "bbox": bbox,
                "datetime": date_range,
                "limit": 50,
            }

            response = requests.post(stac_url, json=query, timeout=30)
            response.raise_for_status()
            data = response.json()

            print(f"    Found {data.get('numberReturned', 0)} items in {collection}")

            if data.get("numberReturned", 0) > 0:
                for item in data["features"]:
                    # Check if item has FMASK asset
                    assets = item.get("assets", {})
                    fmask_asset = None

                    # Look for fmask asset (various naming patterns)
                    for asset_name, asset in assets.items():
                        if "fmask" in asset_name.lower():
                            fmask_asset = asset
                            break

                    if not fmask_asset:
                        continue

                    # Verify this is the right tile by checking path/row in the FMASK URL
                    fmask_url = fmask_asset["href"]

                    # Check if URL contains our target path/row
                    if target_pathrow in fmask_url or f"{path}/{row}" in fmask_url:
                        # Calculate date difference
                        item_date_str = item["properties"]["datetime"].split("T")[0]
                        item_date = datetime.strptime(item_date_str, "%Y-%m-%d")
                        date_diff = abs((fc_date - item_date).days)

                        if date_diff < best_date_diff:
                            best_match = item
                            best_asset = fmask_asset
                            best_date_diff = date_diff
                            print(
                                f"    Better match: {item_date_str} (diff: {date_diff} days)"
                            )

        except Exception as e:
            print(f"    STAC search error for {collection}: {e}")
            continue

    if best_match:
        print(f"    BEST MATCH: {best_date_diff} days difference")

    return best_match, best_asset


def extract_fc_info(fc_filename):
    """Extract path, row, and date from FC filename."""
    # Pattern: ga_ls_fc_089078_20130716_fc3ms.tif
    pattern = r"ga_ls_fc_(\d{3})(\d{3})_(\d{8})_fc3ms\.tif"
    match = re.match(pattern, fc_filename)

    if match:
        path = match.group(1)
        row = match.group(2)
        date = match.group(3)
        return path, row, date

    return None, None, None


def get_tile_bbox_from_db(tile_id):
    """Get tile bounding box from database."""
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    load_dotenv()
    db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    engine = create_engine(db_url)

    path, row = tile_id.split("_")

    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
            SELECT bounds_geojson 
            FROM landsat_tiles 
            WHERE tile_id = :tile_id
            OR (path = :path AND row = :row)
        """
            ),
            {"tile_id": path + row, "path": int(path), "row": int(row)},
        )

        row_data = result.fetchone()

        if not row_data:
            raise ValueError(f"Tile {tile_id} not found in database")

        # Parse GeoJSON to get bbox
        geojson = json.loads(row_data[0])
        coords = geojson["coordinates"][0]
        bbox = [coords[0][0], coords[0][1], coords[2][0], coords[2][1]]

        return bbox


def main():
    parser = argparse.ArgumentParser(
        description="Download FMASK files for existing FC data"
    )
    parser.add_argument("--tile", required=True, help="Tile in format 089_078")
    parser.add_argument(
        "--root", default="D:\\data\\lsat", help="Root directory containing tile data"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without downloading",
    )

    args = parser.parse_args()

    # Get tile bbox
    print(f"Getting bounding box for tile {args.tile}...")
    bbox = get_tile_bbox_from_db(args.tile)
    print(f"Bbox: {bbox}")

    # Find all FC files
    tile_dir = Path(args.root) / args.tile
    if not tile_dir.exists():
        print(f"ERROR: Tile directory not found: {tile_dir}")
        return 1

    fc_files = list(tile_dir.rglob("*fc3ms.tif"))
    print(f"Found {len(fc_files)} FC files")

    downloaded = 0
    skipped = 0
    failed = 0

    for fc_file in fc_files:
        path, row, date = extract_fc_info(fc_file.name)
        if not path or not row or not date:
            print(f"SKIP: Could not parse FC filename: {fc_file.name}")
            continue

        # Check if FMASK already exists (check both original and standardized names)
        standardized_patterns = [
            f"ga_ls*_oa_{path}{row}_{date}_fmask.tif",  # New standardized format
            f"ga_ls_fmask_{path}{row}_{date}_fmask.tif",  # Previous attempt format
        ]

        # Also check for original GA naming patterns
        original_patterns = [
            f"*{path}{row}*{date}*fmask*.tif",
            f"*{path}{row}*{date[:4]}-{date[4:6]}-{date[6:]}*fmask*.tif",
        ]

        existing_fmask = None

        # Check standardized patterns first
        for pattern in standardized_patterns:
            existing_fmask = list(fc_file.parent.glob(pattern))
            if existing_fmask:
                break

        # If not found, check original patterns
        if not existing_fmask:
            for pattern in original_patterns:
                existing_fmask = list(fc_file.parent.glob(pattern))
                if existing_fmask:
                    break

        if existing_fmask:
            print(f"EXISTS: {existing_fmask[0].name}")
            skipped += 1
            continue

        print(f"NEED: FMASK for {fc_file.name}")

        if args.dry_run:
            continue

        # Search for FMASK in STAC (with date proximity)
        date_formatted = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        stac_item, fmask_asset = search_stac_for_fmask(
            bbox, date_formatted, path, row, search_window_days=7
        )

        if not stac_item or not fmask_asset:
            print(f"  NOT FOUND: No STAC item with FMASK for {date_formatted}")
            failed += 1
            continue

        # Get the actual FMASK filename from the URL and standardize it
        fmask_url = fmask_asset["href"]
        fmask_url_filename = fmask_url.split("/")[-1]

        # Extract info from STAC item for standardized naming
        stac_props = stac_item["properties"]
        stac_title = stac_props["title"]
        stac_date = stac_props["datetime"].split("T")[0]  # YYYY-MM-DD

        # Extract sensor info from the original filename or STAC properties
        platform = stac_props.get("platform", "").replace("landsat-", "")
        if platform == "5":
            sensor_prefix = "ga_ls5t_oa"
        elif platform == "7":
            sensor_prefix = "ga_ls7e_oa"
        elif platform == "8":
            sensor_prefix = "ga_ls8c_oa"
        elif platform == "9":
            sensor_prefix = "ga_ls9c_oa"
        else:
            # Fallback - extract from original filename
            if "ls5t" in fmask_url_filename.lower():
                sensor_prefix = "ga_ls5t_oa"
            elif "ls7e" in fmask_url_filename.lower():
                sensor_prefix = "ga_ls7e_oa"
            elif "ls8c" in fmask_url_filename.lower():
                sensor_prefix = "ga_ls8c_oa"
            elif "ls9c" in fmask_url_filename.lower():
                sensor_prefix = "ga_ls9c_oa"
            else:
                sensor_prefix = "ga_ls_oa"  # Generic fallback

        # Standardize the FMASK filename: remove version numbers, _final, convert date
        date_standardized = stac_date.replace("-", "")  # YYYYMMDD
        standardized_name = f"{sensor_prefix}_{path}{row}_{date_standardized}_fmask.tif"
        fmask_path = fc_file.parent / standardized_name

        print(f"  Downloading FMASK: {fmask_url_filename}")
        print(f"  Saving as: {standardized_name}")
        print(f"  From: {fmask_url}")

        if download_file_with_progress(fmask_url, fmask_path):
            downloaded += 1
        else:
            failed += 1

        # Rate limiting
        time.sleep(1)

    print(f"\n=== FMASK Download Summary ===")
    print(f"Total FC files: {len(fc_files)}")
    print(f"Already existed: {skipped}")
    print(f"Downloaded: {downloaded}")
    print(f"Failed: {failed}")

    if args.dry_run:
        print("(Dry run - no files actually downloaded)")

    return 0


if __name__ == "__main__":
    exit(main())

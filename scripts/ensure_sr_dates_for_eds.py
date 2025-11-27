#!/usr/bin/env python
"""
Ensure SR start and end dates exist for EDS processing.

This script checks if the required SR composites for start and end dates exist,
and downloads them from GA if missing. It also ensures fmasks are available.

Usage:
    python ensure_sr_dates_for_eds.py --tile 089_078 --start-date 20230720 --end-date 20240831 --dest D:\data\lsat
"""

import os
import json
import urllib.request
import argparse
import shutil
import time
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import rasterio
import s3fs
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Create an anonymous S3 filesystem
fs = s3fs.S3FileSystem(anon=True)

# Band lists for different Landsat sensors
L57_BANDS = ['nbart_blue','nbart_green','nbart_red','nbart_nir','nbart_swir_1','nbart_swir_2']
L89_BANDS = ['nbart_coastal_aerosol','nbart_blue','nbart_green','nbart_red','nbart_nir','nbart_swir_1','nbart_swir_2']
ALLOWED_SENSORS = {"landsat-8", "landsat-9"}

def make_dir(directory):
    """Create a directory if it doesn't exist."""
    Path(directory).mkdir(parents=True, exist_ok=True)

def download_file(url, output_path, chunk_size=1024*1024):
    """Download a file from S3 or HTTPS to disk (streamed)."""
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Convert S3 URLs to HTTP for DEA public data
    if url.startswith("s3://dea-public-data/"):
        url = url.replace("s3://dea-public-data/", "https://data.dea.ga.gov.au/")
        print(f"Converted S3 URL to HTTP: {url}")

    print(f"Downloading {url}")
    
    try:
        if url.startswith("s3://"):
            # Use s3fs for other S3 URLs
            with fs.open(url, "rb") as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=chunk_size)
        else:
            # Use urllib for HTTP/HTTPS URLs with timeout
            import urllib.request
            import urllib.error
            
            request = urllib.request.Request(url)
            request.add_header('User-Agent', 'EDS-Pipeline/1.0')
            
            with urllib.request.urlopen(request, timeout=60) as resp, dest.open("wb") as dst:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(chunk)
    
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        if dest.exists():
            dest.unlink()  # Clean up partial download
        raise

    size = dest.stat().st_size if dest.exists() else 0
    print(f"Saved to: {dest.resolve()}")
    print(f"  file: {dest.name}  ({size:,} bytes)")

    # Add random sleep to avoid hammering the server
    sleep_time = random.uniform(1, 3)
    print(f"Sleeping {sleep_time:.2f} seconds to avoid rate limits...")
    time.sleep(sleep_time)

def search_stac(collection, bbox, time_range, limit=1000):
    """Query DEA STAC API for a collection."""
    root_url = "https://explorer.dea.ga.gov.au/stac"
    stac_url = (
        f"{root_url}/search?"
        f"collection={collection}"
        f"&time={time_range}"
        f"&bbox={str(bbox).replace(' ', '')}"
        f"&limit={limit}"
    )
    print(f"Querying STAC: {stac_url}")
    with urllib.request.urlopen(stac_url) as url:
        data = json.loads(url.read().decode())
    return data

def find_closest_sr_scene(target_date, path, row, bbox, search_days=30):
    """Find the closest SR scene to target date within search window."""
    from datetime import datetime, timedelta
    
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    start_search = target_dt - timedelta(days=search_days)
    end_search = target_dt + timedelta(days=search_days)
    
    time_range = f"{start_search.strftime('%Y-%m-%d')}/{end_search.strftime('%Y-%m-%d')}"
    print(f"Searching for SR scenes from {start_search.strftime('%Y-%m-%d')} to {end_search.strftime('%Y-%m-%d')}")
    
    # Priority list for SR collections (restricted to Landsat 8/9 only)
    collections = [
        "ga_ls9c_ard_3",
        "ga_ls8c_ard_3"
    ]
    
    all_scenes = []
    target_pathrow = f"{path.zfill(3)}{row.zfill(3)}"  # Ensure 3-digit format
    
    for collection in collections:
        try:
            data_sr = search_stac(collection, bbox, time_range)
            
            if data_sr.get("numberReturned", 0) > 0:
                for feature in data_sr["features"]:
                    # Verify path/row matches
                    properties = feature["properties"]
                    title = properties.get("title", "")
                    
                    # Extract path/row from title
                    pathrow_match = re.search(r'_(\d{6})_', title)
                    if pathrow_match:
                        scene_pathrow = pathrow_match.group(1)
                        if scene_pathrow == target_pathrow:
                            # Calculate date difference
                            scene_date_str = properties.get("datetime", "").split("T")[0]  # YYYY-MM-DD
                            if scene_date_str:
                                scene_dt = datetime.strptime(scene_date_str, "%Y-%m-%d")
                                date_diff = abs((target_dt - scene_dt).days)
                                platform = properties.get("platform", "unknown")
                                # Enforce Landsat 8/9 only
                                if platform in ALLOWED_SENSORS:
                                    all_scenes.append({
                                        'feature': feature,
                                        'collection': collection,
                                        'date': scene_date_str,
                                        'date_diff': date_diff,
                                        'platform': platform
                                    })
                                    print(f"Found scene: {title} (±{date_diff} days) [{platform}]")
        
        except Exception as e:
            print(f"Error searching {collection}: {e}")
            continue
    
    if not all_scenes:
        print(f"No SR scenes found within ±{search_days} days of {target_date}")
        return None
    
    # Sort by date difference (closest first)
    all_scenes.sort(key=lambda x: x['date_diff'])
    closest_scene = all_scenes[0]
    
    print(f"Closest scene: {closest_scene['feature']['properties']['title']} "
          f"(±{closest_scene['date_diff']} days from target)")
    
    return closest_scene

def process_sr_date(target_date, path, row, dest_dir, bbox, search_days=30):
    """Process a single SR date - check if exists, download closest available if missing."""
    
    # Format date strings
    date_str = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"  # YYYY-MM-DD
    year = target_date[:4]
    yearmonth = target_date[:6]
    
    # Create output paths
    pathrow_folder = f"{path}_{row}"
    output_base = Path(dest_dir) / pathrow_folder / year / yearmonth
    
    # Check if SR already exists (restrict to Landsat 8/9 composites in the year/month folder)
    sr_patterns = [
        f"ga_ls8c_ard_{path.zfill(3)}{row.zfill(3)}_*_srb6.tif",
        f"ga_ls8c_ard_{path.zfill(3)}{row.zfill(3)}_*_srb7.tif",
        f"ga_ls9c_ard_{path.zfill(3)}{row.zfill(3)}_*_srb6.tif",
        f"ga_ls9c_ard_{path.zfill(3)}{row.zfill(3)}_*_srb7.tif"
    ]
    
    existing_sr = None
    for pattern in sr_patterns:
        matches = list(output_base.glob(pattern))
        if matches:
            existing_sr = matches[0]
            break
    
    if existing_sr:
        print(f"[EXISTS] SR for {target_date}: {existing_sr.name}")
        return True, existing_sr.name
    
    print(f"[MISSING] SR for {target_date} - searching for closest available scene...")
    
    # Find closest SR scene
    closest_scene = find_closest_sr_scene(target_date, path, row, bbox, search_days)
    if not closest_scene:
        print(f"[ERROR] No SR scenes found within ±{search_days} days of {target_date}")
        return False, None
    
    stac_item = closest_scene['feature']
    properties = stac_item["properties"]
    title = properties["title"]
    actual_date = closest_scene['date'].replace('-', '')  # Convert back to YYYYMMDD
    
    # Determine sensor and expected band count
    sensor = properties["platform"]
    if sensor in ("landsat-8", "landsat-9"):
        sensor_bands = L89_BANDS
        expected_count = 7
    else:
        print(f"Skipping unsupported sensor for SR: {sensor} (allowed: Landsat 8/9)")
        return False, None
    
    # Parse title for standardized naming
    m = re.match(
        r'^(?P<prefix>ga_ls\d+c_ard)_3-2-1_(?P<pathrow>\d{6})_(?P<date>\d{4}-\d{2}-\d{2})(?:_(?P<tail>.+))?$',
        title
    )
    if m:
        prefix = m.group("prefix")
        pathrow = m.group("pathrow")
        date_c = m.group("date").replace("-", "")
    else:
        # Fallback naming
        prefix = f"ga_ls{sensor.replace('landsat-', '').replace('-', '')}c_ard"
        pathrow = f"{path.zfill(3)}{row.zfill(3)}"
        date_c = actual_date
    
    base_name = f"{prefix}_{pathrow}_{date_c}"
    
    # Update output directory to use actual scene date
    actual_year = actual_date[:4]
    actual_yearmonth = actual_date[:6]
    actual_output_base = Path(dest_dir) / pathrow_folder / actual_year / actual_yearmonth
    
    # Create temp working directory
    temp_dir = Path(r"C:\temp\eds_sr_download") / stac_item["id"]
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        os.chdir(temp_dir)
        
        # Download SR bands
        band_files = []
        for idx, band in enumerate(sensor_bands, start=1):
            if band in stac_item["assets"]:
                url = stac_item["assets"][band]["href"]
                filename = f"{title}_{band}.tif"
                download_file(url, filename)
                band_files.append(filename)
        
        if band_files:
            # Stack into SR composite
            sr_count = len(band_files)
            sr_filename = f"{base_name}_srb{sr_count}.tif"
            temp_sr_path = temp_dir / sr_filename
            
            # Stack bands
            with rasterio.open(band_files[0]) as src0:
                meta = src0.meta.copy()
            meta.update(count=len(band_files), compress="lzw")
            
            with rasterio.open(temp_sr_path, 'w', **meta) as dst:
                for band_id, layer_file in enumerate(band_files, start=1):
                    with rasterio.open(layer_file) as src1:
                        dst.write_band(band_id, src1.read(1))
            
            # Clean up individual band files
            for f in band_files:
                Path(f).unlink(missing_ok=True)
            
            # Create output directory and copy SR
            actual_output_base.mkdir(parents=True, exist_ok=True)
            final_sr_path = actual_output_base / sr_filename
            shutil.copy2(temp_sr_path, final_sr_path)
            print(f"[OK] SR saved: {final_sr_path}")
            
            # Also create a symlink in the target date folder for easier finding
            target_output_base = Path(dest_dir) / pathrow_folder / year / yearmonth
            target_output_base.mkdir(parents=True, exist_ok=True)
            symlink_path = target_output_base / sr_filename
            
            if not symlink_path.exists():
                try:
                    # Use relative path for symlink to be more portable
                    rel_path = os.path.relpath(final_sr_path, target_output_base)
                    symlink_path.symlink_to(rel_path)
                    print(f"[OK] Symlink created: {symlink_path}")
                except Exception as e:
                    print(f"[INFO] Could not create symlink: {e}")
        
        # Download fmask if available
        if "oa_fmask" in stac_item["assets"]:
            fmask_filename = f"{base_name}_fmask.tif"
            fmask_path = actual_output_base / fmask_filename
            
            if not fmask_path.exists():
                download_file(stac_item["assets"]["oa_fmask"]["href"], fmask_path)
                print(f"[OK] Fmask saved: {fmask_path}")
            else:
                print(f"[EXISTS] Fmask: {fmask_filename}")
        
        return True, sr_filename
    
    except Exception as e:
        print(f"Error processing SR for {target_date}: {e}")
        return False, None
    
    finally:
        # Clean up temp directory
        try:
            os.chdir(Path(dest_dir).parent)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass

def get_tile_bbox_from_db(tile_id):
    """Get bounding box for a tile from the database."""
    # Load environment variables
    load_dotenv()
    
    # Create database connection
    db_url = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    engine = create_engine(db_url)
    
    path, row = tile_id.split("_")
    
    with engine.connect() as conn:
        # Query for tile bounds
        tile_query = """
        SELECT tile_id, path, row, bounds_geojson 
        FROM landsat_tiles 
        WHERE tile_id = :tile_id
        OR (path = :path AND row = :row)
        """
        
        result = conn.execute(text(tile_query), {
            'tile_id': path + row,  # 089078 format
            'path': int(path),
            'row': int(row)
        })
        
        row_data = result.fetchone()
        
        if not row_data:
            raise ValueError(f"Tile {tile_id} not found in database")
        
        if row_data[3]:  # bounds_geojson
            bounds = json.loads(row_data[3])
            
            # Extract bbox from GeoJSON polygon
            if bounds.get('type') == 'Polygon' and 'coordinates' in bounds:
                coords = bounds['coordinates'][0]  # First ring of polygon
                lons = [coord[0] for coord in coords]
                lats = [coord[1] for coord in coords]
                bbox = [min(lons), min(lats), max(lons), max(lats)]
                return bbox
            else:
                raise ValueError(f"Invalid bounds geometry for tile {tile_id}")
        else:
            raise ValueError(f"No bounds data found for tile {tile_id}")

def main():
    parser = argparse.ArgumentParser(description="Ensure SR start and end dates exist for EDS processing")
    parser.add_argument("--tile", required=True, help="Tile in format 089_078")
    parser.add_argument("--start-date", required=True, help="Start date in YYYYMMDD format")
    parser.add_argument("--end-date", required=True, help="End date in YYYYMMDD format")
    parser.add_argument("--dest", required=True, help="Final destination directory (e.g., D:\\data\\lsat)")
    parser.add_argument("--temp-dir", default=None, help="Temporary working directory (default: auto-generated)")
    parser.add_argument("--cloud-threshold", type=float, default=10, help="Max cloud cover % (default: 10)")
    parser.add_argument("--search-days", type=int, default=30, help="Search window in days (±) for closest scenes (default: 30)")
    
    args = parser.parse_args()
    
    # Parse tile
    path, row = args.tile.split("_")
    
    # Get bounding box from database
    try:
        bbox = get_tile_bbox_from_db(args.tile)
        print(f"Tile {args.tile} bbox from database: {bbox}")
    except Exception as e:
        print(f"ERROR: Could not get bbox for tile {args.tile}: {e}")
        return
    
    # Process start and end dates
    print(f"\n=== Checking SR dates for tile {args.tile} ===")
    
    start_success, start_filename = process_sr_date(args.start_date, path, row, args.dest, bbox, args.search_days)
    end_success, end_filename = process_sr_date(args.end_date, path, row, args.dest, bbox, args.search_days)
    
    if start_success and end_success:
        print(f"\n[SUCCESS] Both SR dates are available:")
        print(f"  Start: {args.start_date} -> {start_filename or 'existing file'}")
        print(f"  End: {args.end_date} -> {end_filename or 'existing file'}")
    else:
        print(f"\n[WARNING] Some SR dates could not be processed:")
        if not start_success:
            print(f"  Failed: {args.start_date}")
        if not end_success:
            print(f"  Failed: {args.end_date}")

if __name__ == "__main__":
    main()
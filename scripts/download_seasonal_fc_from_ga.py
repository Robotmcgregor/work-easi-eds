#!/usr/bin/env python
"""
Download 10 years of seasonal FC data from GA DEA for EDS processing.

This script pulls Fractional Cover data from GA's DEA STAC API for a specific
tile and seasonal window (July-October), downloads and stacks the bands,
and applies clear masks.

Usage:
    python download_seasonal_fc_from_ga.py --tile 089_078 --start-year 2014 --end-year 2024 --dest D:\data\lsat
"""

import os
import json
import urllib.request
import argparse
import shutil
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
import s3fs
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Create an anonymous S3 filesystem for DEA access
fs = s3fs.S3FileSystem(anon=True)

# DEA fractional cover band names
FC_BANDS = ["bs", "pv", "npv"]  # bare soil, photosynthetic vegetation, non-photosynthetic vegetation
ALLOWED_SENSORS = {"landsat-8", "landsat-9"}

def make_dir(directory):
    """Create a directory if it doesn't exist."""
    Path(directory).mkdir(parents=True, exist_ok=True)

def download_file(url, output_path, chunk_size=1024*1024):
    """Download a file from S3 or HTTPS to disk (streamed)."""
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {url}")
    if url.startswith("s3://"):
        with fs.open(url, "rb") as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=chunk_size)
    else:
        with urllib.request.urlopen(url) as resp, dest.open("wb") as dst:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)

    size = dest.stat().st_size if dest.exists() else 0
    print(f"Saved to: {dest.resolve()}")
    print(f"  file: {dest.name}  ({size:,} bytes)")

    # Add random sleep to avoid hammering the server
    sleep_time = random.uniform(1, 5)
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

def apply_clear_mask(fc_path, fmask_path, output_path):
    """Apply clear mask (fmask value 1) to FC data using rasterio."""
    print(f"Applying clear mask: {fc_path}")
    
    with rasterio.open(fc_path) as fc_src, rasterio.open(fmask_path) as fmask_src:
        # Read FC data (all bands)
        fc_data = fc_src.read()
        
        # Read fmask data
        fmask_data = fmask_src.read(1)
        
        # Create clear mask (only keep pixels where fmask == 1, i.e., clear)
        clear_mask = fmask_data == 1
        
        # Apply mask to all FC bands
        fc_masked = fc_data.copy()
        for i in range(fc_data.shape[0]):
            fc_masked[i][~clear_mask] = 0
        
        # Write masked output
        meta = fc_src.meta.copy()
        meta.update(compress="lzw")
        
        with rasterio.open(output_path, 'w', **meta) as dst:
            dst.write(fc_masked)
    
    print(f"Clear masked FC saved: {output_path}")

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
    parser = argparse.ArgumentParser(description="Download seasonal FC data from GA DEA for EDS processing")
    parser.add_argument("--tile", required=True, help="Tile in format 089_078")
    parser.add_argument("--start-year", type=int, default=2014, help="Start year (default: 2014)")
    parser.add_argument("--end-year", type=int, default=2024, help="End year (default: 2024)")
    parser.add_argument("--dest", required=True, help="Final destination directory (e.g., D:\\data\\lsat)")
    parser.add_argument("--temp-dir", default=None, help="Temporary working directory (default: auto-generated)")
    parser.add_argument("--cloud-threshold", type=float, default=50, help="Max cloud cover % (default: 50)")
    parser.add_argument("--seasonal-months", nargs="+", type=int, default=[7, 8, 9, 10], 
                       help="Seasonal months to download (default: 7 8 9 10 for July-October)")
    
    args = parser.parse_args()
    
    # Set up temporary directory
    if args.temp_dir is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.temp_dir = f"C:\\temp\\eds_fc_{args.tile}_{timestamp}"
    
    temp_base = Path(args.temp_dir)
    temp_base.mkdir(parents=True, exist_ok=True)
    print(f"Using temporary workspace: {temp_base}")
    
    # Parse tile
    path, row = args.tile.split("_")
    
    # Get bounding box from database
    try:
        bbox = get_tile_bbox_from_db(args.tile)
        print(f"Tile {args.tile} bbox from database: {bbox}")
    except Exception as e:
        print(f"ERROR: Could not get bbox for tile {args.tile}: {e}")
        return
    
    # Process each year
    collection = "ga_ls_fc_3"
    dates_downloaded = set()
    
    for year in range(args.start_year, args.end_year + 1):
        print(f"\n=== Processing year {year} ===")
        
        # Create seasonal time range for this year
        seasonal_dates = []
        for month in args.seasonal_months:
            seasonal_dates.append(f"{year}-{month:02d}-01")
            # Add end of month
            if month in [1, 3, 5, 7, 8, 10, 12]:
                seasonal_dates.append(f"{year}-{month:02d}-31")
            elif month in [4, 6, 9, 11]:
                seasonal_dates.append(f"{year}-{month:02d}-30")
            else:  # February
                if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
                    seasonal_dates.append(f"{year}-{month:02d}-29")
                else:
                    seasonal_dates.append(f"{year}-{month:02d}-28")
        
        # Create time range string for the seasonal months
        time_ranges = []
        for i in range(0, len(seasonal_dates), 2):
            time_ranges.append(f"{seasonal_dates[i]}/{seasonal_dates[i+1]}")
        
        # Query each seasonal month range
        for time_range in time_ranges:
            print(f"Searching time range: {time_range}")
            
            try:
                data_fc = search_stac(collection, bbox, time_range)
            except Exception as e:
                print(f"Error querying STAC for {time_range}: {e}")
                continue
            
            if data_fc.get("numberReturned", 0) == 0:
                print(f"No FC data found for {time_range}")
                continue
            
            print(f"Found {data_fc['numberReturned']} FC scenes for {time_range}")
            
            # Filter by cloud cover, platform (LS8/9), and path/row directly from features
            filtered_features = []
            for feature in data_fc["features"]:
                cloud_cover = feature["properties"].get("eo:cloud_cover", 0)
                platform = feature["properties"].get("platform", "")
                
                # Extract path/row from the URL to ensure we only get the target tile
                target_pathrow = f"{path.zfill(3)}/{row.zfill(3)}"  # e.g., "089/078"
                
                # Check if this feature is for our target tile
                feature_pathrow = None
                for asset_name, asset in feature.get('assets', {}).items():
                    if asset_name in ['bs', 'pv', 'npv']:
                        url = asset['href']
                        url_parts = url.split('/')
                        # Look for path/row pattern in URL
                        for i, part in enumerate(url_parts):
                            if part.isdigit() and len(part) == 3 and i+1 < len(url_parts) and url_parts[i+1].isdigit() and len(url_parts[i+1]) == 3:
                                feature_pathrow = f"{part}/{url_parts[i+1]}"
                                break
                        break
                
                # Only include if platform is LS8/9, cloud cover is acceptable, and it's the correct tile
                if (platform in ALLOWED_SENSORS) and (cloud_cover < args.cloud_threshold) and (feature_pathrow == target_pathrow):
                    filtered_features.append(feature)
                elif platform not in ALLOWED_SENSORS:
                    print(f"[SKIP] Unsupported platform: {platform} (allowed: {sorted(ALLOWED_SENSORS)})")
                elif feature_pathrow != target_pathrow:
                    print(f"[SKIP] Wrong tile: {feature_pathrow} (wanted {target_pathrow})")
                    
            
            print(f"After cloud filter (<{args.cloud_threshold}%): {len(filtered_features)} scenes")
            
            if len(filtered_features) == 0:
                continue
            
            # Process each scene
            for stac_item in filtered_features:
                properties = stac_item["properties"]
                
                date_str = properties["datetime"].split("T")[0]
                date_clean = date_str.replace("-", "")
                
                if date_str in dates_downloaded:
                    print(f"Skipping {date_str} - already processed")
                    continue
                
                # Check if we already have this FC data
                year_dir = date_clean[:4]
                month_dir = date_clean[:6]
                
                pathrow_folder = args.tile
                output_base = Path(args.dest) / pathrow_folder / year_dir / month_dir
                
                fc_filename = f"ga_ls_fc_{path}{row}_{date_clean}_fc3ms.tif"
                fc_clr_filename = f"ga_ls_fc_{path}{row}_{date_clean}_fc3ms_clr.tif"
                
                fc_path = output_base / fc_filename
                fc_clr_path = output_base / fc_clr_filename
                
                if fc_path.exists():
                    print(f"[SKIP] Already exists: {fc_filename}")
                    dates_downloaded.add(date_str)
                    continue
                
                print(f"Processing FC scene for {date_str}")
                
                # Create scene-specific temp directory
                scene_temp = temp_base / "scenes" / stac_item["id"]
                scene_temp.mkdir(parents=True, exist_ok=True)
                
                try:
                    os.chdir(scene_temp)
                    
                    # Download FC bands
                    band_files = []
                    title = f"ga_ls_fc_3-2-1_{path}{row}_{date_str}_final"
                    
                    for band in FC_BANDS:
                        if band in stac_item["assets"]:
                            url = stac_item["assets"][band]["href"]
                            filename = f"{title}_{band}.tif"
                            download_file(url, filename)
                            band_files.append(filename)
                    
                    if len(band_files) == len(FC_BANDS):
                        # Stack bands into multi-layer FC raster
                        with rasterio.open(band_files[0]) as src0:
                            meta = src0.meta.copy()
                        meta.update(count=len(band_files), compress="lzw")
                        
                        temp_fc_stack = scene_temp / fc_filename
                        
                        with rasterio.open(temp_fc_stack, 'w', **meta) as dst:
                            for band_id, layer_file in enumerate(band_files, start=1):
                                with rasterio.open(layer_file) as src1:
                                    dst.write_band(band_id, src1.read(1))
                        
                        # Clean up individual band files
                        for f in band_files:
                            Path(f).unlink(missing_ok=True)
                        
                        # Create output directory and copy FC stack
                        output_base.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(temp_fc_stack, fc_path)
                        print(f"[OK] FC saved: {fc_path}")
                        
                        # Now we need the fmask for this date to apply clear mask
                        # Check if fmask exists locally first
                        fmask_filename = f"ga_ls{stac_item['id'].split('_')[1]}_ard_{path}{row}_{date_clean}_fmask.tif"
                        fmask_path = output_base / fmask_filename
                        
                        # If fmask doesn't exist, we need to download it from the SR collection
                        if not fmask_path.exists():
                            print(f"Fmask not found locally, attempting to download...")
                            
                            # Try to find corresponding SR scene to get fmask (restrict to LS8/9 only)
                            sr_collections = ["ga_ls9c_ard_3", "ga_ls8c_ard_3"]
                            
                            fmask_downloaded = False
                            for sr_collection in sr_collections:
                                try:
                                    sr_data = search_stac(sr_collection, bbox, f"{date_str}/{date_str}")
                                    if sr_data.get("numberReturned", 0) > 0:
                                        sr_item = sr_data["features"][0]
                                        if "oa_fmask" in sr_item["assets"]:
                                            download_file(sr_item["assets"]["oa_fmask"]["href"], fmask_path)
                                            fmask_downloaded = True
                                            break
                                except Exception as e:
                                    print(f"Error getting fmask from {sr_collection}: {e}")
                                    continue
                            
                            if not fmask_downloaded:
                                print(f"WARNING: Could not download fmask for {date_str}")
                                dates_downloaded.add(date_str)
                                continue
                        
                        # Apply clear mask
                        if fmask_path.exists():
                            apply_clear_mask(fc_path, fmask_path, fc_clr_path)
                            dates_downloaded.add(date_str)
                        else:
                            print(f"WARNING: Fmask not available for {date_str}, skipping clear mask")
                    
                    else:
                        print(f"Incomplete FC bands for {date_str} - got {len(band_files)}/{len(FC_BANDS)}")
                
                except Exception as e:
                    print(f"Error processing {date_str}: {e}")
                
                finally:
                    # Clean up scene temp directory
                    os.chdir(temp_base)
                    shutil.rmtree(scene_temp, ignore_errors=True)
    
    print(f"\n=== Processing complete ===")
    print(f"Downloaded and processed FC data for {len(dates_downloaded)} dates")
    print("All FC data has clear masks applied (_clr.tif files)")
    
    # Cleanup temporary workspace
    try:
        if temp_base.exists():
            shutil.rmtree(temp_base, ignore_errors=True)
            print(f"Cleaned up temporary workspace: {temp_base}")
    except Exception as e:
        print(f"Warning: Could not cleanup temp directory: {e}")

if __name__ == "__main__":
    main()
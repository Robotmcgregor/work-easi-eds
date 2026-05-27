import geopandas as gpd
import subprocess
from datetime import date
from pathlib import Path
import pandas as pd
import sys

# Path to your tiles shapefile
SHAPEFILE = "C:/Users/Rober/code/work-easi-eds/assets/eds-lsat-tiles.shp"  # Update if needed
# Path to NDVI pipeline script
NDVI_SCRIPT = "/home/jovyan/work-easi-eds/scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py"
# S3 and work dir settings
S3_BUCKET = "dcceew-eds-data"
S3_PREFIX = "eds"
WORK_DIR = "/home/jovyan/scratch/eds-work-optimised"
LOOKBACK = "10"

# Optionally, set a custom run log location (or use pipeline default)
# RUN_LOG_URI = "s3://.../runs/optimised_ndvi_runs.parquet"
RUN_LOG_URI = None

# Read all tile IDs from the shapefile (update 'tile' to your actual column name)
gdf = gpd.read_file(SHAPEFILE)
tile_col = 'tile' if 'tile' in gdf.columns else gdf.columns[0]  # fallback to first column if needed
tile_ids = gdf[tile_col].unique()

# Optionally, set end date to today, and omit start date for auto-resume
end_date = date.today().isoformat()

for tile in tile_ids:
    print(f"\n=== Processing tile: {tile} ===")
    # Optionally, check if this tile is already up to date by reading the run log
    # (This is handled by the pipeline, but you can skip tiles here if desired)

    ndvi_cmd = [
        "python", NDVI_SCRIPT,
        "--tile", str(tile),
        "--s3-bucket", S3_BUCKET,
        "--s3-prefix", S3_PREFIX,
        "--work-dir", WORK_DIR,
        "--end-date", end_date,
        "--lookback", LOOKBACK,
        "--run-eds-after",
        "--export-vectors-to-work-dir",
        "--cleanup-work-dir"
    ]
    if RUN_LOG_URI:
        ndvi_cmd += ["--run-log-uri", RUN_LOG_URI]

    try:
        subprocess.run(ndvi_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Pipeline failed for tile {tile}: {e}")
        # Optionally, continue to next tile or break
        continue
    print(f"[OK] Finished tile: {tile}")

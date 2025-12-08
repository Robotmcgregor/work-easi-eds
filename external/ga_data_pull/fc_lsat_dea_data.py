#!/usr/bin/env python
# coding: utf-8

import os
import json
import urllib.request
import geopandas as gpd
import numpy as np
from datetime import datetime, timedelta
import s3fs
import glob
import shutil
import time
import random
import rasterio

# Create an anonymous S3 filesystem
fs = s3fs.S3FileSystem(anon=True)

# DEA fractional cover band names
# According to DEA metadata, they are:
# - bs = bare soil
# - pv = photosynthetic vegetation
# - npv = non-photosynthetic vegetation
# - ue = unmixing error

fc_bands = ["bs", "pv", "npv"]


def download_file(url, output_path):
    """Download a file from S3 or HTTPS to disk."""
    print(f"Downloading {url}")
    if url.startswith("s3://"):
        with fs.open(url, "rb") as remote_file:
            with open(output_path, "wb") as out_file:
                out_file.write(remote_file.read())
    else:
        with urllib.request.urlopen(url) as response, open(
            output_path, "wb"
        ) as out_file:
            out_file.write(response.read())
    print(f"Saved to {output_path}")

    # Add random sleep
    sleep_time = random.uniform(1, 5)
    print(f"Sleeping {sleep_time:.2f} seconds to avoid rate limits...")
    time.sleep(sleep_time)


def search_stac(collection, bbox, time_range, limit=1000):
    """Query DEA STAC API for a collection."""
    root_url = "https://explorer.dea.ga.gov.au/stac"  # production DEA explorer
    stac_url = (
        f"{root_url}/search?"
        f"collection={collection}"
        f"&time={time_range}"
        f"&bbox={str(bbox).replace(' ', '')}"
        f"&limit={limit}"
    )
    print(f"Querying STAC URL:\n{stac_url}")
    with urllib.request.urlopen(stac_url) as url:
        data = json.loads(url.read().decode())
    return data


def make_dir(directory):
    """Create a directory if it doesn't exist."""
    if not os.path.exists(directory):
        os.makedirs(directory)
        print("directory created..", directory)


def main(path, row, output_dir, cloud_threshold):
    # Load WRS2 tile shapefile
    wrs2_path = r"C:\Users\RobMCGREGOR\code\s2_tile_grid\WRS2_AU_centroid_buff50m.shp"
    wrs2 = gpd.read_file(wrs2_path)
    path_row_value = int(path + row)
    path_row = wrs2[wrs2["WRSPR"] == path_row_value]

    if path_row.empty:
        print(f"Tile {path}{row} not found.")
        return

    bbox = list(path_row.total_bounds)
    bbox = [float(num) for num in np.array(bbox)]
    print(f"Tile {path}{row} bbox: {bbox}")

    # Compute date range
    end_date = datetime.today()
    start_date = end_date - timedelta(days=365 * 10)
    time_range = f"{start_date.date()}/{end_date.date()}"
    print(f"Searching date range: {time_range}")

    collection = "ga_ls_fc_3"
    data_fc = search_stac(collection, bbox, time_range)

    if data_fc.get("numberReturned", 0) == 0:
        print("No features returned.")
        return

    print(f"Found {data_fc['numberReturned']} scenes in {collection}")

    gdf = gpd.GeoDataFrame.from_features(data_fc["features"])

    if "eo:cloud_cover" not in gdf.columns:
        print("No cloud cover info. Skipping filtering.")
        cl = gdf
    else:
        cl = gdf[gdf["eo:cloud_cover"] < cloud_threshold]

    print(f"Total scenes after cloud filter: {len(cl)}")

    if len(cl) == 0:
        print("No scenes after cloud filter.")
        return

    indices = cl.index
    dates_downloaded = set()

    for i in indices:
        stac_item = data_fc["features"][i]
        properties = stac_item["properties"]

        date_str = properties["datetime"].split("T")[0]
        print(f"Processing date: {date_str}")

        if date_str in dates_downloaded:
            print(f"Skipping scene on {date_str} — already downloaded.")
            continue

        dates_downloaded.add(date_str)

        # Find any available asset URL
        sample_band = next((b for b in fc_bands if b in stac_item["assets"]), None)

        if sample_band is None:
            print(f"No fractional cover bands found for scene on {date_str}")
            continue

        # Use the first asset URL to extract path/row info
        url_sample = stac_item["assets"][sample_band]["href"]
        parts = url_sample.split("/")
        path_val = parts[6]  # 090
        row_val = parts[7]  # 084
        pathrow = path_val + row_val

        title = f"ga_ls_fc_3-2-1_{pathrow}_{date_str}_final"

        # Prepare output paths
        date_str_clean = date_str.replace("-", "")
        year = date_str_clean[:4]
        yearmonth = date_str_clean[:6]

        pathrow_folder = f"{path}_{row}"
        pathrow_dir = os.path.join(output_dir, pathrow_folder)
        year_dir = os.path.join(pathrow_dir, year)
        month_dir = os.path.join(year_dir, yearmonth)

        for dir_ in [pathrow_dir, year_dir, month_dir]:
            make_dir(dir_)

        temp_dir = os.path.join(
            r"C:\Users\RobMCGREGOR\projects\working\temp_image", stac_item["id"]
        )
        make_dir(temp_dir)
        os.chdir(temp_dir)

        band_files = []

        # Build standardized FC stack name before any downloads
        date_str_clean = date_str.replace("-", "")  # YYYYMMDD
        std_name = f"ga_ls_fc_{pathrow}_{date_str_clean}_fc3ms.tif"
        std_out_path = os.path.join(month_dir, std_name)

        # Also support legacy name (idempotent re-runs)
        legacy_name = f"ga_ls_fc_3-2-1_{pathrow}_{date_str}_final_fc_stack.tif"
        legacy_out_path = os.path.join(month_dir, legacy_name)

        if os.path.exists(std_out_path) or os.path.exists(legacy_out_path):
            already = std_out_path if os.path.exists(std_out_path) else legacy_out_path
            print(
                f"✅ Skipping FC scene {stac_item['id']} — stack already exists at {already}"
            )
            continue

        for band in fc_bands:
            if band in stac_item["assets"]:
                url = stac_item["assets"][band]["href"]
                filename = f"{title}_{band}.tif"
                print(f"Downloading band {band}: {url}")
                download_file(url, filename)
                band_files.append(filename)

        if len(band_files) > 0:
            # Stack bands into a multi-layer raster
            with rasterio.open(band_files[0]) as src0:
                meta = src0.meta
            meta.update(count=len(band_files))

            date_str_clean = date_str.replace("-", "")  # YYYYMMDD
            std_name = f"ga_ls_fc_{pathrow}_{date_str_clean}_fc3ms.tif"
            legacy_name = f"{title}_fc_stack.tif"  # for backward compatibility

            std_out_path = os.path.join(month_dir, std_name)
            legacy_out_path = os.path.join(month_dir, legacy_name)

            # If a standardized or legacy stack already exists, skip writing
            if os.path.exists(std_out_path) or os.path.exists(legacy_out_path):
                already = (
                    std_out_path if os.path.exists(std_out_path) else legacy_out_path
                )
                print(
                    f"✅ Skipping FC scene {stac_item['id']} — stack already exists at {already}"
                )
                os.chdir(r"C:\Users\RobMCGREGOR\projects\working\temp_image")
                shutil.rmtree(temp_dir, ignore_errors=True)
                continue

            # --- Write the 3-band stack (BS, PV, NPV) ---
            with rasterio.open(band_files[0]) as src0:
                meta = src0.meta.copy()
            meta.update(count=len(band_files), compress="lzw")

            # Write to temp with the standardized name
            temp_stack = os.path.join(temp_dir, std_name)
            with rasterio.open(temp_stack, "w", **meta) as dst:
                for band_id, layer_file in enumerate(band_files, start=1):
                    with rasterio.open(layer_file) as src1:
                        dst.write_band(band_id, src1.read(1))
                        print(f"Band {band_id} written from {layer_file}")

            # Delete single-band files
            for f in band_files:
                try:
                    os.remove(f)
                except Exception:
                    pass
            print("Individual FC bands deleted after stacking.")

            # Copy standardized file to month_dir (don’t overwrite if it somehow appeared)
            if not os.path.exists(std_out_path):
                shutil.copy(temp_stack, std_out_path)
                print(f"Copied stacked file to: {std_out_path}")
            else:
                print(f"Target already exists (race or rerun): {std_out_path}")

        else:
            print(f"No fractional cover bands found for scene {title}.")

        # Clean up temp folder if desired
        os.chdir(r"C:\Users\RobMCGREGOR\projects\working\temp_image")
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("🎉 Finished processing FC tiles.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Download DEA Fractional Cover data from STAC."
    )
    parser.add_argument(
        "--path", type=str, default="091", help="Landsat WRS2 path (e.g. '091')"
    )
    parser.add_argument(
        "--row", type=str, default="078", help="Landsat WRS2 row (e.g. '078')"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=r"D:\projects\working\lsat",
        help="Output directory for downloaded files",
    )
    parser.add_argument(
        "--cloud_threshold",
        type=float,
        default=10,
        help="Maximum allowed cloud cover percentage (default = 10)",
    )

    args = parser.parse_args()

    main(
        path=args.path,
        row=args.row,
        output_dir=args.output_dir,
        cloud_threshold=args.cloud_threshold,
    )

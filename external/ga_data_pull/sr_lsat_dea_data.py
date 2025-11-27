#!/usr/bin/env python
# coding: utf-8

import os
import json
import urllib.request
import geopandas as gpd
import numpy as np
from datetime import datetime, timedelta
import s3fs
import rasterio
import re
import time
import random
from pathlib import Path
import shutil
# Create an anonymous S3 filesystem
fs = s3fs.S3FileSystem(anon=True)

# Band lists
l57_bands = ['nbart_blue','nbart_green','nbart_red','nbart_nir','nbart_swir_1','nbart_swir_2']
l89_bands = ['nbart_coastal_aerosol','nbart_blue','nbart_green','nbart_red','nbart_nir','nbart_swir_1','nbart_swir_2']
oa = ['oa_fmask',] #'oa_combined_terrain_shadow']


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
    print(f"  dir : {dest.resolve().parent}")
    print(f"  file: {dest.name}  ({size:,} bytes)")

    # Add random sleep to avoid hammering the server
    sleep_time = random.uniform(1, 5)
    print(f"Sleeping {sleep_time:.2f} seconds to avoid rate limits...")
    time.sleep(sleep_time)


def search_stac(collection, bbox, time_range, limit=1000):
    """Query DEA STAC API for a collection."""
    root_url = "https://explorer.sandbox.dea.ga.gov.au/stac"
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

def make_dir(directory):
    """Create a directory if it doesn't exist."""
    if not os.path.exists(directory):
        os.makedirs(directory)
        print("directory created..", directory)

def main(path, row, output_dir, cloud_threshold, target_date: str | None = None):

    # Read the WRS2 shapefile to get the bounding box
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

    # Priority list
    collections = [
        "ga_ls9c_ard_3",
        "ga_ls8c_ard_3",
        "ga_ls5t_ard_3",
        "ga_ls7e_ard_3"
    ]

    dates_downloaded = set()

    # Normalize optional target_date to YYYY-MM-DD if provided
    target_date_norm = None
    if target_date:
        td = target_date.strip()
        if len(td) == 8 and td.isdigit():
            target_date_norm = f"{td[:4]}-{td[4:6]}-{td[6:]}"
        else:
            target_date_norm = td

    for collection in collections:
        data_sr = search_stac(collection, bbox, time_range)

        if data_sr.get("numberReturned", 0) > 0:
            print(f"Found {data_sr['numberReturned']} scenes in {collection}")

            # Convert features to GeoDataFrame
            gdf = gpd.GeoDataFrame.from_features(data_sr["features"])
            cl = gdf[gdf["eo:cloud_cover"] < cloud_threshold]
            print(f"Total scenes after cloud filter in {collection}: {len(cl)}")

            if len(cl) == 0:
                continue

            indices = cl.index

            for i in indices:
                print(f"Processing scene {i} from collection {collection}")
                stac_item = data_sr["features"][i]
                properties = stac_item["properties"]
                date_str = properties["datetime"].split("T")[0]
                print(f"Processing date: {date_str}")

                # If a specific target date was requested, skip all others
                if target_date_norm and date_str != target_date_norm:
                    continue

                if date_str in dates_downloaded:
                    print(f"Skipping {collection} scene on {date_str} — already downloaded from higher sensor.")
                    # date_str_clean = date_str_.replace("-", "")
                    # date_str_clean = ""
                    continue

                title = properties["title"]
                file_name_parts = title.split("_")

                date_str_ = file_name_parts[4]
                print(f"Processing date string: {date_str_}")
                # date_str_clean = date_str_.replace("-", "")
                # date_str is always in format YYYY-MM-DD
                date_str_clean = date_str.replace("-", "")
                year = date_str_clean[:4]
                yearmonth = date_str_clean[:6]

                year = date_str_clean[:4]
                print(f"Extracted year: {year}")
                yearmonth = date_str_clean[:6]
                print(f"Extracted yearmonth: {yearmonth}")

                pathrow_folder = f"{path}_{row}"

                pathrow_dir = os.path.join(output_dir, pathrow_folder)
                year_dir = os.path.join(pathrow_dir, year)
                month_dir = os.path.join(year_dir, yearmonth)

                for dir_ in [pathrow_dir, year_dir, month_dir]:
                    make_dir(dir_)

                print(f"Processing scene {stac_item['id']} with date {date_str} in {month_dir}")
                print(f"Output directory: {month_dir}")

                # --- decide expected SR name / band list by sensor ---
                # --- decide expected SR name / band list by sensor ---
                sensor = properties["platform"]
                if sensor in ("landsat-5", "landsat-7"):
                    sensor_band_list = l57_bands  # 6 bands
                    count_expected = 6
                elif sensor in ("landsat-8", "landsat-9"):
                    sensor_band_list = l89_bands  # 7 bands
                    count_expected = 7
                else:
                    sensor_band_list = l89_bands  # fallback
                    count_expected = 7

                expected_mask_names = [
                    f"{title}_fmask.tif",
                    # f"{title}_combined-terrain-shadow.tif",
                ]

                # If EITHER srb6 or srb7 already exists, skip SR build entirely
                # sr_exists = any(os.path.exists(os.path.join(month_dir, f"{title}_{tag}.tif"))
                #                 for tag in ("srb6", "srb7"))

                # --- parse pieces for standardized names from DEA title ---
                m = re.match(
                    r'^(?P<prefix>ga_ls\d+c_ard)_3-2-1_(?P<pathrow>\d{6})_(?P<date>\d{4}-\d{2}-\d{2})(?:_(?P<tail>.+))?$',
                    title
                )
                if m:
                    prefix = m.group("prefix")  # e.g. ga_ls9c_ard
                    pathrow = m.group("pathrow")  # e.g. 089080
                    date_c = m.group("date").replace("-", "")  # e.g. 20230125
                else:
                    # fallback if format changes
                    prefix = "ga_lsXc_ard"
                    pathrow = f"{path}{row}"
                    date_c = date_str.replace("-", "")

                base_std = f"{prefix}_{pathrow}_{date_c}"  # standardized (NO _final)
                base_std_fin = f"{base_std}_final"  # legacy variant with _final

                # any plausible SR already present? (legacy + standardized; srb6/7)
                sr_candidates = [
                    os.path.join(month_dir, f"{title}_srb6.tif"),
                    os.path.join(month_dir, f"{title}_srb7.tif"),
                    os.path.join(month_dir, f"{base_std}_srb6.tif"),
                    os.path.join(month_dir, f"{base_std}_srb7.tif"),
                    os.path.join(month_dir, f"{base_std_fin}_srb6.tif"),
                    os.path.join(month_dir, f"{base_std_fin}_srb7.tif"),
                ]
                sr_exists = any(os.path.exists(p) for p in sr_candidates)

                # standardized mask paths (we accept legacy as “exists”, but only write standardized)
                std_fmask_path = os.path.join(month_dir, f"{base_std}_fmask.tif")
                legacy_fmask = os.path.join(month_dir, f"{title}_fmask.tif")
                fmask_exists = os.path.exists(std_fmask_path) or os.path.exists(legacy_fmask)

                print("-" * 50)
                print("Checking outputs in:", month_dir)
                print(f"  SR product : srb6/srb7 -> {'exists' if sr_exists else 'missing'}")
                print(f"  FMASK      : {os.path.basename(std_fmask_path)} -> {'exists' if fmask_exists else 'missing'}")

                if sr_exists:
                    existing = next(p for p in sr_candidates if os.path.exists(p))
                    print(f"Skipping SR build — found existing: {existing}")
                else:
                    # temp workspace
                    temp_dir = os.path.join(r"C:\Users\RobMCGREGOR\projects\working\temp_image", stac_item["id"])
                    make_dir(temp_dir)
                    cwd_before = os.getcwd()
                    try:
                        os.chdir(temp_dir)
                        print("Working directory:", os.getcwd())

                        # Download available SR bands for this scene
                        band_files = []
                        for idx, band in enumerate(sensor_band_list, start=1):
                            if band in stac_item["assets"]:
                                url = stac_item["assets"][band]["href"]
                                out_name = f"{title}_band{idx:02d}.tif"
                                download_file(url, out_name)
                                band_files.append(out_name)

                        if band_files:
                            # Build SR name using ACTUAL band count (6 or 7)
                            sr_count = len(band_files)
                            sr_out_name = f"{base_std}_srb{sr_count}.tif"  # <- NO _final in outputs
                            sr_out_tmp = os.path.join(temp_dir, sr_out_name)

                            with rasterio.open(band_files[0]) as src0:
                                meta = src0.meta.copy()
                            meta.update(count=sr_count, compress="lzw")

                            with rasterio.open(sr_out_tmp, "w", **meta) as dst:
                                for band_id, layer_file in enumerate(sorted(band_files), start=1):
                                    with rasterio.open(layer_file) as src1:
                                        dst.write_band(band_id, src1.read(1))
                            print(f"✓ SR composite built: {sr_out_tmp}")

                            # cleanup singles
                            for f in band_files:
                                try:
                                    os.remove(f)
                                except Exception:
                                    pass

                            final_sr_path = os.path.join(month_dir, os.path.basename(sr_out_tmp))
                            if not os.path.exists(final_sr_path):
                                shutil.copy(sr_out_tmp, final_sr_path)
                                print(f"→ Copied SR to: {final_sr_path}")
                            else:
                                print(f"→ SR already present at destination: {final_sr_path}")
                        else:
                            print("[WARN] No SR bands available in assets for this scene.")
                    finally:
                        os.chdir(cwd_before)

                # ---------------------------------------------------------------------
                # Masks (write standardized names; accept legacy as already present)
                # ---------------------------------------------------------------------
                print("Mask outputs (standardized):")
                print(f"  FMASK : {os.path.basename(std_fmask_path)} -> {'exists' if fmask_exists else 'missing'}")

                if not fmask_exists and "oa_fmask" in stac_item["assets"]:
                    download_file(stac_item["assets"]["oa_fmask"]["href"], std_fmask_path)
                else:
                    print("FMASK present; skip download.")
                #
                # # ---------------------------------------------------------------------
                # # Masks: download each only if missing
                # # ---------------------------------------------------------------------
                # # FMASK
                # m = re.match(
                #     r'^(?P<prefix>ga_ls\d+c_ard)_3-2-1_(?P<pathrow>\d{6})_(?P<date>\d{4}-\d{2}-\d{2})_(?P<tail>.+)$',
                #     title
                # )
                # if m:
                #     prefix = m.group("prefix")  # ga_ls9c_ard
                #     pathrow = m.group("pathrow")  # 089080
                #     date_c = m.group("date").replace("-", "")  # 20220615
                # else:
                #     # Fallback if pattern ever changes
                #     prefix, pathrow, date_c = "ga_lsXc_ard", "000000", date_str.replace("-", "")
                #
                # std_fmask_name = f"{prefix}_{pathrow}_{date_c}_fmask.tif"
                # # std_ctsh_name = f"{prefix}_{pathrow}_{date_c}_combined-terrain-shadow.tif"
                #
                # std_fmask_path = os.path.join(month_dir, std_fmask_name)
                # # std_ctsh_path = os.path.join(month_dir, std_ctsh_name)
                #
                # # We also consider “legacy” names (with -3-2-1 and 'final') as already present
                # legacy_fmask_path = os.path.join(month_dir, f"{title}_fmask.tif")
                # # legacy_ctsh_path = os.path.join(month_dir, f"{title}_combined-terrain-shadow.tif")
                #
                # fmask_exists = os.path.exists(std_fmask_path) or os.path.exists(legacy_fmask_path)
                # # ctsh_exists = os.path.exists(std_ctsh_path) or os.path.exists(legacy_ctsh_path)
                #
                # print("Mask outputs (standardized):")
                # print(f"  FMASK : {std_fmask_name} -> {'exists' if fmask_exists else 'missing'}")
                # # print(f"  CTSH  : {std_ctsh_name}  -> {'exists' if ctsh_exists else 'missing'}")
                #
                # # ---------------------------------------------------------------------
                # # Masks: download each only if missing (write to standardized names)
                # # ---------------------------------------------------------------------
                # # FMASK
                # print("Mask outputs:")
                # print(f"  FMASK : {os.path.basename(std_fmask_path)} -> {'exists' if fmask_exists else 'missing'}")
                #
                # if not fmask_exists and "oa_fmask" in stac_item["assets"]:
                #     download_file(stac_item["assets"]["oa_fmask"]["href"], std_fmask_path)
                # else:
                #     print("FMASK present; skip download.")

                # # Combined terrain shadow
                # if not ctsh_exists and "oa_combined_terrain_shadow" in stac_item["assets"]:
                #     download_file(stac_item["assets"]["oa_combined_terrain_shadow"]["href"], std_ctsh_path)
                # else:
                #     print("Combined terrain shadow present; skip download.")


    if not dates_downloaded:
        print("No data found in any Landsat collection for this tile.")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Download Landsat surface reflectance data from DEA STAC API."
    )
    parser.add_argument(
        "--path",
        type=str,
        default="091",
        help="Landsat WRS2 path (e.g. '090')"
    )
    parser.add_argument(
        "--row",
        type=str,
        default="078",
        help="Landsat WRS2 row (e.g. '084')"
    )

    parser.add_argument(
        "--output_dir",
        type=str,
        default=r"D:\projects\working\lsat",
        help="Output directory for downloaded files"
    )
    parser.add_argument(
        "--cloud_threshold",
        type=float,
        default=10,
        help="Maximum allowed cloud cover percentage (default = 10)"
    )
    parser.add_argument(
        "--target_date",
        type=str,
        default=None,
        help="Optional single date to download only (YYYY-MM-DD or YYYYMMDD)"
    )

    args = parser.parse_args()

    main(
        path=args.path,
        row=args.row,
        output_dir=args.output_dir,
        cloud_threshold=args.cloud_threshold,
        target_date=args.target_date,
    )

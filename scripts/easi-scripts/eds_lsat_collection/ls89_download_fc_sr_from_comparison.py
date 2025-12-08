#!/usr/bin/env python
"""
ls89_download_fc_sr_from_comparison.py

Download & composite LS8/9 NBART SR + FC + FMASK for a single tile, driven by a
comparison_table.csv produced by ls89_fc_sr_query.py, running on EASI.

High-level flow (per unique date in the comparison table for this tile):

1. Query Datacube for SR (ga_ls8c_ard_3 / ga_ls9c_ard_3) + FMASK (oa_fmask),
   and FC (ga_ls_fc_3), over a lat/lon bounding box.

2. For each:
   - SR: time-mean composite for that day (unmasked + masked by FMASK).
   - FC: time-mean composite (unmasked + masked by FMASK).
   - FMASK: compressed to a single 2D "ffmask" for the day.

3. Write 5 GeoTIFFs to local scratch:
     ~/scratch/eds/tiles/pPPP_rRRR/sr/YYYY/YYYYMM/...
     ~/scratch/eds/tiles/pPPP_rRRR/fc/YYYY/YYYYMM/...
     ~/scratch/eds/tiles/pPPP_rRRR/ffmask/YYYY/YYYYMM/...

4. Upload those 5 files to user scratch S3:
     s3://dcceew-prod-user-scratch/<UserId>/eds/tiles/...

NOTE ON CRS:
------------
We DO NOT pass output_crs / resolution to dc.load at all.

Therefore:
- Datacube returns data in the native product CRS & resolution.
- For DEA LS8/9 ARD v3 and ga_ls_fc_3, that is EPSG:3577 (DEA Albers).
- We do not reproject in write_geotiff: we simply write what we were given.

So this script does NOT change CRS. All reprojection would have to happen
upstream in Datacube (by specifying output_crs) or downstream in another step.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Tuple

import pandas as pd
import numpy as np
import boto3
import datacube
import xarray as xr
import math

# rioxarray is used for GeoTIFF writing
import rioxarray  # noqa: F401  # needed for .rio accessor

# Configure S3 access for unsigned + requester-pays (EASI DEA buckets)
from datacube.utils.aws import configure_s3_access

print("[DEBUG] ls89_download_fc_sr_from_comparison.py imported")

# ---------------------------------------------------------------------
# Constants / configuration
# ---------------------------------------------------------------------
HOME = Path.home()

# Local scratch root:
#   ~/scratch/eds/tiles/pPPP_rRRR/...
LOCAL_SCRATCH_ROOT = HOME / "scratch" / "eds" / "tiles"

# S3 scratch bucket (user-scoped)
S3_BUCKET = "dcceew-prod-user-scratch"

# SR band names in DEA LS8/9 ARD (NBART)
SR_BANDS = [
    "nbart_blue",
    "nbart_green",
    "nbart_red",
    "nbart_nir",
    "nbart_swir_1",
    "nbart_swir_2",
]

# Pixel-quality / FMASK band name in LS8/9 ARD v3
FMASK_BAND = "oa_fmask"

# FC bands in ga_ls_fc_3
FC_BANDS = ["bs", "pv", "npv", "ue"]

# FMASK value(s) considered "clear"
FMASK_CLEAR_VALUES = {1}

print("[DEBUG] Constants defined; LOCAL_SCRATCH_ROOT =", LOCAL_SCRATCH_ROOT)


# ---------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------

def tile_id_from_pathrow(path: int, row: int) -> str:
    return f"p{int(path):03d}r{int(row):03d}"


def year_month_from_date(d: pd.Timestamp) -> Tuple[str, str]:
    """Return (YYYY, YYYYMM) strings from a Timestamp or datetime.date."""
    y = f"{d.year:04d}"
    ym = f"{d.year:04d}{d.month:02d}"
    return y, ym


def ensure_dir(p: Path) -> None:
    """Create directory (and parents) if it does not exist."""
    p.mkdir(parents=True, exist_ok=True)


def get_user_prefix_from_sts() -> str:
    """
    Use STS to get the same UserId we used already for s3:// paths, e.g.:

        "UserId": "AROA...:robotmcgregor"

    Returns that full string.
    """
    sts = boto3.client("sts")
    ident = sts.get_caller_identity()
    user_id = ident.get("UserId")
    if not user_id:
        raise RuntimeError("Could not get UserId from sts.get_caller_identity()")
    print(f"[DEBUG] STS UserId: {user_id}")
    return user_id


def s3_key_for_tile(
    user_prefix: str,
    tile_id: str,
    yyyy: str,
    yyyymm: str,
    filename: str,
    subdir: str,
) -> str:
    """
    Build an S3 key for a given tile + date + filename in our layout.

    subdir is one of: 'sr', 'fc', 'ffmask'.
    """
    return (
        f"{user_prefix}/eds/tiles/{tile_id}/"
        f"{subdir}/{yyyy}/{yyyymm}/{filename}"
    )


def s3_object_exists(client, bucket: str, key: str) -> bool:
    """
    Check if an object exists in S3 via HEAD.
    """
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except client.exceptions.ClientError as e:
        code = e.response["Error"].get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        # Anything else is unexpected; let caller see it
        raise


# ---------------------------------------------------------------------
# Datacube loaders (SR + FMASK, FC)
# ---------------------------------------------------------------------

def _describe_ds_crs_and_dims(ds: xr.Dataset, label: str) -> None:
    """
    Utility to print CRS and basic dimensions for a dataset.
    """
    # Try Datacube geobox first
    try:
        geobox = ds.geobox
        crs_str = str(geobox.crs)
        res_y, res_x = geobox.resolution
        print(f"[DEBUG] {label}: geobox CRS={crs_str}, "
              f"res=({res_y}, {res_x}), shape={geobox.shape}")
    except Exception:
        # Fallback to attrs
        crs_str = ds.attrs.get("crs", "unknown")
        print(f"[DEBUG] {label}: no geobox; ds.attrs['crs']={crs_str}")
        print(f"[DEBUG] {label}: dims={ds.dims}")

    # Also show what rioxarray thinks (if any)
    try:
        print(f"[DEBUG] {label}: rioxarray CRS={ds.rio.crs}")
    except Exception:
        print(f"[DEBUG] {label}: rioxarray CRS not set yet")


def load_sr_and_fmask_for_day(
    dc: datacube.Datacube,
    product: str,
    lat_range: Tuple[float, float],
    lon_range: Tuple[float, float],
    date_str: str,
    target_utm_epsg,
    crs_suffix
) -> xr.Dataset | None:
    """
    Load all SR bands + FMASK for a single day for one ARD product.
    Returns an xarray.Dataset with time dimension (may be >1), or None if load fails.

    NOTE: We do NOT pass output_crs / resolution here.
          Datacube will return data in the product's native CRS and resolution.
          For DEA LS8/9 ARD v3, that is EPSG:3577 (DEA Albers).
    """
    t0 = pd.to_datetime(date_str)
    t1 = t0 + pd.Timedelta(days=1)

    print(f"[DEBUG] Loading SR+FMASK for {product}, date={date_str}, "
          f"lat_range={lat_range}, lon_range={lon_range}")
    print("[DEBUG] dc.load called WITHOUT output_crs/resolution → native CRS, no reprojection.")

    try:
        ds = dc.load(
            product=product,
            measurements=SR_BANDS + [FMASK_BAND],
            latitude=lat_range,
            longitude=lon_range,
            time=(t0, t1),
            group_by="solar_day",
            output_crs=target_utm_epsg,  # auto-picked UTM zone
            resolution=(-30, 30),        # e.g. 30 m UTM
            skip_broken_datasets=True,
        )

        print(f"[DEBUG] Loaded SR+FMASK dataset for {product}, date={date_str}")
        _describe_ds_crs_and_dims(ds, label=f"SR+FMASK ({product})")

    except Exception as e:
        print(f"[DL] ERROR loading SR for product={product}, date={date_str}: {e}")
        return None

    return ds


def load_fc_for_day(
    dc: datacube.Datacube,
    lat_range: Tuple[float, float],
    lon_range: Tuple[float, float],
    date_str: str,
    target_utm_epsg,
    crs_suffix
) -> xr.Dataset | None:
    """
    Load ga_ls_fc_3 for a single day, all FC_BANDS.
    Returns an xarray.Dataset, or None if load fails.

    NOTE: As with SR, we do NOT specify output_crs, so data come out
          in the native CRS of ga_ls_fc_3 (EPSG:3577).
    """
    t0 = pd.to_datetime(date_str)
    t1 = t0 + pd.Timedelta(days=1)

    print(f"[DEBUG] Loading FC for date={date_str}, lat_range={lat_range}, lon_range={lon_range}")
    print("[DEBUG] dc.load called WITHOUT output_crs/resolution → native CRS, no reprojection.")

    try:
        ds = dc.load(
            product="ga_ls_fc_3",
            measurements=FC_BANDS,
            latitude=lat_range,
            longitude=lon_range,
            time=(t0, t1),
            group_by="solar_day",
            output_crs=target_utm_epsg,  # auto-picked UTM zone
            resolution=(-30, 30),        # e.g. 30 m UTM
            skip_broken_datasets=True,
        )

        print(f"[DEBUG] Loaded FC dataset for date={date_str}")
        _describe_ds_crs_and_dims(ds, label="FC (ga_ls_fc_3)")

    except Exception as e:
        print(f"[DL] ERROR loading FC for date={date_str}: {e}")
        return None

    return ds


# ---------------------------------------------------------------------
# Compositing helpers
# ---------------------------------------------------------------------

def composite_time_mean(ds: xr.Dataset, band_names: Iterable[str]) -> xr.Dataset:
    """
    Simple time-mean composite across the "time" dimension, keeping only the
    selected band_names. Result has no time dimension.

    If there is no 'time' dimension (only one time slice), we just drop it.
    """
    print(f"[DEBUG] composite_time_mean on bands={list(band_names)}; ds.dims={ds.dims}")
    subset = ds[band_names]
    if "time" in subset.dims:
        out = subset.mean("time", keep_attrs=True)
        print("[DEBUG] composite_time_mean: time dimension found → mean over time.")
        return out
    print("[DEBUG] composite_time_mean: no time dimension → returning subset unchanged.")
    return subset


def composite_fmask(fmask: xr.DataArray, clear_values: set[int]) -> xr.DataArray:
    """
    Build a 2D ffmask from oa_fmask for a single day's stack.
    """
    print(f"[DEBUG] composite_fmask: fmask.dims={fmask.dims}")

    if "time" not in fmask.dims:
        # 2D case: simple clear mask
        print("[DEBUG] composite_fmask: 2D case (no time dim).")
        clear = xr.zeros_like(fmask, dtype=bool)
        for v in clear_values:
            clear = clear | (fmask == v)
    else:
        # 3D: fmask(time, y, x) -> clear(y, x) if ANY time is clear
        print("[DEBUG] composite_fmask: 3D case (time,y,x).")
        clear = xr.zeros_like(fmask.isel(time=0, drop=True), dtype=bool)
        for v in clear_values:
            clear = clear | (fmask == v).any("time")

    ffmask = xr.where(clear, 1, 0).astype("uint8")
    ffmask.name = "ffmask"
    print("[ACTION] composite fmask created (ffmask)")
    return ffmask


def apply_fmask(ds: xr.Dataset, fmask: xr.DataArray, clear_values: set[int]) -> xr.Dataset:
    """
    Mask dataset ds where fmask is not in clear_values. Keeps ds's bands.
    """
    print(f"[DEBUG] apply_fmask: ds.dims={ds.dims}, fmask.dims={fmask.dims}")
    mask = xr.zeros_like(fmask, dtype=bool)
    for v in clear_values:
        mask = mask | (fmask == v)
    out = ds.where(mask)
    print("[ACTION] fmask applied to dataset.")
    return out


# ---------------------------------------------------------------------
# Define to UTM
#----------------------------------------------------------------------



def utm_epsg_from_bounds(lat_min: float, lat_max: float,
                         lon_min: float, lon_max: float) -> str:
    """
    Given lat/lon bounds, pick a sensible WGS84 UTM zone EPSG code.

    - Uses the longitude of the AOI centre to choose the zone.
    - Uses latitude sign to choose north/south hemisphere.

    Returns: e.g. "EPSG:32752" for UTM zone 52S.
    """
    # Centre of the AOI
    lat_c = 0.5 * (lat_min + lat_max)
    lon_c = 0.5 * (lon_min + lon_max)

    # UTM zone number (1–60)
    zone = int(math.floor((lon_c + 180.0) / 6.0)) + 1

    # Hemisphere: north = 326xx, south = 327xx
    if lat_c >= 0:
        epsg = f"EPSG:326{zone:02d}"
        hemi = "N"
    else:
        epsg = f"EPSG:327{zone:02d}"
        hemi = "S"

    print(f"[UTM] AOI centre lat={lat_c:.4f}, lon={lon_c:.4f} -> "
          f"zone {zone}{hemi} ({epsg})")

    return epsg

def crs_suffix_from_epsg(crs: str) -> str:
    """
    Normalise a CRS string to a numeric EPSG suffix for filenames.

    Examples:
        "EPSG:32752" -> "32752"
        "32752"      -> "32752"
        32752        -> "32752"
    """
    crs_str = str(crs)
    if ":" in crs_str:
        crs_str = crs_str.split(":")[-1]
    return crs_str


# ---------------------------------------------------------------------
# GeoTIFF writer
# ---------------------------------------------------------------------

def write_geotiff(
    da_or_ds: xr.DataArray | xr.Dataset,
    out_path: Path,
    dtype="float32",
    nodata=None,
) -> None:
    """
    Write a DataArray/Dataset to GeoTIFF using rioxarray.

    If Dataset, we stack bands in declaration order as a "band" dimension.

    NOTE:
    - This function does NOT change CRS.
    - If `nodata` is not None, we set the GeoTIFF nodata value so
      ArcGIS/QGIS will treat that code as transparent.
    """
    print(f"[DEBUG] write_geotiff: type={type(da_or_ds)}, out_path={out_path}, nodata={nodata}")

    if isinstance(da_or_ds, xr.Dataset):
        ds2 = da_or_ds

        # Defensive: drop any singleton time dim if present
        if "time" in ds2.dims and ds2.sizes.get("time", 0) == 1:
            ds2 = ds2.isel(time=0, drop=True)

        bands = list(ds2.data_vars)
        print(f"[DEBUG] write_geotiff: dataset with bands={bands}")

        stacked = ds2[bands].to_array("band")
        stacked = stacked.astype(dtype)
        stacked["band"] = np.arange(1, len(bands) + 1)
        stacked.attrs["band_names"] = ",".join(bands)

        # Tell rioxarray the CRS if we have it
        if "crs" in stacked.attrs and stacked.rio.crs is None:
            stacked = stacked.rio.write_crs(stacked.attrs["crs"], inplace=False)

        # Set nodata metadata if requested
        if nodata is not None:
            print(f"[DEBUG] write_geotiff: setting nodata={nodata}")
            stacked = stacked.rio.write_nodata(nodata, encoded=True, inplace=False)

        print(f"[DEBUG] write_geotiff: rioxarray CRS before write: {stacked.rio.crs}")
        stacked.rio.to_raster(out_path)

    else:
        # DataArray case
        arr = da_or_ds
        print(f"[DEBUG] write_geotiff: DataArray dims={arr.dims}")
        if "time" in arr.dims and arr.sizes.get("time", 0) == 1:
            arr = arr.isel(time=0, drop=True)
        arr = arr.astype(dtype)

        if "crs" in arr.attrs and arr.rio.crs is None:
            arr = arr.rio.write_crs(arr.attrs["crs"], inplace=False)

        if nodata is not None:
            print(f"[DEBUG] write_geotiff: setting nodata={nodata}")
            arr = arr.rio.write_nodata(nodata, encoded=True, inplace=False)

        print(f"[DEBUG] write_geotiff: rioxarray CRS before write: {arr.rio.crs}")
        arr.rio.to_raster(out_path)

    print(f"[ACTION] Wrote GeoTIFF to: {out_path}")



# ---------------------------------------------------------------------
# Main download/composite logic
# ---------------------------------------------------------------------

def process_tile_from_comparison(
    comparison_csv: Path,
    tile_id: str,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    start_date: str | None = None,
    end_date: str | None = None,
    dry_run: bool = False,
) -> None:
    """
    For one tile, read comparison_table.csv, subset to that tile (and optional
    date window), then loop over dates and build SR+FC composites (with FMASK)
    and upload to S3.
    """
    print(f"[DL] Reading comparison table: {comparison_csv}")
    df = pd.read_csv(comparison_csv, parse_dates=["date"])

    # Derive path,row from tile_id like "p104r070"
    tid = tile_id.lower()
    if not (tid.startswith("p") and "r" in tid):
        raise ValueError(f"Unrecognised tile_id format: {tile_id}")
    p_str, r_str = tid[1:].split("r")
    tile_path = int(p_str)
    tile_row = int(r_str)
    print(f"[DEBUG] Parsed tile_id={tile_id} → path={tile_path}, row={tile_row}")

    # Filter to tile
    df_tile = df[(df["path"] == tile_path) & (df["row"] == tile_row)].copy()
    if df_tile.empty:
        print(f"[DL] No rows in comparison for tile {tile_id} – nothing to do.")
        return

    # Optional date window
    if start_date:
        start_ts = pd.to_datetime(start_date)
        df_tile = df_tile[df_tile["date"] >= start_ts]
    if end_date:
        end_ts = pd.to_datetime(end_date)
        df_tile = df_tile[df_tile["date"] <= end_ts]

    if df_tile.empty:
        print(f"[DL] No rows after applying date window – nothing to do.")
        return

    dates = sorted(df_tile["date"].dt.normalize().unique())
    print(f"[DL] Tile {tile_id}: {len(df_tile)} rows, {len(dates)} unique dates.")

    # Prepare S3 client and prefix
    s3_client = boto3.client("s3")
    user_prefix = get_user_prefix_from_sts()
    print(f"[DL] Using S3 user prefix: {user_prefix}")

    # Configure Datacube S3 access for EASI/DEA (unsigned + requester-pays)
    configure_s3_access(aws_unsigned=True, requester_pays=True)

    # Datacube and lat/lon ranges (ensure min/max ordering)
    dc = datacube.Datacube(app="ls89_download_fc_sr_from_comparison")
    lat_range = (min(lat_min, lat_max), max(lat_min, lat_max))
    lon_range = (min(lon_min, lon_max), max(lon_min, lon_max))
    print(f"[DEBUG] lat_range={lat_range}, lon_range={lon_range}")

    # Identify the UTM
    target_utm_epsg = utm_epsg_from_bounds(*lat_range, *lon_range)
    output_crs = target_utm_epsg
    print(f"[DL] Target UTM CRS for this AOI: {target_utm_epsg}")

    crs_suffix = crs_suffix_from_epsg(output_crs)  # "32752"
    print(f"[DL] Target UTM CRS for this AOI: {output_crs} (suffix={crs_suffix})")


    for d in dates:
        date_str = pd.to_datetime(d).strftime("%Y-%m-%d")
        date_tag = pd.to_datetime(d).strftime("%Y%m%d")
        yyyy, yyyymm = year_month_from_date(pd.to_datetime(d))

        print(f"\n[DL] === {tile_id} – {date_str} ===")

        # -----------------------------------------------------------------
        # Build local output dirs & filenames
        # -----------------------------------------------------------------
        tile_root = LOCAL_SCRATCH_ROOT / tile_id
        sr_dir = tile_root / "sr" / yyyy / yyyymm
        fc_dir = tile_root / "fc" / yyyy / yyyymm
        mask_dir = tile_root / "ffmask" / yyyy / yyyymm

        ensure_dir(sr_dir)
        ensure_dir(fc_dir)
        ensure_dir(mask_dir)

        # sr_nb_filename      = f"ls89sr_{tile_id}_{date_tag}_nbart6m.tif"
        # sr_nb_clr_filename  = f"ls89sr_{tile_id}_{date_tag}_nbart6m_clr.tif"
        # fc_nb_filename      = f"galsfc3_{tile_id}_{date_tag}_fcm.tif"
        # fc_nb_clr_filename  = f"galsfc3_{tile_id}_{date_tag}_fcm_clr.tif"
        # ffmask_filename     = f"ls89_{tile_id}_{date_tag}_ffmask.tif"

        # Use the numeric CRS suffix (e.g. 32752) in filenames
        crs_suffix = crs_suffix_from_epsg(output_crs)

        sr_nb_filename      = f"ls89sr_{tile_id}_{date_tag}_nbart6m{crs_suffix[-1]}.tif"
        sr_nb_clr_filename  = f"ls89sr_{tile_id}_{date_tag}_nbart6m{crs_suffix[-1]}_clr.tif"
        fc_nb_filename      = f"galsfc3_{tile_id}_{date_tag}_fcm{crs_suffix[-1]}.tif"
        fc_nb_clr_filename  = f"galsfc3_{tile_id}_{date_tag}_fcm{crs_suffix[-1]}_clr.tif"
        ffmask_filename     = f"ls89_{tile_id}_{date_tag}_ffmask{crs_suffix[-1]}.tif"


        sr_nb_out      = sr_dir / sr_nb_filename
        sr_nb_clr_out  = sr_dir / sr_nb_clr_filename
        fc_nb_out      = fc_dir / fc_nb_filename
        fc_nb_clr_out  = fc_dir / fc_nb_clr_filename
        ffmask_out     = mask_dir / ffmask_filename

        print(f"[DEBUG] Output paths:")
        print(f"        SR nbart:      {sr_nb_out}")
        print(f"        SR nbart_clr:  {sr_nb_clr_out}")
        print(f"        FC fcm:        {fc_nb_out}")
        print(f"        FC fcm_clr:    {fc_nb_clr_out}")
        print(f"        ffmask:        {ffmask_out}")

        # Check local existence of ALL 5 files
        local_files = [sr_nb_out, sr_nb_clr_out, fc_nb_out, fc_nb_clr_out, ffmask_out]
        if all(p.exists() for p in local_files):
            print(f"[DL] All SR/FC/ffmask outputs already exist locally for {date_str}, skipping.")
            continue

        # Build S3 keys for ALL 5 files
        sr_nb_key     = s3_key_for_tile(user_prefix, tile_id, yyyy, yyyymm, sr_nb_filename,     "sr")
        sr_nb_clr_key = s3_key_for_tile(user_prefix, tile_id, yyyy, yyyymm, sr_nb_clr_filename, "sr")
        fc_nb_key     = s3_key_for_tile(user_prefix, tile_id, yyyy, yyyymm, fc_nb_filename,     "fc")
        fc_nb_clr_key = s3_key_for_tile(user_prefix, tile_id, yyyy, yyyymm, fc_nb_clr_filename, "fc")
        ffmask_key    = s3_key_for_tile(user_prefix, tile_id, yyyy, yyyymm, ffmask_filename,    "ffmask")

        s3_keys = [sr_nb_key, sr_nb_clr_key, fc_nb_key, fc_nb_clr_key, ffmask_key]
        s3_exists = [s3_object_exists(s3_client, S3_BUCKET, k) for k in s3_keys]

        if all(s3_exists):
            print(f"[DL] All SR/FC/ffmask outputs already exist in S3 for {date_str}, skipping.")
            continue

        # -----------------------------------------------------------------
        # Load SR + FMASK for this date (from whichever LS8/9 products exist)
        # -----------------------------------------------------------------
        day_rows = df_tile[df_tile["date"].dt.normalize() == d]
        sr_products_today = sorted(day_rows["sr_product"].unique())
        print(f"[DL] SR products this day: {sr_products_today}")

        sr_datasets = []
        for prod in sr_products_today:
            ds_sr = load_sr_and_fmask_for_day(dc, prod, lat_range, lon_range, date_str, target_utm_epsg, crs_suffix)
            if ds_sr is not None and ds_sr.sizes.get("time", 0) > 0:
                sr_datasets.append(ds_sr)

        if not sr_datasets:
            print(f"[DL] No SR data loaded for {date_str}, skipping.")
            continue

        # Sanity check: all SR datasets should share same CRS
        try:
            crs_list = [str(ds.geobox.crs) for ds in sr_datasets]
            if len(set(crs_list)) > 1:
                print(f"[WARNING] Multiple SR CRS for {date_str}: {crs_list}")
            else:
                print(f"[DEBUG] SR CRS for {date_str}: {crs_list[0]}")
        except Exception:
            print("[DEBUG] Could not introspect CRS list for SR datasets.")

        # Merge along time (concatenate LS8 + LS9 etc.)
        sr_all = xr.concat(sr_datasets, dim="time")
        print(f"[DEBUG] sr_all dims after concat: {sr_all.dims}")

        if FMASK_BAND not in sr_all.data_vars:
            print(f"[DL] Warning: {FMASK_BAND} not present for {date_str}, skipping.")
            continue

        fmask = sr_all[FMASK_BAND]

        # ---------------- SR composites (nbart & nbart_clr) ----------------
        sr_composite = composite_time_mean(sr_all, SR_BANDS)

        sr_masked = apply_fmask(sr_all[SR_BANDS], fmask, FMASK_CLEAR_VALUES)
        sr_composite_clr = composite_time_mean(sr_masked, SR_BANDS)

        # ffmask for this day (2D)
        ffmask = composite_fmask(fmask, FMASK_CLEAR_VALUES)

        # -----------------------------------------------------------------
        # Load FC for this date and apply the same FMASK
        # -----------------------------------------------------------------
        ds_fc = load_fc_for_day(dc, lat_range, lon_range, date_str, target_utm_epsg, crs_suffix)
        if ds_fc is None or ds_fc.sizes.get("time", 0) == 0:
            print(f"[DL] No FC data loaded for {date_str}, skipping FC.")
            fc_composite = None
            fc_composite_clr = None
        else:
            # Unmasked FC composite
            fc_composite = composite_time_mean(ds_fc, FC_BANDS)

            # Masked FC composite (clr)
            fc_masked = apply_fmask(ds_fc[FC_BANDS], fmask, FMASK_CLEAR_VALUES)
            fc_composite_clr = composite_time_mean(fc_masked, FC_BANDS)

        # -----------------------------------------------------------------
        # Dry-run mode: just report what we'd do
        # -----------------------------------------------------------------
        if dry_run:
            print("[DL] Dry run – would write:")
            print(f"  SR nbart      -> {sr_nb_out}")
            print(f"  SR nbart_clr  -> {sr_nb_clr_out}")
            print(f"  FC fcm        -> {fc_nb_out}")
            print(f"  FC fcm_clr    -> {fc_nb_clr_out}")
            print(f"  ffmask        -> {ffmask_out}")
            print("[DL] and upload to S3 keys:")
            print(f"  {sr_nb_key}")
            print(f"  {sr_nb_clr_key}")
            print(f"  {fc_nb_key}")
            print(f"  {fc_nb_clr_key}")
            print(f"  {ffmask_key}")
            continue

        # -----------------------------------------------------------------
        # Write local GeoTIFFs (still in native CRS; no reprojection)
        # -----------------------------------------------------------------
        print(f"[DL] Writing SR (unmasked) composite to {sr_nb_out}")
        # SR: float32 with nodata = -999
        write_geotiff(sr_composite, sr_nb_out, dtype="float32", nodata=-999.0)

        print(f"[DL] Writing SR (masked) composite to {sr_nb_clr_out}")
        write_geotiff(sr_composite_clr, sr_nb_clr_out, dtype="float32", nodata=-999.0)

        if fc_composite is not None:
            print(f"[DL] Writing FC (unmasked) composite to {fc_nb_out}")
            # FC: nodata code 255 (consistent with raw product)
            write_geotiff(fc_composite, fc_nb_out, dtype="float32", nodata=255.0)
        else:
            print("[DL] Skipping FC unmasked write (no FC data).")

        if fc_composite_clr is not None:
            print(f"[DL] Writing FC (masked) composite to {fc_nb_clr_out}")
            write_geotiff(fc_composite_clr, fc_nb_clr_out, dtype="float32", nodata=255.0)
        else:
            print("[DL] Skipping FC masked write (no FC data).")

        print(f"[DL] Writing ffmask to {ffmask_out}")
        # Usually ffmask 0/1 is fine; no nodata needed, but you can add one if you like.
        write_geotiff(ffmask, ffmask_out, dtype="uint8", nodata=None)


        # -----------------------------------------------------------------
        # Upload to S3
        # -----------------------------------------------------------------
        uploads = [
            (sr_nb_out,     sr_nb_key),
            (sr_nb_clr_out, sr_nb_clr_key),
        ]

        if fc_composite is not None and fc_nb_out.exists():
            uploads.append((fc_nb_out, fc_nb_key))
        if fc_composite_clr is not None and fc_nb_clr_out.exists():
            uploads.append((fc_nb_clr_out, fc_nb_clr_key))
        if ffmask_out.exists():
            uploads.append((ffmask_out, ffmask_key))

        for local_path, key in uploads:
            print(f"[DL] Uploading {local_path.name} to s3://{S3_BUCKET}/{key}")
            s3_client.upload_file(str(local_path), S3_BUCKET, key)

    print("\n[DL] Done for tile", tile_id)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download & composite LS8/9 NBART SR + FC + FMASK for a single tile from a comparison CSV."
    )

    parser.add_argument(
        "--comparison-csv",
        required=True,
        type=Path,
        help="Path to comparison_table CSV produced by ls89_fc_sr_query.py",
    )
    parser.add_argument(
        "--tile-id",
        required=True,
        type=str,
        help="Tile ID in the form pPPPrrr (e.g. p104r070)",
    )
    parser.add_argument(
        "--lat-min",
        required=True,
        type=float,
        help="Minimum latitude of AOI",
    )
    parser.add_argument(
        "--lat-max",
        required=True,
        type=float,
        help="Maximum latitude of AOI",
    )
    parser.add_argument(
        "--lon-min",
        required=True,
        type=float,
        help="Minimum longitude of AOI",
    )
    parser.add_argument(
        "--lon-max",
        required=True,
        type=float,
        help="Maximum longitude of AOI",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Optional start date (YYYY-MM-DD) to filter comparison table",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Optional end date (YYYY-MM-DD) to filter comparison table",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="If set, do not write or upload anything – just print what would be done.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    process_tile_from_comparison(
        comparison_csv=args.comparison_csv,
        tile_id=args.tile_id,
        lat_min=args.lat_min,
        lat_max=args.lat_max,
        lon_min=args.lon_min,
        lon_max=args.lon_max,
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

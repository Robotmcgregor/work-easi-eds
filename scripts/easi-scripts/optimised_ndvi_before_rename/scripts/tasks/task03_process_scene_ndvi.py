#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import numpy as np
import re
from lib.cog import write_cog_uint8, write_cog_float32
from lib.s3_io import upload_file_to_s3
import datacube
import numpy as np
import re
import datacube
import numpy as np

# def process_scene_to_s3(
#     tile: str,
#     date: str,              # YYYYMMDD
#     platform: str,
#     product: str,
#     lon_min: float,
#     lat_min: float,
#     lon_max: float,
#     lat_max: float,
#     target_epsg: int,
#     cloud_max: float,
#     bucket: str,
#     ndvi_key: str,
#     ffmask_key: str,
#     work_dir: Path,
#     resolution: float,
#     rebase: bool,
#     dask_chunk: int = 2048,
# ) -> None:
#     """
#     Loads nbart_red, nbart_nir, oa_fmask from datacube for one scene date.

#     - Queries by TILE BBOX (WGS84)
#     - Reprojects to GDA94 MGA (EPSG:283xx)
#     - Chooses the BEST slice (if multiple datasets returned for the same day) based on max CLEAR%
#     - Masks using oa_fmask "clear" class for this product (ga_ls8c_ard_3: clear=0 in your test)
#     - Writes NDVI + FFMASK as Cloud Optimised GeoTIFFs (COGs)
#     - Uploads outputs to S3 using the provided keys
#     """


#     tile = tile.lower()
#     work_dir.mkdir(parents=True, exist_ok=True)

#     dc = datacube.Datacube(app="optimised_ndvi_process")

#     # datacube time query wants ISO-ish strings
#     t0 = f"{date[:4]}-{date[4:6]}-{date[6:]}"
#     time = (t0, t0)

#     # chunking keeps RAM down and lets cheap nodes run
#     dask_chunks = {"x": int(dask_chunk), "y": int(dask_chunk)}

#     print(f"[INFO] Loading {tile} {platform} {date} product={product} EPSG:{target_epsg}")
#     print(f"[DEBUG] lon=({lon_min}, {lon_max}) lat=({lat_min}, {lat_max}) time={time}")

    

#     m = re.fullmatch(r"p(\d{3})r(\d{3})", tile.lower())
#     path = int(m.group(1))
#     row  = int(m.group(2))
#     region_code = f"{path:03d}{row:03d}"   # "115078"

#     def only_this_tile(ds) -> bool:
#         # region_code is commonly present on DEA ARD datasets
#         rc = getattr(getattr(ds, "metadata", None), "region_code", None)
#         if rc is None:
#             # fallback: parse from the dataset URI/path if needed
#             try:
#                 uri = ds.uri if hasattr(ds, "uri") else (ds.uris[0] if hasattr(ds, "uris") else "")
#                 return f"/{path:03d}/{row:03d}/" in str(uri)
#             except Exception:
#                 return False
#         return str(rc) == region_code


#     ds = dc.load(
#         product=product,
#         measurements=["nbart_red", "nbart_nir", "oa_fmask"],
#         time=time,
#         lon=(float(lon_min), float(lon_max)),
#         lat=(float(lat_min), float(lat_max)),
#         output_crs=f"EPSG:{int(target_epsg)}",
#         resolution=(-float(resolution), float(resolution)),
#         dask_chunks=dask_chunks,
#         dataset_predicate=only_this_tile,
#         skip_broken_datasets=True,
#     )

#     if ds is None or "time" not in ds.dims or ds.sizes.get("time", 0) == 0:
#         raise RuntimeError(
#             f"No data returned by datacube load for tile={tile} product={product} date={date}"
#         )

#     # ------------------------------------------------------------------
#     # CLEAR definition:
#     # Your oa_fmask histogram shows:
#     #   0 dominates and looks like "valid/clear background",
#     #   1 is small, 2..5 other classes.
#     # So for this product in your env: treat CLEAR as 0.
#     # ------------------------------------------------------------------
#     CLEAR_VALUES = (0,)

#     # ------------------------------------------------------------------
#     # If datacube returns multiple time slices for the same day,
#     # pick the slice with the highest clear% so we don't accidentally
#     # process a worse (e.g., mostly cloud) dataset.
#     # IMPORTANT: we must use the SAME chosen slice for red/nir/oa.
#     # ------------------------------------------------------------------
#     clear_pct_by_time = ds["oa_fmask"].isin(CLEAR_VALUES).mean(dim=("y", "x")).compute()
#     best_i = int(clear_pct_by_time.argmax().values)
#     best_clear_pct = float(clear_pct_by_time.isel(time=best_i).values * 100.0)

#     if ds.sizes.get("time", 1) > 1:
#         times = [str(t) for t in ds["time"].values]
#         print(f"[INFO] Multiple slices returned for {date}: n={ds.sizes['time']} -> choosing best_i={best_i}")
#         print(f"[DEBUG] time coords: {times}")
#         print(f"[DEBUG] clear% by slice: {[float(x*100.0) for x in clear_pct_by_time.values]}")

#     ds0 = ds.isel(time=best_i)

#     red = ds0["nbart_red"].astype("float32")
#     nir = ds0["nbart_nir"].astype("float32")
#     oa  = ds0["oa_fmask"].astype("uint8")

#     # clear mask: True where oa_fmask is "clear"
#     clear = oa.isin(CLEAR_VALUES)

#     # percent clear for your threshold
#     # cloud_max=40 => require clear >= 60%
#     min_clear_pct = 100.0 - float(cloud_max)
#     clear_pct = best_clear_pct

#     print(f"[INFO] Clear% (oa_fmask in {CLEAR_VALUES}): {clear_pct:.2f}% (min required {min_clear_pct:.2f}%)")
#     if clear_pct < min_clear_pct:
#         print(f"[SKIP] Rejected by clear% threshold: {clear_pct:.2f}% < {min_clear_pct:.2f}%")
#         return

#     # NDVI (avoid divide-by-zero)
#     denom = (nir + red)
#     ndvi = (nir - red) / denom.where(denom != 0, other=np.float32(np.nan))
#     ndvi = ndvi.where(clear, other=np.float32(-9999.0)).astype("float32")

#     # ffmask output as uint8: 1 clear, 0 masked
#     ffmask = clear.astype("uint8")

#     # local staging filenames (only temporary; uploads go to S3 keys)
#     ndvi_local = work_dir / f"lztmre_{tile}_{date}_ndvi_{int(target_epsg)}.tif"
#     fmk_local  = work_dir / f"lztmre_{tile}_{date}_ffmask_{int(target_epsg)}.tif"
#     print(f"[DEBUG] -- ndvi_local:  {ndvi_local}")
#     print(f"[DEBUG] -- fmk_local:  {fmk_local}")

#     # ------------------------------------------------------------------
#     # Ensure CRS metadata survives xarray math
#     # lib/cog.py requires da.attrs["crs"]
#     # ------------------------------------------------------------------
#     crs_val = (
#         ds.attrs.get("crs")
#         or ds0.attrs.get("crs")
#         or ds0["oa_fmask"].attrs.get("crs")
#         or ds0["nbart_red"].attrs.get("crs")
#         or ds0["nbart_nir"].attrs.get("crs")
#     )

#     if not crs_val:
#         # last-resort: try the common spatial_ref coordinate
#         try:
#             # often holds WKT or EPSG-ish info
#             crs_val = ds0["spatial_ref"].attrs.get("crs_wkt") or ds0["spatial_ref"].attrs.get("wkt")
#         except Exception:
#             crs_val = None

#     if not crs_val:
#         raise RuntimeError(
#             "Cannot determine CRS for output COG. "
#             "Tried ds.attrs['crs'], band attrs, and spatial_ref wkt."
#         )

#     # attach to outputs so cog.py can read it
#     ndvi.attrs["crs"] = crs_val
#     ffmask.attrs["crs"] = crs_val


#     # write Cloud Optimised GeoTIFFs (COGs)
#     write_cog_float32(ndvi, out_path=str(ndvi_local), nodata=-9999.0)
#     write_cog_uint8(ffmask, out_path=str(fmk_local), nodata=0)

#     # upload to S3 using the provided keys (do NOT rewrite keys here)
#     upload_file_to_s3(str(ndvi_local), bucket=bucket, key=ndvi_key)
#     upload_file_to_s3(str(fmk_local),  bucket=bucket, key=ffmask_key)

#     print(f"[OK] NDVI   -> s3://{bucket}/{ndvi_key}")
#     print(f"[OK] FFMASK -> s3://{bucket}/{ffmask_key}")

#     # optional local cleanup (if you want it)
#     if not rebase:
#         try:
#             ndvi_local.unlink(missing_ok=True)
#             fmk_local.unlink(missing_ok=True)
#         except Exception:
#             pass

def process_scene_to_s3(
    tile: str,
    date: str,              # YYYYMMDD
    platform: str,
    product: str,
    lon_min: float,
    lat_min: float,
    lon_max: float,
    lat_max: float,
    target_epsg: int,
    cloud_max: float,
    bucket: str,
    ndvi_key: str,
    ffmask_key: str,
    work_dir: Path,
    resolution: float,
    rebase: bool,
    dask_chunk: int = 2048,
) -> None:
    """
    Loads nbart_red, nbart_nir, oa_fmask from datacube for one scene date.

    - Queries by TILE BBOX (WGS84)
    - Filters datasets to the *exact* WRS tile
    - skip_broken_datasets=True so it doesn’t crash on bad URIs
    - Picks the best slice based on clear %
    - Masks using oa_fmask
    - Writes NDVI and FFMASK as COGs
    - Uploads outputs to S3
    """



    # these imports should already exist but just assuming they do
    # from lib.cog import write_cog_uint8, write_cog_float32
    # from lib.s3_io import upload_file_to_s3

    # normalise tile name
    tile = tile.lower().strip()

    # make sure work dir exists
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # open datacube connection
    dc = datacube.Datacube(app="optimised_ndvi_process")

    # convert YYYYMMDD into something datacube likes
    t0 = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    time = (t0, t0)

    # chunking so we don’t blow memory
    dask_chunks = {"x": int(dask_chunk), "y": int(dask_chunk)}

    # basic logging so we know what’s happening
    print(f"[INFO] Loading {tile} {platform} {date} product={product} EPSG:{target_epsg}")
    print(f"[DEBUG] lon=({lon_min}, {lon_max}) lat=({lat_min}, {lat_max}) time={time}")



    # ------------------------------------------------------------------
    # Filter datasets to the exact tile (prevents 115077/115079 neighbours)
    # ------------------------------------------------------------------
    m = re.fullmatch(r"p(\d{3})r(\d{3})", tile)
    if not m:
        raise ValueError(f"Expected tile like p###r###, got: {tile}")
    path = int(m.group(1))
    row  = int(m.group(2))
    region_code = f"{path:03d}{row:03d}"  # e.g. "115078"

    def only_this_tile(ds) -> bool:
        # Common on DEA ARD datasets
        rc = getattr(getattr(ds, "metadata", None), "region_code", None)
        if rc is not None:
            return str(rc) == region_code

        # Fallback: check URI contains /PPP/RRR/
        try:
            uri = ds.uri if hasattr(ds, "uri") else (ds.uris[0] if hasattr(ds, "uris") and ds.uris else "")
            return f"/{path:03d}/{row:03d}/" in str(uri)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------

    # DEBUG 
    ds_native = dc.load(
        product=product,
        measurements=["nbart_red"],
        time=time,
        lon=(float(lon_min), float(lon_max)),
        lat=(float(lat_min), float(lat_max)),
        dataset_predicate=only_this_tile,
        skip_broken_datasets=True,
    )

    if ds_native and ds_native.sizes.get("time", 0) > 0:
        print("\n=== NATIVE CRS DEBUG ===")
        print("Native dataset CRS:", ds_native.odc.geobox.crs)
        print("Native resolution:", ds_native.odc.geobox.resolution)
        print("========================\n")


    ds = dc.load(
        product=product,
        measurements=["nbart_red", "nbart_nir", "oa_fmask"],
        time=time,
        lon=(float(lon_min), float(lon_max)),
        lat=(float(lat_min), float(lat_max)),
        output_crs=f"EPSG:{int(target_epsg)}",
        resolution=(-float(resolution), float(resolution)),
        dask_chunks=dask_chunks,
        dataset_predicate=only_this_tile,
        skip_broken_datasets=True,
    )

    print("\n=== CRS DEBUG ===")
    print("Returned dataset CRS:", ds.odc.geobox.crs)
    print("Resolution:", ds.odc.geobox.resolution)
    print("=================\n")


    # import sys
    # sys.exit("forces stop debug crs")


    # Hard-skip if datacube had to ignore broken datasets (prevents small outputs)
    for band in ["oa_fmask", "nbart_red", "nbart_nir"]:
        try:
            _ = ds[band].isel(time=0).mean().compute()
        except Exception as e:
            print(f"[SKIP] Broken dataset: {band} cannot be read ({tile} {date}): {e}")
            return



    if ds is None or "time" not in ds.dims or ds.sizes.get("time", 0) == 0:
        raise RuntimeError(f"No data returned by dc.load for tile={tile} product={product} date={date}")

    # ------------------------------------------------------------------
    # LAND-ONLY definition for DEA ARD oa_fmask:
    # 0 = nodata, 1 = clear land, 2 = water, 3 = shadow, 5 = cloud (common classes)
    # We ONLY keep clear land (1) and drop everything else. im pretty sure this is right but should check
    # TODO: check the mask outputs actually look ok
    # ------------------------------------------------------------------
    LAND_CLEAR_VALUE = 1

    def _valid_mask(oa_da):
        # try get nodata from attrs (in my test it was 0)
        nodata = oa_da.attrs.get("nodata", None)

        # if nodata is missing just assume finite values are ok
        if nodata is None:
            return np.isfinite(oa_da)

        # valid is anything not nodata
        return (oa_da != nodata)

    def _land_clear_mask(oa_da):
        # valid pixels only + clear land class
        valid = _valid_mask(oa_da)
        return (oa_da == LAND_CLEAR_VALUE) & valid

    def _land_clear_pct_by_time(oa_da):
        # returns fraction (0..1) per time slice
        land_clear = _land_clear_mask(oa_da)
        valid = _valid_mask(oa_da)

        # count how many pixels are valid and how many are clear
        valid_count = valid.sum(dim=("y", "x"))
        clear_count = land_clear.sum(dim=("y", "x"))

        # divide to get percent (but dont divide by 0)
        frac = (clear_count / valid_count).where(valid_count > 0)
        return frac

    # ------------------------------------------------------------------
    # pick the best time slice based on LAND-CLEAR% (also try not to crash if sources are broken)
    # NOTE: we are NOT filtering scenes by this %, we only filter by metadata cloud < 40.
    # ------------------------------------------------------------------
    try:
        # calculate land clear fraction per time (forces compute so we actually hit the data)
        land_clear_frac_by_time = _land_clear_pct_by_time(ds["oa_fmask"]).compute()
    except Exception as e:
        # if it errors its probably a broken URI / missing file so just skip this scene
        print(f"[SKIP] Broken source data while computing land-clear% for {tile} {date} ({product}): {e}")
        return

    # old code left here just in case
    # best_i = int(land_clear_frac_by_time.argmax().values)
    # best_land_clear_pct = float(land_clear_frac_by_time.isel(time=best_i).values * 100.0)

    # if everything comes back NaN then theres nothing useful, so skip it
    lc = land_clear_frac_by_time
    if bool(lc.isnull().all()):
        print(f"[SKIP] land-clear% is all-NaN for {tile} {date} ({product}) - likely missing/broken fmask source")
        return

    # fill NaNs with -1 so argmax doesnt choke and it ignores NaNs basically
    lc_filled = lc.fillna(-1.0)

    # choose index of best time slice
    best_i = int(lc_filled.argmax(dim="time").values)

    # get the actual % for that slice (from the original lc, not the filled one)
    best_land_clear_pct = float(lc.isel(time=best_i).values * 100.0)

    # if multiple slices returned, print some debug so we can see what it picked
    if ds.sizes.get("time", 1) > 1:
        times = [str(t) for t in ds["time"].values]
        print(f"[INFO] Multiple slices returned for {date}: n={ds.sizes['time']} -> choosing best_i={best_i}")
        print(f"[DEBUG] time coords: {times}")
        print(f"[DEBUG] land-clear% by slice: {[float(x*100.0) for x in land_clear_frac_by_time.values]}")

    # grab only the best slice now
    ds0 = ds.isel(time=best_i)

    # pull out bands we need (cast types so maths works)
    red = ds0["nbart_red"].astype("float32")
    nir = ds0["nbart_nir"].astype("float32")
    oa  = ds0["oa_fmask"].astype("uint8")

    # land-only mask (keep oa_fmask == 1 and valid pixels)
    land_clear = _land_clear_mask(oa)

    # log the land clear % (just for info, not actually filtering)
    print(f"[INFO] Land-clear% (oa_fmask=={LAND_CLEAR_VALUE}, valid-only): {best_land_clear_pct:.2f}% (QA only; not used for filtering)")

    # ------------------------------------------------------------------
    # NDVI (computed everywhere valid, then masked to land-only)
    # ------------------------------------------------------------------
    denom = (nir + red)
    ndvi = (nir - red) / denom.where(denom != 0, other=np.float32(np.nan))

    # Apply land-only mask: everything else becomes nodata
    ndvi = ndvi.where(land_clear, other=np.float32(-9999.0)).astype("float32")

    # ffmask: 1 = kept (clear land), 0 = masked (water/cloud/shadow/nodata)
    ffmask = land_clear.astype("uint8")

    # ------------------------------------------------------------------
    # IMPORTANT: ensure cog.py can determine CRS.
    # output_crs == EPSG:target_epsg
    # ------------------------------------------------------------------
    ndvi.attrs["crs"] = f"EPSG:{int(target_epsg)}"
    ffmask.attrs["crs"] = f"EPSG:{int(target_epsg)}"

    # local staging filenames
    ndvi_local = work_dir / f"lztmre_{tile}_{date}_ndvi_{int(target_epsg)}.tif"
    fmk_local  = work_dir / f"lztmre_{tile}_{date}_ffmask_{int(target_epsg)}.tif"
    print(f"[DEBUG] -- ndvi_local: {ndvi_local}")
    print(f"[DEBUG] -- fmk_local:  {fmk_local}")

    # write Cloud Optimised GeoTIFFs (COGs)
    write_cog_float32(ndvi, out_path=str(ndvi_local), nodata=-9999.0)
    write_cog_uint8(ffmask, out_path=str(fmk_local), nodata=0)

    # upload to S3 using the provided keys
    upload_file_to_s3(str(ndvi_local), bucket=bucket, key=ndvi_key)
    upload_file_to_s3(str(fmk_local),  bucket=bucket, key=ffmask_key)

    print(f"[OK] NDVI   -> s3://{bucket}/{ndvi_key}")
    print(f"[OK] FFMASK -> s3://{bucket}/{ffmask_key}")

    # optional local cleanup
    if not rebase:
        try:
            ndvi_local.unlink(missing_ok=True)
            fmk_local.unlink(missing_ok=True)
        except Exception:
            pass

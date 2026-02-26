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
    Loads LSAT nbart_red, nbart_nir, oa_fmask from datacube for one scene date.

    - Queries by TILE BBOX (WGS84)
    - Filters datasets to the *exact* WRS tile (prevents neighbour tiles)
    - skip_broken_datasets=True to avoid crashing on stale 404 URIs

    - Chooses BEST slice (if multiple) by max CLEAR%
    - Masks using oa_fmask clear class for this product (your test: clear=0)
    - Writes NDVI + FFMASK as Cloud Optimised GeoTIFFs (COGs)
    - Uploads outputs to S3 using provided keys
    """


    # NOTE: these imports should already be at the top of the file but whatever
    # from lib.cog import write_cog_uint8, write_cog_float32
    # from lib.s3_io import upload_file_to_s3

    tile = tile.lower().strip()

    # make sure work dir exists
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # create datacube instance
    dc = datacube.Datacube(app="optimised_ndvi_process")

    # datacube wants time in YYYY-MM-DD format so convert it
    t0 = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    time = (t0, t0)


    # use chunking so we dont load everything into memory at once
    dask_chunks = {"x": int(dask_chunk), "y": int(dask_chunk)}


    # print some logs so we can see what scene its doing
    print(f"[INFO] Loading {tile} {platform} {date} product={product} EPSG:{target_epsg}")
    print(f"[DEBUG] lon=({lon_min}, {lon_max}) lat=({lat_min}, {lat_max}) time={time}")

    # ------------------------------------------------------------------
    # filter datasets down to the exact tile only
    # (bbox queries can pull in neighbour tiles like 115077/115079)
    # ------------------------------------------------------------------
    m = re.fullmatch(r"p(\d{3})r(\d{3})", tile)
    if not m:
        # tile format is expected to be p###r### or this wont work
        raise ValueError(f"Expected tile like p###r###, got: {tile}")

    # parse out path/row from the tile string
    path = int(m.group(1))
    row = int(m.group(2))

    # build the region code like "115078"
    region_code = f"{path:03d}{row:03d}"

    def only_this_tile(ds) -> bool:
        # first try region_code from metadata (if it exists)
        rc = getattr(getattr(ds, "metadata", None), "region_code", None)
        if rc is not None:
            return str(rc) == region_code

        # fallback: check if the dataset uri contains /PPP/RRR/
        try:
            uri = (
                ds.uri if hasattr(ds, "uri")
                else (ds.uris[0] if hasattr(ds, "uris") and ds.uris else "")
            )
            return f"/{path:03d}/{row:03d}/" in str(uri)
        except Exception:
            # if anything goes wrong just treat it as not matching
            return False

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
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

    # Hard-skip if datacube had to ignore broken datasets (prevents tiny outputs)
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
    # 0 = nodata, 1 = clear land, 2 = water, 3 = shadow, 5 = cloud  (common classes)
    # We KEEP ONLY clear land (1) and REMOVE everything else.
    # ------------------------------------------------------------------
    LAND_CLEAR_VALUE = 1

    def _valid_mask(oa_da):
        nodata = oa_da.attrs.get("nodata", None)  # in your test: 0
        if nodata is None:
            return np.isfinite(oa_da)
        return (oa_da != nodata)

    def _land_clear_mask(oa_da):
        valid = _valid_mask(oa_da)
        return (oa_da == LAND_CLEAR_VALUE) & valid

    def _land_clear_pct_by_time(oa_da):
        # returns fraction (0..1) per time slice
        land_clear = _land_clear_mask(oa_da)
        valid = _valid_mask(oa_da)
        valid_count = valid.sum(dim=("y", "x"))
        clear_count = land_clear.sum(dim=("y", "x"))
        frac = (clear_count / valid_count).where(valid_count > 0)
        return frac

    # ------------------------------------------------------------------
    # Choose best slice by LAND-CLEAR% (guard against broken source errors)
    # NOTE: We DO NOT reject scenes based on this % (your filter is metadata cloud <40).
    # ------------------------------------------------------------------
    try:
        land_clear_frac_by_time = _land_clear_pct_by_time(ds["oa_fmask"]).compute()
    except Exception as e:
        print(f"[SKIP] Broken source data while computing land-clear% for {tile} {date} ({product}): {e}")
        return

    # best_i = int(land_clear_frac_by_time.argmax().values)
    # best_land_clear_pct = float(land_clear_frac_by_time.isel(time=best_i).values * 100.0)

    # If everything is NaN (broken/missing sources), skip gracefully
    lc = land_clear_frac_by_time

    if bool(lc.isnull().all()):
        print(f"[SKIP] land-clear% is all-NaN for {tile} {date} ({product}) - likely missing/broken fmask source")
        return

    # pick best slice ignoring NaNs
    lc_filled = lc.fillna(-1.0)
    best_i = int(lc_filled.argmax(dim="time").values)
    best_land_clear_pct = float(lc.isel(time=best_i).values * 100.0)


    # datacube sometimes gives more than one time slice back, so log it
    if ds.sizes.get("time", 1) > 1:
        # convert time coords to strings
        times = [str(t) for t in ds["time"].values]

        print(f"[INFO] Multiple slices returned for {date}: n={ds.sizes['time']} -> choosing best_i={best_i}")

        # dump the time values
        print(f"[DEBUG] time coords: {times}")

        # dump land clear % per slice so we can see why it picked that one
        print(f"[DEBUG] land-clear% by slice: {[float(x*100.0) for x in land_clear_frac_by_time.values]}")

    ds0 = ds.isel(time=best_i)

    red = ds0["nbart_red"].astype("float32")
    nir = ds0["nbart_nir"].astype("float32")
    oa  = ds0["oa_fmask"].astype("uint8")

    # Land-only mask: keep only oa_fmask == 1 (clear land) and valid (not nodata)
    land_clear = _land_clear_mask(oa)

    print(f"[INFO] Land-clear% (oa_fmask=={LAND_CLEAR_VALUE}, valid-only): {best_land_clear_pct:.2f}% (QA only; not used for filtering)")

    # ------------------------------------------------------------------
    # NDVI (computed everywhere valid, then mask to land-only)
    # ------------------------------------------------------------------
    denom = (nir + red)
    ndvi = (nir - red) / denom.where(denom != 0, other=np.float32(np.nan))

    # Apply land-only mask: everything else becomes nodata
    ndvi = ndvi.where(land_clear, other=np.float32(-9999.0)).astype("float32")

    # ffmask: 1 = kept (clear land), 0 = mask (water/cloud/shadow/nodata)
    ffmask = land_clear.astype("uint8")

    # ------------------------------------------------------------------
    # IMPORTANT: ensure cog.py can determine CRS.
    # We *know* output_crs == EPSG:target_epsg
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

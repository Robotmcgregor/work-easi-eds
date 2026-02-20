from __future__ import annotations

from pathlib import Path
import numpy as np
from osgeo import gdal

# ... existing imports ...
from lib.geo import (
    derive_target_epsg_gda94_mga,
    warp_to_epsg,
    compute_ndvi,
    write_cog_from_array,
)
from lib.s3_io import upload_file_to_s3


def process_scene_to_s3(
    tile: str,
    date: str,
    platform: str,
    red_path: str,
    nir_path: str,
    ffmask_path: str,   # <- this is oa_fmask on input
    bucket: str,
    out_key: str,       # NDVI output key (datatype=ndvi)
    work_dir: Path,
    target_epsg: int,
    resolution: float,
    rebase: bool,
) -> None:

    # --- decide EPSG ---
    if target_epsg == 0:
        ds_ref = gdal.Open(red_path, gdal.GA_ReadOnly)
        if ds_ref is None:
            raise RuntimeError(f"Cannot open red_path: {red_path}")
        target_epsg = derive_target_epsg_gda94_mga(ds_ref)
        ds_ref = None

    # --- local staged filenames (NO ffmask datatype; we will output oa_fmask) ---
    red_w = work_dir / f"lztmre_{tile}_{date}_red_{target_epsg}.tif"
    nir_w = work_dir / f"lztmre_{tile}_{date}_nir_{target_epsg}.tif"
    oa_w  = work_dir / f"lztmre_{tile}_{date}_oa_fmask_{target_epsg}.tif"   # binary clear mask output
    ndv_o = work_dir / f"lztmre_{tile}_{date}_ndvi_{target_epsg}.tif"

    print(f"[INFO] Target EPSG: {target_epsg}")

    # --- warp inputs to the same grid ---
    warp_to_epsg(src=red_path, dst=str(red_w), epsg=target_epsg, res=resolution)
    warp_to_epsg(src=nir_path, dst=str(nir_w), epsg=target_epsg, res=resolution, match=str(red_w))

    # oa_fmask must use nearest resampling to preserve class values
    warp_to_epsg(
        src=ffmask_path,          # oa_fmask source
        dst=str(oa_w),
        epsg=target_epsg,
        res=resolution,
        match=str(red_w),
        nearest=True,             # IMPORTANT: preserve mask classes
    )

    # --- read arrays ---
    red = gdal.Open(str(red_w)).ReadAsArray().astype(np.float32)
    nir = gdal.Open(str(nir_w)).ReadAsArray().astype(np.float32)
    oa  = gdal.Open(str(oa_w)).ReadAsArray().astype(np.uint8)

    # ------------------------------------------------------------------
    # Derive *binary clear mask* from oa_fmask (legacy: clear == 1)
    # Output:
    #   1 = clear/valid
    #   0 = masked (cloud, water, shadow, etc.)
    # ------------------------------------------------------------------
    clear_mask = (oa == 1).astype(np.uint8)

    # Overwrite oa_w with the binary clear mask as an optimised COG
    write_cog_from_array(
        ref_path=str(red_w),
        out_path=str(oa_w),
        array=clear_mask,
        nodata=0,                  # 0 = masked/nodata
        dtype=gdal.GDT_Byte,
    )

    # Upload oa_fmask next to NDVI using the same naming convention
    oa_key = out_key.replace("_ndvi_", "_oa_fmask_")
    upload_file_to_s3(local_path=str(oa_w), bucket=bucket, key=oa_key)
    print(f"[OK] oa_fmask -> s3://{bucket}/{oa_key}")

    # ------------------------------------------------------------------
    # Compute NDVI using the *binary clear mask*
    # (compute_ndvi should treat clear_mask==1 as valid)
    # ------------------------------------------------------------------
    ndvi = compute_ndvi(red, nir, clear_mask)

    # Write NDVI as COG + upload (existing behaviour)
    write_cog_from_array(
        ref_path=str(red_w),
        out_path=str(ndv_o),
        array=ndvi,
        nodata=-9999.0,
        dtype=gdal.GDT_Float32,
    )

    upload_file_to_s3(local_path=str(ndv_o), bucket=bucket, key=out_key)
    print(f"[OK] ndvi -> s3://{bucket}/{out_key}")

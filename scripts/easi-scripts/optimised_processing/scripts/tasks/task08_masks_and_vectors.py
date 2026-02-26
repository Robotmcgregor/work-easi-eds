from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import rasterio
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape

from lib.s3_io import upload_file_to_s3
from lib.cog import to_cog


@dataclass(frozen=True)
class MaskVectorOutputs:
    """
    Simple container for mask vector output paths.
    Just groups everything together so its easier to pass around.
    """
    strong_mask_local: Path
    clear_mask_local: Path
    strong_mask_s3: str
    clear_mask_s3: str
    strong_shp_s3_prefix: str
    clear_shp_s3_prefix: str


def _write_mask_geotiff(
    *,
    src_profile: dict,
    src_transform,
    src_crs,
    mask_u8: np.ndarray,
    out_raw: Path,
) -> None:
    profile = src_profile.copy()
    profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=0,
        compress="DEFLATE",
        predictor=2,
        tiled=True,
        blockxsize=512,
        blockysize=512,
        BIGTIFF="IF_SAFER",
    )

    # Ensure 2D
    if mask_u8.ndim != 2:
        raise ValueError(f"Expected 2D mask array, got shape={mask_u8.shape}")

    with rasterio.open(out_raw, "w", **profile) as dst:
        dst.write(mask_u8, 1)

def _polygonise_mask(
    *,
    mask_u8: np.ndarray,
    transform,
    crs,
    min_area_ha: float = 0.0,
) -> gpd.GeoDataFrame:
    """Turn pixels == 1 into polygons (stays in the raster CRS)."""

    # make sure mask is uint8 because thats what shapes() expects basically
    if mask_u8.dtype != np.uint8:
        mask_u8 = mask_u8.astype(np.uint8)

    # rasterio shapes generator (only where mask == 1)
    geom_val_iter = shapes(mask_u8, mask=(mask_u8 == 1), transform=transform)

    # collect geometries + values
    geoms: List = []
    vals: List[int] = []
    for geom, val in geom_val_iter:
        # only keep the 1s (should already be filtered but just in case)
        if int(val) != 1:
            continue
        geoms.append(shape(geom))
        vals.append(int(val))

    # if nothing came back, return empty gdf
    if not geoms:
        return gpd.GeoDataFrame({"value": [], "area_ha": []}, geometry=[], crs=crs)

    # build geodataframe
    gdf = gpd.GeoDataFrame({"value": vals}, geometry=geoms, crs=crs)

    # area in hectares (assumes CRS is metres which it probably is)
    gdf["area_ha"] = gdf.geometry.area / 10_000.0

    # optionally drop tiny polygons
    if min_area_ha and float(min_area_ha) > 0:
        gdf = gdf[gdf["area_ha"] >= float(min_area_ha)].copy()

    # try to clean invalid geometry (buffer(0) hack)
    try:
        gdf["geometry"] = gdf["geometry"].buffer(0)
        gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty]
    except Exception:
        # ignore if it fails
        pass

    return gdf


def _write_shapefile_set(gdf: gpd.GeoDataFrame, out_dir: Path, stem: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    shp_path = out_dir / f"{stem}.shp"
    # ESRI Shapefile driver creates the sidecar files automatically
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    return shp_path


def _upload_shapefile_folder(local_dir: Path, bucket: str, s3_prefix: str) -> None:
    # upload all expected shapefile components present in folder
    for p in sorted(local_dir.glob("*")):
        if p.is_file():
            key = f"{s3_prefix.rstrip('/')}/{p.name}"
            upload_file_to_s3(str(p), bucket=bucket, key=key)


def make_masks_and_vectors(
    *,
    dljmz_cog_local: Path,
    bucket: str,
    s3_prefix: str,
    tile: str,
    run_tag: str,
    strong_threshold: int = 60,
    clear_threshold: int = 80,
    min_area_ha: float = 0.0,
    work_dir: Path,
    rebase: bool = False,
    dry_run: bool = False,
) -> MaskVectorOutputs:
    """
    Create:
      - strong_mask_cog.tif (>= strong_threshold)
      - clear_mask_cog.tif  (>= clear_threshold)
      - polygonised shapefiles for each mask

    Uses the dljmz COG as clearing_prob source.
    """
    tile = tile.lower().strip()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    masks_s3_dir = f"{s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}/masks"
    vec_s3_dir   = f"{s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}/vectors"

    strong_mask_key = f"{masks_s3_dir}/lztmre_{tile}_{run_tag}_strong_ge{int(strong_threshold):02d}_mask_cog.tif"
    clear_mask_key  = f"{masks_s3_dir}/lztmre_{tile}_{run_tag}_clear_ge{int(clear_threshold):02d}_mask_cog.tif"

    # strong_mask_raw = work_dir / f"{tile}_{run_tag}_strong_mask_raw.tif"
    # clear_mask_raw  = work_dir / f"{tile}_{run_tag}_clear_mask_raw.tif"

    # strong_mask_cog = work_dir / f"{tile}_{run_tag}_strong_mask_cog.tif"
    # clear_mask_cog  = work_dir / f"{tile}_{run_tag}_clear_mask_cog.tif"

    strong_mask_raw = work_dir / f"{run_tag}_strong_mask_raw.tif"
    clear_mask_raw  = work_dir / f"{run_tag}_clear_mask_raw.tif"

    strong_mask_cog = work_dir / f"{run_tag}_strong_mask_cog.tif"
    clear_mask_cog  = work_dir / f"{run_tag}_clear_mask_cog.tif"

    strong_vec_dir = work_dir / "vectors" / "strong"
    clear_vec_dir  = work_dir / "vectors" / "clear"

    strong_vec_prefix = f"{vec_s3_dir}/strong_ge{int(strong_threshold):02d}"
    clear_vec_prefix  = f"{vec_s3_dir}/clear_ge{int(clear_threshold):02d}"

    if dry_run:
        print(f"[DRY] MASK strong >= {strong_threshold} -> s3://{bucket}/{strong_mask_key}")
        print(f"[DRY] MASK clear  >= {clear_threshold}  -> s3://{bucket}/{clear_mask_key}")
        print(f"[DRY] VECT strong -> s3://{bucket}/{strong_vec_prefix}/")
        print(f"[DRY] VECT clear  -> s3://{bucket}/{clear_vec_prefix}/")
        return MaskVectorOutputs(
            strong_mask_local=strong_mask_cog,
            clear_mask_local=clear_mask_cog,
            strong_mask_s3=strong_mask_key,
            clear_mask_s3=clear_mask_key,
            strong_shp_s3_prefix=strong_vec_prefix,
            clear_shp_s3_prefix=clear_vec_prefix,
        )

    # with rasterio.open(dljmz_cog_local) as src:
    #         # dljmz is multi-band; clearing_prob is band 4 in the legacy output
    # band = 4 if src.count >= 4 else 1
    # if src.count < 4:
    #     print(f"[WARN] dljmz has only {src.count} band(s); using band 1")
    # arr = src.read(band)
    # print(f"[INFO] dljmz band {band} stats: min={arr.min()} max={arr.max()} dtype={arr.dtype}")
    # #     profile = src.profile
    # #     transform = src.transform
    # #     crs = src.crs

    # ------------------------------------------------------------
    # Read dljmz (multi-band). clearing_prob is band 4 in legacy output.
    # ------------------------------------------------------------
    with rasterio.open(dljmz_cog_local) as src:
        band = 4 if src.count >= 4 else 1
        if src.count < 4:
            print(f"[WARN] dljmz has only {src.count} band(s); using band 1")

        arr = src.read(band)
        print("-"*100)
        print("[CHECK] band4 >=60:", int((arr >= 60).sum()))
        print("[CHECK] band4 >=80:", int((arr >= 80).sum()))
        print("[CHECK] band4 nonzero:", int((arr != 0).sum()))
        print("-"*100)

        profile = src.profile.copy()
        transform = src.transform
        crs = src.crs

    # Stats (helpful for confirming range ~0..200 for clearing_prob)
    finite = np.isfinite(arr)
    if finite.any():
        print(
            f"[INFO] dljmz band {band} stats: "
            f"min={arr[finite].min()} max={arr[finite].max()} dtype={arr.dtype}"
        )
    else:
        print(f"[WARN] dljmz band {band} has no finite pixels")

    # dljmz is uint8 in legacy output (0..200). Treat nodata as invalid if set.
    nodata = profile.get("nodata", None)
    if nodata is not None:
        valid = arr != nodata
    else:
        valid = np.ones_like(arr, dtype=bool)

    # masks: keep only valid pixels
    strong = (arr >= int(strong_threshold)) & valid
    clear  = (arr >= int(clear_threshold)) & valid

    strong_u8 = strong.astype(np.uint8)
    clear_u8  = clear.astype(np.uint8)

    print("[DEBUG] MASK DIAGNOSTICS")

    print("[DEBUG] strong mask stats:")
    print("  unique values:", np.unique(strong_u8))
    print("  pixel count (sum):", int(strong_u8.sum()))
    print("  pixel count (>0):", int((strong_u8 > 0).sum()))

    print("[DEBUG] clear mask stats:")
    print("  unique values:", np.unique(clear_u8))
    print("  pixel count (sum):", int(clear_u8.sum()))
    print("  pixel count (>0):", int((clear_u8 > 0).sum()))
    print("="*80 + "\n")

    print(f"[INFO] strong pixels: {int(strong_u8.sum())}, clear pixels: {int(clear_u8.sum())}")
    print("="*100)

    # ------------------------------------------------------------
    # Write raw mask GeoTIFFs (required before COG conversion)
    # ------------------------------------------------------------
    mask_profile = profile.copy()
    mask_profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=0,              # mask nodata/background is 0
        compress="deflate",
        tiled=True,
    )

    # Write raw mask GeoTIFFs first
    with rasterio.open(str(strong_mask_raw), "w", **mask_profile) as dst:
        dst.write(strong_u8, 1)

    with rasterio.open(str(clear_mask_raw), "w", **mask_profile) as dst:
        dst.write(clear_u8, 1)

    # ------------------------------------------------------------
    # DEBUG: Verify raw masks written correctly
    # ------------------------------------------------------------
    print("\n" + "="*80)
    print("[DEBUG] VERIFY RAW MASKS ON DISK")

    with rasterio.open(str(strong_mask_raw)) as src:
        arr_check = src.read(1)
        print("[DEBUG] strong_mask_raw unique:", np.unique(arr_check))
        print("[DEBUG] strong_mask_raw sum:", int(arr_check.sum()))
        print("[DEBUG] strong_mask_raw >0:", int((arr_check > 0).sum()))

    with rasterio.open(str(clear_mask_raw)) as src:
        arr_check = src.read(1)
        print("[DEBUG] clear_mask_raw unique:", np.unique(arr_check))
        print("[DEBUG] clear_mask_raw sum:", int(arr_check.sum()))
        print("[DEBUG] clear_mask_raw >0:", int((arr_check > 0).sum()))

    print("="*80 + "\n")

    # Hard assert to catch path mistakes early
    if not strong_mask_raw.exists():
        raise FileNotFoundError(f"Strong raw mask not created: {strong_mask_raw}")
    if not clear_mask_raw.exists():
        raise FileNotFoundError(f"Clear raw mask not created: {clear_mask_raw}")


    # Convert to COG (lossless)
    to_cog(str(strong_mask_raw), str(strong_mask_cog), overwrite=True)
    to_cog(str(clear_mask_raw), str(clear_mask_cog), overwrite=True)

    upload_file_to_s3(str(strong_mask_cog), bucket=bucket, key=strong_mask_key)
    upload_file_to_s3(str(clear_mask_cog), bucket=bucket, key=clear_mask_key)

    # Polygonise & write shapefiles
    gdf_strong = _polygonise_mask(mask_u8=strong_u8, transform=transform, crs=crs, min_area_ha=float(min_area_ha))
    gdf_clear  = _polygonise_mask(mask_u8=clear_u8,  transform=transform, crs=crs, min_area_ha=float(min_area_ha))

    print("\n" + "="*80)
    print("[DEBUG] POLYGON DIAGNOSTICS")

    print(f"[DEBUG] Strong polygons count: {len(gdf_strong)}")
    if len(gdf_strong) > 0:
        print("[DEBUG] Strong polygons head:")
        print(gdf_strong.head())
        print("[DEBUG] Strong polygon areas (ha) sample:")
        if "area_ha" in gdf_strong.columns:
            print(gdf_strong["area_ha"].head())
    else:
        print("[DEBUG] Strong polygon GeoDataFrame is EMPTY")

    print("-"*60)

    print(f"[DEBUG] Clear polygons count: {len(gdf_clear)}")
    if len(gdf_clear) > 0:
        print("[DEBUG] Clear polygons head:")
        print(gdf_clear.head())
        print("[DEBUG] Clear polygon areas (ha) sample:")
        if "area_ha" in gdf_clear.columns:
            print(gdf_clear["area_ha"].head())
    else:
        print("[DEBUG] Clear polygon GeoDataFrame is EMPTY")

    print("="*80 + "\n")

    _write_shapefile_set(gdf_strong, strong_vec_dir, stem=f"lztmre_{tile}_{run_tag}_strong_ge{int(strong_threshold):02d}")
    _write_shapefile_set(gdf_clear,  clear_vec_dir,  stem=f"lztmre_{tile}_{run_tag}_clear_ge{int(clear_threshold):02d}")

    # Upload shapefile folders (all sidecar files)
    _upload_shapefile_folder(strong_vec_dir, bucket=bucket, s3_prefix=strong_vec_prefix)
    _upload_shapefile_folder(clear_vec_dir,  bucket=bucket, s3_prefix=clear_vec_prefix)

    # cleanup raw masks
    try:
        strong_mask_raw.unlink(missing_ok=True)
        clear_mask_raw.unlink(missing_ok=True)
    except Exception:
        pass

    return MaskVectorOutputs(
        strong_mask_local=strong_mask_cog,
        clear_mask_local=clear_mask_cog,
        strong_mask_s3=strong_mask_key,
        clear_mask_s3=clear_mask_key,
        strong_shp_s3_prefix=strong_vec_prefix,
        clear_shp_s3_prefix=clear_vec_prefix,
    )

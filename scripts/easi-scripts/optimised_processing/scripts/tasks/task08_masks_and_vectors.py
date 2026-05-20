from __future__ import annotations

"""Task 08: create masks and shapefiles from the DLJ output.

Non-coder summary:
- DLJ contains an interpretation band we treat as "clearing probability".
- We threshold that band to create two mask rasters:
    - strong: more conservative (default >= 60)
    - clear:  more confident (default >= 80)
- We then polygonise those masks to create shapefiles.

These are typically the artefacts used for QA and for area calculations.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import rasterio
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape

from lib.cog import to_cog
from lib.s3_io import upload_file_to_s3

import re

def _insert_tag_before_epsg(base_name: str, tag: str) -> str:
    """
    Insert a tag before the trailing _e#### part.

    Example:
      sl8olre_p089r080_d2025060720260109_dlj_e32756
    + dlj-clear-ge80
    -> sl8olre_p089r080_d2025060720260109_dlj-clear-ge80_e32756
    """
    m = re.match(r"^(.*?)(?:_e(\d+))$", base_name)
    if not m:
        raise ValueError(f"Could not parse EPSG suffix from base name: {base_name}")

    prefix = m.group(1)
    epsg = m.group(2)
    return f"{prefix}-{tag}_e{epsg}"

@dataclass(frozen=True)
class MaskVectorOutputs:
    """Container for run-scoped local and S3 mask/vector outputs."""
    strong_mask_local: Path
    clear_mask_local: Path
    strong_mask_s3: str
    clear_mask_s3: str
    strong_shp_s3_prefix: str
    clear_shp_s3_prefix: str

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
        gdf = gdf.loc[gdf["area_ha"] >= float(min_area_ha)].copy()

    # try to clean invalid geometry (buffer(0) hack)
    try:
        gdf["geometry"] = gdf["geometry"].buffer(0)
        gdf = gdf.loc[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
    except Exception:
        # ignore if it fails
        pass

    return gdf


def _write_shapefile_set(gdf: gpd.GeoDataFrame, out_dir: Path, stem: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    shp_path = out_dir / f"{stem}.shp"
    # ESRI Shapefile driver creates the sidecar files automatically
    gdf.to_file(shp_path, driver="ESRI Shapefile")

    # Also write a single-file GeoPackage for easier downstream use.
    gpkg_path = out_dir / f"{stem}.gpkg"
    try:
        try:
            import fiona  # type: ignore

            supported = getattr(fiona, "supported_drivers", {}) or {}
            if "GPKG" not in supported:
                raise RuntimeError(
                    "Fiona/GDAL in this environment does not advertise the 'GPKG' driver. "
                    "(Often caused by missing GDAL SQLite support.)"
                )
        except Exception:
            # If Fiona isn't installed or doesn't expose supported_drivers, we'll
            # still attempt the write and report any failure.
            pass

        try:
            gpkg_path.unlink(missing_ok=True)
        except Exception:
            pass

        # Use a short/stable layer name for maximum compatibility.
        # (Very long stems can produce awkward layer/table names in some tooling.)
        layer_name = "polygons"

        # Some Fiona/GeoPandas versions require/accept `layer`, others ignore it.
        try:
            gdf.to_file(gpkg_path, driver="GPKG", layer=layer_name)
        except TypeError:
            gdf.to_file(gpkg_path, driver="GPKG")

        # Basic sanity check: ensure it wrote something and is readable.
        try:
            if gpkg_path.exists() and gpkg_path.stat().st_size == 0:
                raise RuntimeError("GeoPackage written with zero size")
        except Exception:
            raise

        try:
            # If this fails, the file is likely corrupt or the driver is missing.
            _ = gpd.read_file(gpkg_path, layer=layer_name)
        except Exception as e:
            raise RuntimeError(f"GeoPackage validation read failed: {e}")
    except Exception as e:
        try:
            gpkg_path.unlink(missing_ok=True)
        except Exception:
            pass
        print(
            f"[WARN] Failed to write a valid GeoPackage: {gpkg_path} ({e}). "
            "Shapefile outputs were still created."
        )

    # Bundle into a single zip for easy download from S3/ArcGIS cloud connections.
    try:
        import zipfile

        zip_path = out_dir / f"{stem}.zip"
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass

        members = [p for p in sorted(out_dir.glob(f"{stem}.*")) if p.is_file()]
        if members:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for p in members:
                    # store with just the filename (not full path)
                    zf.write(p, arcname=p.name)
    except Exception as e:
        print(f"[WARN] Failed to create zip bundle for {stem}: {e}")

    return shp_path


def _upload_shapefile_folder(local_dir: Path, bucket: str, s3_prefix: str) -> None:
    # upload all expected shapefile components present in folder
    for p in sorted(local_dir.glob("*")):
        if p.is_file():
            # Avoid uploading transient sqlite sidecars (rare, but can exist).
            if p.name.lower().endswith((".gpkg-wal", ".gpkg-shm", ".gpkg-journal")):
                continue
            key = f"{s3_prefix.rstrip('/')}/{p.name}"
            upload_file_to_s3(str(p), bucket=bucket, key=key)

def _output_base_from_dlj(dljmz_cog_local: Path) -> str:
    """Use the DLJ filename stem as the base for downstream masks/vectors."""
    return Path(dljmz_cog_local).stem

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
    """Create strong/clear masks and shapefiles for this run, then upload to S3.

    S3 destinations:
      {s3_prefix}/tiles/{tile}/outputs/{run_tag}/masks
      {s3_prefix}/tiles/{tile}/outputs/{run_tag}/vectors
    """
    tile = tile.lower().strip()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    masks_s3_dir = f"{s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}/masks"
    vec_s3_dir   = f"{s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}/vectors"
    masks_dir = work_dir / "masks"
    vectors_dir = work_dir / "vectors"

    masks_dir.mkdir(parents=True, exist_ok=True)
    vectors_dir.mkdir(parents=True, exist_ok=True)

    base_name = _output_base_from_dlj(dljmz_cog_local)

    strong_core = _insert_tag_before_epsg(
        base_name,
        f"dlj-strong-ge{int(strong_threshold):02d}",
    )
    clear_core = _insert_tag_before_epsg(
        base_name,
        f"dlj-clear-ge{int(clear_threshold):02d}",
    )

    strong_mask_stem = strong_core
    clear_mask_stem  = clear_core

    strong_vec_stem = strong_core
    clear_vec_stem  = clear_core

    strong_mask_key = f"{masks_s3_dir}/{strong_mask_stem}.tif"
    clear_mask_key  = f"{masks_s3_dir}/{clear_mask_stem}.tif"

    strong_mask_raw = masks_dir / f"{strong_mask_stem}_raw.tif"
    clear_mask_raw  = masks_dir / f"{clear_mask_stem}_raw.tif"

    strong_mask_cog = masks_dir / f"{strong_mask_stem}.tif"
    clear_mask_cog  = masks_dir / f"{clear_mask_stem}.tif"

    strong_vec_dir = vectors_dir / "strong"
    clear_vec_dir  = vectors_dir / "clear"

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

    with rasterio.open(dljmz_cog_local) as src:
        band = 4 if src.count >= 4 else 1
        if src.count < 4:
            print(f"[WARN] dljmz has only {src.count} band(s); using band 1")

        arr = src.read(band)

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

    print(f"[INFO] strong pixels: {int(strong_u8.sum())}, clear pixels: {int(clear_u8.sum())}")

    mask_profile = profile.copy()
    mask_profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=0,              # mask nodata/background is 0
        compress="deflate",
        tiled=True,
    )

    with rasterio.open(str(strong_mask_raw), "w", **mask_profile) as dst:
        dst.write(strong_u8, 1)

    with rasterio.open(str(clear_mask_raw), "w", **mask_profile) as dst:
        dst.write(clear_u8, 1)

    if not strong_mask_raw.exists():
        raise FileNotFoundError(f"Strong raw mask not created: {strong_mask_raw}")
    if not clear_mask_raw.exists():
        raise FileNotFoundError(f"Clear raw mask not created: {clear_mask_raw}")

    to_cog(str(strong_mask_raw), str(strong_mask_cog), overwrite=True)
    to_cog(str(clear_mask_raw), str(clear_mask_cog), overwrite=True)

    upload_file_to_s3(str(strong_mask_cog), bucket=bucket, key=strong_mask_key)
    upload_file_to_s3(str(clear_mask_cog), bucket=bucket, key=clear_mask_key)

    # Polygonise & write shapefiles
    gdf_strong = _polygonise_mask(mask_u8=strong_u8, transform=transform, crs=crs, min_area_ha=float(min_area_ha))
    gdf_clear  = _polygonise_mask(mask_u8=clear_u8,  transform=transform, crs=crs, min_area_ha=float(min_area_ha))

    _write_shapefile_set(gdf_strong, strong_vec_dir, stem=strong_vec_stem)
    _write_shapefile_set(gdf_clear,  clear_vec_dir,  stem=clear_vec_stem)

    _upload_shapefile_folder(strong_vec_dir, bucket=bucket, s3_prefix=strong_vec_prefix)
    _upload_shapefile_folder(clear_vec_dir,  bucket=bucket, s3_prefix=clear_vec_prefix)

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

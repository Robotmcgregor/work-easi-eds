#!/usr/bin/env python
"""
Build minimal QLD-compatible files (db8 reflectance pair and dc4 NDVI timeseries)
from GA/EASI SR products using Normalized Difference Vegetation Index (NDVI).

Unlike the FC-based builder, this script:
  - Builds db8 stacks from SR multi-band composites (as before)
  - Computes NDVI from SR bands instead of reading FC files
  - Outputs dc4 images containing NDVI (scaled to 0-200 and stored as uint8)

EASI conventions supported:

SR (multi-band nbart composites)
    ls89sr_p104r072_20200611_nbart6m3.tif
    ls89sr_p104r072_20200611_nbart6m3_clr.tif

Legacy conventions are also supported:
    *_srb6.tif / *_srb7.tif composites
    *_B2.tif ... *_B7.tif single-band files

All outputs are written to:

    <out-root>/<scene>/

where:
    - out-root is provided via --out-root (e.g. /home/jovyan/scratch/eds/compat)
    - scene is the tile code (e.g. p104r072)
    - db8: lztmre_<scene>_<date>_db8mz.img
    - dc4: lztmre_<scene>_<date>_dc4mz.img (NDVI instead of FPC)
    - footprint: lztmna_<scene>_eall_dw1mz.img

NDVI Calculation:
  - NDVI = (NIR - RED) / (NIR + RED)
  - Uses SR bands: RED=B4 (band 3), NIR=B5 (band 4) in the db8 stack
  - Output scaled to [0, 200] as uint8 where NDVI range [-1, 1] maps to [0, 200]
  - Formula: ndvi_uint8 = uint8(100 + 100 * NDVI)

Example (EASI with SR timeseries):

  python easi_slats_compat_builder_sr_ndvi.py \\
      --tile p104r072 \\
      --out-root /home/jovyan/scratch/eds/compat \\
      --sr-dir /home/jovyan/scratch/eds/tiles/p104r072/sr/2020/202006 \\
      --sr-date 20200611 \\
      --sr-dir /home/jovyan/scratch/eds/tiles/p104r072/sr/2023/202306 \\
      --sr-date 20230611

This is designed to be called from the EASI master pipeline script with --sr-mode=ndvi.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from osgeo import gdal
import numpy as np


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _find_band_file(dir_or_pattern: str, band_tag: str) -> str:
    """
    band_tag like B2 or srb2; look for both patterns in .tif/.tiff.

    Used only for legacy per-band stacks; EASI nbart composites will usually be
    handled via the COMPOSITE path logic instead.
    """
    if os.path.isdir(dir_or_pattern):
        base = band_tag.lower()
        alts: List[str] = []
        if base.startswith("b") and len(base) >= 2 and base[1].isdigit():
            alts = [base, "srb" + base[1:]]
        elif base.startswith("srb"):
            alts = [base, "b" + base[3:]]
        else:
            alts = [base]

        pats: List[str] = []
        for a in alts:
            pats.append(os.path.join(dir_or_pattern, f"*_{a}*.tif"))
            pats.append(os.path.join(dir_or_pattern, f"*_{a}*.tiff"))
            pats.append(os.path.join(dir_or_pattern, f"*{a}*.tif"))
            pats.append(os.path.join(dir_or_pattern, f"*{a}*.tiff"))

        for p in pats:
            hits = glob.glob(p)
            if hits:
                return hits[0]
        raise FileNotFoundError(f"No file for {band_tag} in {dir_or_pattern}")
    else:
        hits = glob.glob(dir_or_pattern)
        if hits:
            return hits[0]
        raise FileNotFoundError(f"No file matching pattern: {dir_or_pattern}")


def _stack_sr(
    date_tag: str,
    scene: str,
    band_sources: Dict[str, str],
    out_scene_dir: Path,
) -> str:
    """
    Create db8 stack from either:
      - a multi-band composite (EASI *_nbart6m*.tif or legacy *_srb6/_srb7.tif), or
      - single-band files (B2..B7).

    band_sources:
      - If key "COMPOSITE" exists, it will be used directly and all bands copied.
      - Else, if keys contain B2..B7, those files will be stacked in order.
    """
    # Order for legacy single-bands
    order = ["B2", "B3", "B4", "B5", "B6", "B7"]
    composite_path: Optional[str] = band_sources.get("COMPOSITE")

    out_name = f"lztmre_{scene}_{date_tag}_db8mz.img"
    out_path = out_scene_dir / out_name
    _ensure_dir(out_scene_dir)

    if composite_path:
        ds = gdal.Open(composite_path, gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError(f"Cannot open composite: {composite_path}")
        xsize, ysize = ds.RasterXSize, ds.RasterYSize
        n_bands = ds.RasterCount
        geotrans = ds.GetGeoTransform(can_return_null=True)
        proj = ds.GetProjection()

        drv = gdal.GetDriverByName("ENVI")
        out = drv.Create(str(out_path), xsize, ysize, n_bands, gdal.GDT_Int16)
        if geotrans:
            out.SetGeoTransform(geotrans)
        if proj:
            out.SetProjection(proj)

        for i in range(1, n_bands + 1):
            in_band = ds.GetRasterBand(i)
            out_band = out.GetRasterBand(i)
            out_band.WriteArray(in_band.ReadAsArray())

        out.FlushCache()
        del out
        del ds
        return str(out_path)

    files = [band_sources[b] for b in order if b in band_sources]
    if len(files) < 4:
        raise SystemExit(f"Need at least B2,B3,B4,B5; got {files}")

    ds0 = gdal.Open(files[0], gdal.GA_ReadOnly)
    xsize, ysize = ds0.RasterXSize, ds0.RasterYSize
    geotrans = ds0.GetGeoTransform(can_return_null=True)
    proj = ds0.GetProjection()

    drv = gdal.GetDriverByName("ENVI")
    out = drv.Create(str(out_path), xsize, ysize, len(files), gdal.GDT_Int16)
    if geotrans:
        out.SetGeoTransform(geotrans)
    if proj:
        out.SetProjection(proj)

    for i, f in enumerate(files, start=1):
        ds = gdal.Open(f, gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError(f"Cannot open {f}")
        band = ds.GetRasterBand(1)
        out_band = out.GetRasterBand(i)
        out_band.WriteArray(band.ReadAsArray())
        ds = None

    out.FlushCache()
    del out
    del ds0
    return str(out_path)


def _compute_ndvi_from_sr(
    sr_file: str,
    nodata: Optional[float] = None,
) -> np.ndarray:
    """
    Compute NDVI from SR db8 stack.
    
    NDVI = (NIR - RED) / (NIR + RED)
    
    SR band order in db8: B2, B3, B4, B5, B6, B7
      - B4 = RED (index 2)
      - B5 = NIR (index 3)
    
    Output is scaled to [0, 200] as uint8:
      - NDVI range [-1, 1] -> [0, 200]
      - Formula: output = uint8(100 + 100 * NDVI)
    
    Pixels where nodata or where RED + NIR == 0 are set to 0.
    """
    ds = gdal.Open(sr_file, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open SR file: {sr_file}")
    
    if ds.RasterCount < 5:
        raise RuntimeError(f"SR file must have >= 5 bands; got {ds.RasterCount}")
    
    # Read B4 (RED, index 2) and B5 (NIR, index 3)
    red_band = ds.GetRasterBand(3)  # B4 is the 3rd band in db8
    nir_band = ds.GetRasterBand(4)  # B5 is the 4th band in db8
    
    red = red_band.ReadAsArray().astype(np.float32)
    nir = nir_band.ReadAsArray().astype(np.float32)
    
    # Determine nodata value if not provided
    if nodata is None:
        nodata_val = red_band.GetNoDataValue()
    else:
        nodata_val = nodata
    
    # Compute NDVI
    denominator = nir + red
    
    # Build a valid mask: exclude nodata and zero-denominator pixels
    valid = np.ones_like(red, dtype=bool)
    if nodata_val is not None:
        valid = (red != nodata_val) & (nir != nodata_val)
    valid = valid & (denominator != 0.0)
    
    # Compute NDVI
    ndvi = np.zeros_like(red)
    ndvi[valid] = (nir[valid] - red[valid]) / denominator[valid]
    
    # Scale NDVI from [-1, 1] to [0, 200]
    # Formula: output = 100 + 100 * NDVI
    ndvi_scaled = np.clip(100.0 + 100.0 * ndvi, 0.0, 200.0)
    ndvi_uint8 = np.round(ndvi_scaled).astype(np.uint8)
    
    # Set invalid pixels to 0 (nodata)
    ndvi_uint8[~valid] = 0
    
    ds = None
    return ndvi_uint8


def _write_ndvi_dc4(
    date_tag: str,
    scene: str,
    sr_file: str,
    out_scene_dir: Path,
) -> str:
    """
    Compute NDVI from an SR db8 file and write a SLATS-compatible dc4 image.

    The output naming convention is:

        lztmre_<scene>_<date>_dc4mz.img

    where:
      - <scene> is the tile (e.g. p104r072)
      - <date>  is the YYYYMMDD date tag (e.g. 20200611)
    """
    # Open the SR file to get georeferencing
    ds = gdal.Open(sr_file, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open SR file: {sr_file}")

    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    geotrans = ds.GetGeoTransform(can_return_null=True)
    proj = ds.GetProjection()
    
    ds = None

    # Compute NDVI from the SR file
    ndvi_data = _compute_ndvi_from_sr(sr_file)

    # Build the output filename and ensure the scene directory exists
    out_name = f"lztmre_{scene}_{date_tag}_dc4mz.img"
    out_path = out_scene_dir / out_name
    _ensure_dir(out_scene_dir)

    # Create a new ENVI raster with one band, using 8-bit pixels.
    # This will store NDVI values (0-200 representing NDVI -1 to 1).
    drv = gdal.GetDriverByName("ENVI")
    out = drv.Create(str(out_path), xsize, ysize, 1, gdal.GDT_Byte)

    # Copy georeferencing so the output lines up with other products
    if geotrans:
        out.SetGeoTransform(geotrans)
    if proj:
        out.SetProjection(proj)

    # Write the NDVI data into the output dc4 file
    out_band = out.GetRasterBand(1)
    out_band.WriteArray(ndvi_data)

    # Use 0 as nodata (consistent with the rest of the compat products)
    out_band.SetNoDataValue(0)
    out.FlushCache()

    # Explicitly close datasets to ensure they are written to disk
    del out

    # Return the path so callers can log/track what was created
    return str(out_path)


def _ensure_footprint(scene: str, template_img: str, out_scene_dir: Path) -> str:
    """
    Ensure a simple footprint exists:

        lztmna_<scene>_eall_dw1mz.img

    Written into out_scene_dir, using template_img for size/projection.
    """
    fp_name = f"lztmna_{scene}_eall_dw1mz.img"
    fp_path = out_scene_dir / fp_name
    if fp_path.exists():
        return str(fp_path)

    ds = gdal.Open(template_img, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open template: {template_img}")

    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    geotrans = ds.GetGeoTransform(can_return_null=True)
    proj = ds.GetProjection()

    drv = gdal.GetDriverByName("ENVI")
    out = drv.Create(str(fp_path), xsize, ysize, 1, gdal.GDT_Byte)
    if geotrans:
        out.SetGeoTransform(geotrans)
    if proj:
        out.SetProjection(proj)

    band = out.GetRasterBand(1)
    band.Fill(1)
    band.SetNoDataValue(0)
    out.FlushCache()

    del out
    del ds
    return str(fp_path)


def _extract_date_from_path(p: str) -> str:
    m = re.search(r"(19|20)\d{6}", os.path.basename(p))
    if not m:
        raise ValueError(f"Cannot parse date from {p}")
    return m.group(0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build SLATS-compatible db8/dc4 files from GA/EASI SR with NDVI timeseries"
    )
    ap.add_argument(
        "--tile",
        required=True,
        help="Scene code like p090r084 or p104r072",
    )
    ap.add_argument(
        "--out-root",
        required=True,
        help="Base output root, e.g. /home/jovyan/scratch/eds/compat",
    )
    ap.add_argument(
        "--sr-date",
        action="append",
        help="SR date tag (YYYYMMDD) to build db8 for; repeat per --sr-dir",
    )
    ap.add_argument(
        "--sr-dir",
        action="append",
        help=(
            "Directory or composite per SR date. "
            "Can be:\n"
            "  - directory containing *_nbart6m*.tif / *_srb6/_srb7.tif / *_B2*.tif etc.\n"
            "  - direct path to *_nbart6m*.tif / *_srb6/_srb7.tif"
        ),
    )

    args = ap.parse_args(argv)

    if not args.sr_dir or len(args.sr_dir) < 1:
        raise SystemExit("Provide at least one --sr-dir (start/end, etc.)")

    # If sr-date not supplied, infer from path names
    if not args.sr_date or len(args.sr_date) != len(args.sr_dir):
        args.sr_date = [_extract_date_from_path(d) for d in args.sr_dir]

    scene = args.tile
    out_root = Path(args.out_root)
    out_scene_dir = out_root / scene
    _ensure_dir(out_scene_dir)

    # ------------------------------------------------------------------
    # Build db8 from SR inputs and dc4 from NDVI
    # ------------------------------------------------------------------
    built_db8: List[str] = []
    built_dc4: List[str] = []
    
    for d_tag, ddir in zip(args.sr_date, args.sr_dir):
        bands: Dict[str, str] = {}

        # Case 1: direct composite file (EASI nbart or legacy srb)
        if os.path.isfile(ddir):
            fname = os.path.basename(ddir).lower()
            if re.search(r"_nbart6m\d+(_clr)?\.tif$", fname) or re.search(
                r"_srb[67]\.tif$", fname
            ):
                bands["COMPOSITE"] = ddir
            else:
                # Treat as pattern / single-band style; try to find B2..B7 from here
                for b in ["B2", "B3", "B4", "B5", "B6", "B7"]:
                    try:
                        bands[b] = _find_band_file(ddir, b)
                    except Exception:
                        pass

        # Case 2: directory – search for composites first, then per-band
        elif os.path.isdir(ddir):
            comp_hits: List[str] = []
            # EASI nbart6m composites
            for pat in ("*_nbart6m*.tif", "*_nbart6m*.tiff"):
                comp_hits.extend(glob.glob(os.path.join(ddir, pat)))
            # Legacy composite patterns
            for pat in ("*_srb7.tif", "*_srb6.tif", "*_srb7.tiff", "*_srb6.tiff"):
                comp_hits.extend(glob.glob(os.path.join(ddir, pat)))

            if comp_hits:
                bands["COMPOSITE"] = sorted(comp_hits)[0]
            else:
                # Fallback to single-band files
                for b in ["B2", "B3", "B4", "B5", "B6", "B7"]:
                    try:
                        bands[b] = _find_band_file(ddir, b)
                    except Exception:
                        pass
        else:
            # Treat as pattern/glob
            for b in ["B2", "B3", "B4", "B5", "B6", "B7"]:
                try:
                    bands[b] = _find_band_file(ddir, b)
                except Exception:
                    pass

        # Build db8 from SR
        out_db8 = _stack_sr(d_tag, scene, bands, out_scene_dir)
        print(f"Built db8: {out_db8}")
        built_db8.append(out_db8)
        
        # Build dc4 from NDVI computed from SR
        out_dc4 = _write_ndvi_dc4(d_tag, scene, out_db8, out_scene_dir)
        print(f"Built dc4 (NDVI): {out_dc4}")
        built_dc4.append(out_dc4)

    # Ensure footprint
    if built_db8:
        fp = _ensure_footprint(scene, built_db8[0], out_scene_dir)
        print(f"Footprint: {fp}")

    print(f"\n[OK] Built {len(built_db8)} db8 and {len(built_dc4)} NDVI dc4 files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""
Build minimal QLD-compatible files (db8 reflectance pair and dc4 FPC/FC timeseries)
from GA/EASI SR and FC products.

EASI conventions supported:

SR (multi-band nbart composites)
    ls89sr_p104r072_20200611_nbart6m3.tif
    ls89sr_p104r072_20200611_nbart6m3_clr.tif

FC (fractional cover)
    galsfc3_p104r072_20200611_fcm3.tif
    galsfc3_p104r072_20200611_fcm3_clr.tif

Legacy conventions are also supported:
    *_srb6.tif / *_srb7.tif composites
    *_B2.tif ... *_B7.tif single-band files
    *_fc3ms.tif / *_fc3ms_clr.tif

All outputs are written to:

    <out-root>/<scene>/

where:
    - out-root is provided via --out-root (e.g. /home/jovyan/scratch/eds/compat)
    - scene is the tile code (e.g. p104r072)
    - db8: lztmre_<scene>_<date>_db8mz.img
    - dc4: lztmre_<scene>_<date>_dc4mz.img
    - footprint: lztmna_<scene>_eall_dw1mz.img

Example (EASI):

  python easi_slats_compat_builder.py \
      --tile p104r072 \
      --out-root /home/jovyan/scratch/eds/compat \
      --sr-dir /home/jovyan/scratch/eds/tiles/p104r072/sr/2020/202006 \
      --sr-date 20200611 \
      --sr-dir /home/jovyan/scratch/eds/tiles/p104r072/sr/2023/202306 \
      --sr-date 20230611 \
      --fc "/home/jovyan/scratch/eds/tiles/p104r072/fc/**/galsfc3_p104r072_*_fcm3*.tif" \
      --fc-only-clr

This is designed to be called from the EASI master pipeline script.
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
        ds0 = gdal.Open(composite_path, gdal.GA_ReadOnly)
        if ds0 is None:
            raise RuntimeError(f"Cannot open composite SR: {composite_path}")
        xsize, ysize = ds0.RasterXSize, ds0.RasterYSize
        geotrans = ds0.GetGeoTransform(can_return_null=True)
        proj = ds0.GetProjection()

        drv = gdal.GetDriverByName("ENVI")
        out = drv.Create(str(out_path), xsize, ysize, ds0.RasterCount, gdal.GDT_Int16)
        if geotrans:
            out.SetGeoTransform(geotrans)
        if proj:
            out.SetProjection(proj)

        for i in range(1, ds0.RasterCount + 1):
            band = ds0.GetRasterBand(i)
            data = band.ReadAsArray()
            out_band = out.GetRasterBand(i)
            out_band.WriteArray(data)
            out_band.SetNoDataValue(0)

        out.FlushCache()
        del out
        del ds0
        return str(out_path)

    files = [band_sources[b] for b in order if b in band_sources]
    if len(files) < 4:
        raise RuntimeError(
            "Need at least 4 SR bands (B2,B3,B5,B6) for index computation, "
            "or provide a multi-band *_nbart6m*.tif / *_srb6/_srb7.tif composite"
        )

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
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray()
        out_band = out.GetRasterBand(i)
        out_band.WriteArray(data)
        out_band.SetNoDataValue(0)
        del ds

    out.FlushCache()
    del out
    del ds0
    return str(out_path)


# def _convert_fc_to_fpc(
#     arr: np.ndarray,
#     nodata: Optional[float],
#     k: float,
#     n: float,
# ) -> np.ndarray:
#     """Convert FC green to FPC using: FPC = 100 * (1 - exp(-k * FC^n))."""
#     arrf = arr.astype(np.float32)
#     if nodata is not None:
#         mask = arrf == nodata
#     else:
#         mask = np.zeros_like(arrf, dtype=bool)

#     fpc = 100.0 * (1.0 - np.exp(-(k * np.power(arrf, n))))
#     fpc = np.clip(fpc, 0.0, 100.0)

#     if nodata is not None:
#         fpc = np.where(mask, 0.0, fpc)


#     return np.round(fpc).astype(np.uint8)
def _convert_fc_to_fpc(
    arr: np.ndarray,
    nodata: Optional[float],
    k: float,
    n: float,
) -> np.ndarray:
    """
    Convert Fractional Cover (FC) to Foliage Projective Cover (FPC)
    using the empirical relationship:

        FPC = 100 * (1 - exp(-k * FC^n))

    Where:
      - FC is the fractional cover input (0–100 style values).
      - k and n are model parameters that control curve shape.
      - Output is scaled to 0–100 and stored as whole numbers (uint8).

    Notes:
      - Pixels marked as 'nodata' in the original FC image are preserved
        as 0 in the FPC output (so they do not appear as valid vegetation).
    """

    # Convert the input FC array to floating point for the maths
    arrf = arr.astype(np.float32)

    # Build a mask for nodata pixels, if a nodata value is supplied.
    # These pixels will later be forced to 0 in the FPC image.
    if nodata is not None:
        mask = arrf == nodata
    else:
        mask = np.zeros_like(arrf, dtype=bool)

    # Apply the empirical FC -> FPC relationship
    # The exponential function gives us a curve that rises quickly at low FC
    # and then flattens out at high FC values.
    fpc = 100.0 * (1.0 - np.exp(-(k * np.power(arrf, n))))

    # Ensure FPC is bounded between 0 and 100
    fpc = np.clip(fpc, 0.0, 100.0)

    # Restore nodata pixels back to 0 so they are clearly "no data"
    if nodata is not None:
        fpc = np.where(mask, 0.0, fpc)

    # Round to whole numbers and store as 8-bit integers (saves space
    # and matches the legacy format expectations).
    return np.round(fpc).astype(np.uint8)


# def _write_fc(
#     date_tag: str,
#     scene: str,
#     fc_file: str,
#     out_scene_dir: Path,
#     *,
#     convert_to_fpc: bool = False,
#     k: float = 0.000435,
#     n: float = 1.909,
#     fc_nodata: Optional[float] = None,
# ) -> str:
#     """Write dc4 image (FC or FPC) from a single-band FC input."""
#     ds = gdal.Open(fc_file, gdal.GA_ReadOnly)
#     if ds is None:
#         raise RuntimeError(f"Cannot open FC file: {fc_file}")

#     xsize, ysize = ds.RasterXSize, ds.RasterYSize
#     geotrans = ds.GetGeoTransform(can_return_null=True)
#     proj = ds.GetProjection()

#     out_name = f"lztmre_{scene}_{date_tag}_dc4mz.img"
#     out_path = out_scene_dir / out_name
#     _ensure_dir(out_scene_dir)

#     drv = gdal.GetDriverByName("ENVI")
#     out = drv.Create(str(out_path), xsize, ysize, 1, gdal.GDT_Byte)
#     if geotrans:
#         out.SetGeoTransform(geotrans)
#     if proj:
#         out.SetProjection(proj)

#     band = ds.GetRasterBand(1)
#     data = band.ReadAsArray()

#     if convert_to_fpc:
#         nd = fc_nodata if fc_nodata is not None else band.GetNoDataValue()
#         data = _convert_fc_to_fpc(data, nd, k, n)

#     out_band = out.GetRasterBand(1)
#     out_band.WriteArray(data)
#     out_band.SetNoDataValue(0)
#     out.FlushCache()

#     del out
#     del ds
#     return str(out_path)


def _write_fc(
    date_tag: str,
    scene: str,
    fc_file: str,
    out_scene_dir: Path,
    *,
    convert_to_fpc: bool = False,
    k: float = 0.000435,
    n: float = 1.909,
    fc_nodata: Optional[float] = None,
) -> str:
    """
    Read a single-band Fractional Cover (FC) image and write a
    SLATS-compatible dc4 image for this date.

    Depending on options, the dc4 image can contain:
      - raw FC values, or
      - converted FPC values (if convert_to_fpc=True).

    The output naming convention is:

        lztmre_<scene>_<date>_dc4mz.img

    where:
      - <scene> is the tile (e.g. p104r072)
      - <date>  is the YYYYMMDD date tag (e.g. 20200611)
    """

    # Open the input FC raster for reading
    ds = gdal.Open(fc_file, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open FC file: {fc_file}")

    # Get basic spatial info so we can create an aligned output:
    # - width/height of the image
    # - georeferencing (position on the Earth)
    # - projection (coordinate system)
    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    geotrans = ds.GetGeoTransform(can_return_null=True)
    proj = ds.GetProjection()

    # Build the output filename and ensure the scene directory exists
    out_name = f"lztmre_{scene}_{date_tag}_dc4mz.img"
    out_path = out_scene_dir / out_name
    _ensure_dir(out_scene_dir)

    # Create a new ENVI raster with one band, using 8-bit pixels.
    # This will store either FC or FPC values.
    drv = gdal.GetDriverByName("ENVI")
    out = drv.Create(str(out_path), xsize, ysize, 1, gdal.GDT_Byte)

    # Copy georeferencing so the output lines up with other products
    if geotrans:
        out.SetGeoTransform(geotrans)
    if proj:
        out.SetProjection(proj)

    # Read the single band of FC data from the input
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray()

    # Optionally convert FC -> FPC before writing
    if convert_to_fpc:
        # If a nodata override is supplied, use that; otherwise use band nodata
        nd = fc_nodata if fc_nodata is not None else band.GetNoDataValue()

        # Apply the empirical conversion to FPC
        data = _convert_fc_to_fpc(data, nd, k, n)

    # Write the (possibly converted) data into the output dc4 file
    out_band = out.GetRasterBand(1)
    out_band.WriteArray(data)

    # Use 0 as nodata (consistent with the rest of the compat products)
    out_band.SetNoDataValue(0)
    out.FlushCache()

    # Explicitly close datasets to ensure they are written to disk
    del out
    del ds

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
        raise RuntimeError(f"Cannot open template for footprint: {template_img}")

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
        raise ValueError(f"Cannot find YYYYMMDD in {p}")
    return m.group(0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build SLATS-compatible db8/dc4 files from GA/EASI SR/FC"
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
    ap.add_argument(
        "--fc",
        action="append",
        help=(
            "Paths or globs to FC green/FPC files to include in timeseries "
            "(supports ** for recursive). Accepts *_fc3ms*.tif and *_fcm*.tif."
        ),
    )
    ap.add_argument(
        "--fc-list",
        help="Optional text file with one FC filepath per line to include",
    )
    ap.add_argument(
        "--fc-only-clr",
        action="store_true",
        help="Use only masked FC files (*_fc3ms_clr.tif, *_fcm*_clr.tif); ignore unmasked ones",
    )
    ap.add_argument(
        "--fc-prefer-clr",
        action="store_true",
        help=(
            "Prefer clr variant when both clr and non-clr exist for same date. "
            "If neither --fc-only-clr nor this flag is provided, default is to "
            "still prefer clr where available."
        ),
    )

    # FC->FPC conversion options
    ap.add_argument(
        "--fc-convert-to-fpc",
        action="store_true",
        help=(
            "Convert FC green to FPC using FPC=100*(1-exp(-k*FC^n)) before writing dc4"
        ),
    )
    ap.add_argument(
        "--fc-k",
        type=float,
        default=0.000435,
        help="k parameter for FC->FPC conversion (default 0.000435)",
    )
    ap.add_argument(
        "--fc-n",
        type=float,
        default=1.909,
        help="n parameter for FC->FPC conversion (default 1.909)",
    )
    ap.add_argument(
        "--fc-nodata",
        type=float,
        default=None,
        help="Override nodata value for FC input; defaults to band nodata if present",
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
    # 1. Build db8 from SR inputs
    # ------------------------------------------------------------------
    built_db8: List[str] = []
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

        out_db8 = _stack_sr(d_tag, scene, bands, out_scene_dir)
        print(out_db8)
        built_db8.append(out_db8)

    # # ------------------------------------------------------------------
    # # 2. Build dc4 from FC inputs
    # # ------------------------------------------------------------------
    # fc_files: List[str] = []
    # if args.fc:
    #     for pat in args.fc:
    #         hits = glob.glob(pat, recursive=True)
    #         fc_files.extend(hits)

    # if args.fc_list:
    #     list_path = Path(args.fc_list)
    #     if list_path.exists():
    #         with list_path.open("r", encoding="utf-8") as f:
    #             for line in f:
    #                 p = line.strip().strip('"')
    #                 if p:
    #                     fc_files.append(p)
    #     else:
    #         print(f"[WARN] --fc-list not found: {list_path}")

    # # De-duplicate while preserving order
    # seen: set[str] = set()
    # fc_files = [x for x in fc_files if not (x in seen or seen.add(x))]
    # print("fc_files")
    # if fc_files:
    #     # Optionally restrict to _clr variants only
    #     if args.fc_only_clr:
    #         def is_clr(path: str) -> bool:
    #             name = os.path.basename(path).lower()
    #             return "_clr.tif" in name
    #         fc_files = [f for f in fc_files if is_clr(f)]
    #         print(f"[INFO] --fc-only-clr active; using {len(fc_files)} masked FC files")

    #     # Group by date tag and pick one per date (preferring clr variants)
    #     grouped: Dict[str, List[str]] = {}
    #     for f in fc_files:
    #         try:
    #             d = _extract_date_from_path(f)
    #         except Exception:
    #             continue
    #         grouped.setdefault(d, []).append(f)

    #     selected: List[str] = []
    #     for d, flist in grouped.items():
    #         clr = [f for f in flist if "_clr.tif" in os.path.basename(f).lower()]
    #         non_clr = [f for f in flist if f not in clr]

    #         prefer_clr = args.fc_prefer_clr or not args.fc_only_clr
    #         if clr and prefer_clr:
    #             chosen = sorted(clr)[0]
    #         elif non_clr:
    #             chosen = sorted(non_clr)[0]
    #         elif clr:
    #             chosen = sorted(clr)[0]
    #         else:
    #             chosen = sorted(flist)[0]
    #         selected.append(chosen)

    #     if len(selected) != len(fc_files):
    #         print(
    #             f"[INFO] Deduplicated FC inputs {len(fc_files)} -> {len(selected)} "
    #             f"(preferring clr where available)"
    #         )
    #     fc_files = selected

    #     for fc_file in fc_files:
    #         try:
    #             dtag = _extract_date_from_path(fc_file)
    #             out_dc4 = _write_fc(
    #                 dtag,
    #                 scene,
    #                 fc_file,
    #                 out_scene_dir,
    #                 convert_to_fpc=args.fc_convert_to_fpc,
    #                 k=args.fc_k,
    #                 n=args.fc_n,
    #                 fc_nodata=args.fc_nodata,
    #             )
    #             print(out_dc4)
    #         except Exception as e:
    #             print(f"[ERR] dc4 build failed for {fc_file}: {e}")

    # ------------------------------------------------------------------
    # 2. Build dc4 from FC inputs
    # ------------------------------------------------------------------
    fc_files: List[str] = []

    # Collect FC inputs from any --fc glob patterns supplied on the command line.
    # These can be:
    #   - legacy *_fc3ms*.tif
    #   - new EASI *_fcm*.tif
    if args.fc:
        for pat in args.fc:
            hits = glob.glob(pat, recursive=True)
            fc_files.extend(hits)

    # Optionally, also read FC paths from a text file (--fc-list),
    # one path per line.
    if args.fc_list:
        list_path = Path(args.fc_list)
        if list_path.exists():
            with list_path.open("r", encoding="utf-8") as f:
                for line in f:
                    p = line.strip().strip('"')
                    if p:
                        fc_files.append(p)
        else:
            print(f"[WARN] --fc-list not found: {list_path}")

    # Remove duplicates while preserving the original order.
    seen: set[str] = set()
    fc_files = [x for x in fc_files if not (x in seen or seen.add(x))]

    print("fc_files")
    if fc_files:
        # If the user requested "--fc-only-clr", restrict to the masked
        # versions of FC (those ending in "_clr.tif"). This enforces
        # cloud/mask usage.
        if args.fc_only_clr:

            def is_clr(path: str) -> bool:
                name = os.path.basename(path).lower()
                return "_clr.tif" in name

            fc_files = [f for f in fc_files if is_clr(f)]
            print(f"[INFO] --fc-only-clr active; using {len(fc_files)} masked FC files")

        # Group FC files by date (YYYYMMDD) extracted from their filenames.
        # For each date we then pick a single "best" file (prefer clr).
        grouped: Dict[str, List[str]] = {}
        for f in fc_files:
            try:
                d = _extract_date_from_path(f)
            except Exception:
                # If we can't find a date in the filename, skip this file.
                continue
            grouped.setdefault(d, []).append(f)

        selected: List[str] = []
        for d, flist in grouped.items():
            # Split into clr and non-clr variants for this date
            clr = [f for f in flist if "_clr.tif" in os.path.basename(f).lower()]
            non_clr = [f for f in flist if f not in clr]

            # Decide whether to prefer clr versions depending on flags.
            prefer_clr = args.fc_prefer_clr or not args.fc_only_clr

            if clr and prefer_clr:
                chosen = sorted(clr)[0]
            elif non_clr:
                chosen = sorted(non_clr)[0]
            elif clr:
                chosen = sorted(clr)[0]
            else:
                chosen = sorted(flist)[0]

            selected.append(chosen)

        # If we reduced multiple files per date down to one per date,
        # let the user know.
        if len(selected) != len(fc_files):
            print(
                f"[INFO] Deduplicated FC inputs {len(fc_files)} -> {len(selected)}"
                f"(preferring clr where available)"
            )
        fc_files = selected

        # For each chosen FC file:
        #   - extract the date from the filename
        #   - write a dc4 image (FC or FPC) for that date
        for fc_file in fc_files:
            try:
                dtag = _extract_date_from_path(fc_file)
                out_dc4 = _write_fc(
                    dtag,
                    scene,
                    fc_file,
                    out_scene_dir,
                    convert_to_fpc=args.fc_convert_to_fpc,
                    k=args.fc_k,
                    n=args.fc_n,
                    fc_nodata=args.fc_nodata,
                )
                print(out_dc4)
            except Exception as e:
                print(f"[ERR] dc4 build failed for {fc_file}: {e}")

    # ------------------------------------------------------------------
    # 3. Ensure footprint exists
    # ------------------------------------------------------------------
    sample_template: Optional[str] = None
    if built_db8:
        sample_template = built_db8[0]
    else:
        # Try any dc4 in the scene dir
        dc4_candidates = list(out_scene_dir.glob("*_dc4mz.img"))
        if dc4_candidates:
            sample_template = str(dc4_candidates[0])

    if sample_template:
        fp = _ensure_footprint(scene, sample_template, out_scene_dir)
        print(fp)

    print(f"Compat build complete {sample_template}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

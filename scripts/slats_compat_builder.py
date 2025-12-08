#!/usr/bin/env python
"""
Build minimal QLD-compatible files (db8 reflectance pair and dc4 FPC timeseries) from GA SR and FC.

This script stacks SR bands (Blue, Green, Red, NIR, SWIR1, SWIR2) into an ENVI .img and writes FC green as dc4.
It also creates empty masks and a simple footprint. Filenames follow QLD conventions so the QLD script runs unchanged.

Inputs can be a local folder or S3 listing provided externally (download first).

Example (local):
  python scripts/slats_compat_builder.py \
    --tile p090r084 \
    --sr "data/source/p090r084/sr/*20150103*.tif" "data/source/p090r084/sr/*20160215*.tif" \
    --sr-bands B2=B2.tif B3=B3.tif B4=B4.tif B5=B5.tif B6=B6.tif B7=B7.tif \
    --fc "data/source/p090r084/fc/*2014*.tif" "data/source/p090r084/fc/*2013*.tif" \
    --out-root data/compat/files

You can also point --sr to directories (one per date) that contain band files matching *_B2*.tif etc.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import sys

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from osgeo import gdal
import numpy as np

from rsc.utils.metadb import stdProjFilename


def _find_band_file(dir_or_pattern: str, band_tag: str) -> str:
    # band_tag like B2 or srb2; look for both patterns in .tif/.tiff
    if os.path.isdir(dir_or_pattern):
        base = band_tag.lower()
        alts = []
        if base.startswith("b") and len(base) >= 2 and base[1].isdigit():
            alts = [base, "srb" + base[1:]]
        elif base.startswith("srb"):
            alts = [base, "b" + base[3:]]
        else:
            alts = [base]
        pats = []
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
    date_tag: str, scene: str, band_sources: Dict[str, str], out_dir: Path
) -> str:
    """Create db8 stack from either single-band files (B2..B7) or a multi-band *_srb6/_srb7 composite.

    band_sources:
      - If keys contain B2..B7, those files will be stacked in order.
      - Else if key 'COMPOSITE' exists, it will be used directly and all bands copied.
    """
    # Order: B2,B3,B4,B5,B6,B7
    order = ["B2", "B3", "B4", "B5", "B6", "B7"]
    composite_path: Optional[str] = band_sources.get("COMPOSITE")
    if composite_path:
        ds0 = gdal.Open(composite_path, gdal.GA_ReadOnly)
        if ds0 is None:
            raise RuntimeError(f"Cannot open composite SR: {composite_path}")
        xsize, ysize = ds0.RasterXSize, ds0.RasterYSize
        geotrans, proj = ds0.GetGeoTransform(can_return_null=True), ds0.GetProjection()
        out_name = f"lztmre_{scene}_{date_tag}_db8mz.img"
        out_path = Path(stdProjFilename(out_name))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        drv = gdal.GetDriverByName("ENVI")
        out = drv.Create(str(out_path), xsize, ysize, ds0.RasterCount, gdal.GDT_Int16)
        if geotrans:
            out.SetGeoTransform(geotrans)
        if proj:
            out.SetProjection(proj)
        for i in range(1, ds0.RasterCount + 1):
            band = ds0.GetRasterBand(i)
            data = band.ReadAsArray()
            out.GetRasterBand(i).WriteArray(data)
            out.GetRasterBand(i).SetNoDataValue(0)
        out.FlushCache()
        del out
        del ds0
        return str(out_path)

    files = [band_sources[b] for b in order if b in band_sources]
    if len(files) < 4:
        raise RuntimeError(
            "Need at least 4 SR bands (B2,B3,B5,B6) for index computation or provide a *_srb6/_srb7 composite"
        )
    # Open first for georef
    ds0 = gdal.Open(files[0], gdal.GA_ReadOnly)
    xsize, ysize = ds0.RasterXSize, ds0.RasterYSize
    geotrans, proj = ds0.GetGeoTransform(can_return_null=True), ds0.GetProjection()
    out_name = f"lztmre_{scene}_{date_tag}_db8mz.img"
    out_path = Path(stdProjFilename(out_name))
    out_path.parent.mkdir(parents=True, exist_ok=True)
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
        out.GetRasterBand(i).WriteArray(data)
        out.GetRasterBand(i).SetNoDataValue(0)
        del ds
    out.FlushCache()
    del out
    del ds0
    return str(out_path)


def _convert_fc_to_fpc(
    arr: np.ndarray, nodata: Optional[float], k: float, n: float
) -> np.ndarray:
    """Convert FC green to FPC using: FPC = 100 * (1 - exp(-k * FC^n)).

    - arr: FC green array (expected 0..100 or similar scale)
    - nodata: value to treat as nodata (kept as 0 in output), if None uses no explicit mask
    - k, n: conversion parameters
    Returns uint8 in [0,100].
    """
    arrf = arr.astype(np.float32)
    if nodata is not None:
        mask = arrf == nodata
    else:
        mask = np.zeros_like(arrf, dtype=bool)
    fpc = 100.0 * (1.0 - np.exp(-(k * np.power(arrf, n))))
    fpc = np.clip(fpc, 0.0, 100.0)
    # Set nodata to 0 for downstream normalisation (0 is treated as nodata later)
    if nodata is not None:
        fpc = np.where(mask, 0.0, fpc)
    return np.round(fpc).astype(np.uint8)


def _write_fc(
    date_tag: str,
    scene: str,
    fc_file: str,
    *,
    convert_to_fpc: bool = False,
    k: float = 0.000435,
    n: float = 1.909,
    fc_nodata: Optional[float] = None,
) -> str:
    ds = gdal.Open(fc_file, gdal.GA_ReadOnly)
    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    geotrans, proj = ds.GetGeoTransform(can_return_null=True), ds.GetProjection()
    out_name = f"lztmre_{scene}_{date_tag}_dc4mz.img"
    out_path = Path(stdProjFilename(out_name))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    drv = gdal.GetDriverByName("ENVI")
    out = drv.Create(str(out_path), xsize, ysize, 1, gdal.GDT_Byte)
    if geotrans:
        out.SetGeoTransform(geotrans)
    if proj:
        out.SetProjection(proj)
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray()
    # Optionally convert FC green to FPC before writing dc4
    if convert_to_fpc:
        # Use provided nodata override, else fall back to band nodata
        nd = fc_nodata if fc_nodata is not None else band.GetNoDataValue()
        data = _convert_fc_to_fpc(data, nd, k, n)
    # Write out (uint8). If not converted, data is written as-is; normalisation later handles scaling.
    out.GetRasterBand(1).WriteArray(data)
    out.GetRasterBand(1).SetNoDataValue(0)
    out.FlushCache()
    del out
    del ds
    return str(out_path)


def _ensure_footprint(scene: str, template_img: str) -> str:
    from osgeo import gdal
    from rsc.utils.metadb import stdProjFilename

    # footprint name: lztmna_<scene>_eall_dw1mz.img
    fp_name = f"lztmna_{scene}_eall_dw1mz.img"
    fp_path = Path(stdProjFilename(fp_name))
    if fp_path.exists():
        return str(fp_path)
    ds = gdal.Open(template_img, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Cannot open template image for footprint: {template_img}")
    xsize, ysize = ds.RasterXSize, ds.RasterYSize
    geotrans, proj = ds.GetGeoTransform(can_return_null=True), ds.GetProjection()
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
        description="Build SLATS-compatible db8/dc4 files from GA SR/FC"
    )
    ap.add_argument("--tile", required=True, help="Scene code like p090r084")
    ap.add_argument(
        "--sr-date",
        action="append",
        help="SR date tag (YYYYMMDD) to build db8 for; repeat twice for start/end",
    )
    ap.add_argument(
        "--sr-dir",
        action="append",
        help="Directory per SR date containing *_B2*.tif, *_B3*.tif, ...",
    )
    ap.add_argument(
        "--fc",
        action="append",
        help="Paths or globs to FC green files to include in timeseries (supports ** with recursive)",
    )
    ap.add_argument(
        "--fc-list", help="Optional text file with one FC filepath per line to include"
    )
    ap.add_argument(
        "--fc-only-clr",
        action="store_true",
        help="Use only masked FC files (*_fc3ms_clr.tif); ignore unmasked *_fc3ms.tif",
    )
    ap.add_argument(
        "--fc-prefer-clr",
        action="store_true",
        help="Prefer clr variant when both *_fc3ms.tif and *_fc3ms_clr.tif for same date exist (default if neither clr-only nor prefer flag supplied is to deduplicate picking clr).",
    )

    # FC-> FPC conversion options
    ap.add_argument(
        "--fc-convert-to-fpc",
        action="store_true",
        help="Convert FC green to FPC using FPC=100*(1-exp(-k*FC^n)) before writing dc4",
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

    if not args.sr_dir or len(args.sr_dir) < 2:
        raise SystemExit("Provide two --sr-dir directories (start/end)")
    if not args.sr_date or len(args.sr_date) != len(args.sr_dir):
        # infer dates from filenames
        args.sr_date = [_extract_date_from_path(d) for d in args.sr_dir]

    # Build db8 images
    built = []
    for d, ddir in zip(args.sr_date, args.sr_dir):
        bands = {}
        # Accept either a direct composite file path, or a directory containing one
        if os.path.isfile(ddir) and re.search(
            r"_srb[67]\.tif$", os.path.basename(ddir), re.IGNORECASE
        ):
            bands["COMPOSITE"] = ddir
        elif os.path.isdir(ddir):
            # Look for a composite inside the directory first
            comp_hits = []
            for pat in ("*_srb7.tif", "*_srb6.tif", "*_srb7.tiff", "*_srb6.tiff"):
                comp_hits.extend(glob.glob(os.path.join(ddir, pat)))
            if comp_hits:
                bands["COMPOSITE"] = sorted(comp_hits)[0]
            else:
                # Fall back to per-band files
                for b in ["B2", "B3", "B4", "B5", "B6", "B7"]:
                    try:
                        bands[b] = _find_band_file(ddir, b)
                    except Exception:
                        pass
        else:
            # Treat as a direct glob/pattern pointing to a single band
            for b in ["B2", "B3", "B4", "B5", "B6", "B7"]:
                try:
                    bands[b] = _find_band_file(ddir, b)
                except Exception:
                    pass
        out = _stack_sr(d, args.tile, bands, Path("."))
        print(out)
        built.append(out)

    # Build dc4 images from FC
    fc_files: List[str] = []
    if args.fc:
        for pat in args.fc:
            hits = glob.glob(pat, recursive=True)
            fc_files.extend(hits)
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
    # De-duplicate while preserving order
    seen = set()
    fc_files = [x for x in fc_files if not (x in seen or seen.add(x))]
    if fc_files:
        # Filter / deduplicate logic
        lower_map = {f.lower(): f for f in fc_files}
        if args.fc_only_clr:
            fc_files = [f for f in fc_files if f.lower().endswith("_fc3ms_clr.tif")]
            print(f"[INFO] --fc-only-clr active; using {len(fc_files)} masked FC files")
        else:
            # Group by date tag and prefer clr variant if present either by flag or default behaviour
            grouped = {}
            for f in fc_files:
                try:
                    d = _extract_date_from_path(f)
                except Exception:
                    continue
                grouped.setdefault(d, []).append(f)
            selected = []
            for d, flist in grouped.items():
                clr = [f for f in flist if f.lower().endswith("_fc3ms_clr.tif")]
                base = [
                    f
                    for f in flist
                    if f.lower().endswith("_fc3ms.tif")
                    and not f.lower().endswith("_fc3ms_clr.tif")
                ]
                if clr and (args.fc_prefer_clr or True):  # default prefer clr
                    selected.append(sorted(clr)[0])
                elif base:
                    selected.append(sorted(base)[0])
                else:
                    # fallback any
                    selected.append(sorted(flist)[0])
            if len(selected) != len(fc_files):
                print(
                    f"[INFO] Deduplicated FC inputs {len(fc_files)} -> {len(selected)} (preferring clr where available)"
                )
            fc_files = selected
        for fc_file in fc_files:
            try:
                dtag = _extract_date_from_path(fc_file)
                out = _write_fc(
                    dtag,
                    args.tile,
                    fc_file,
                    convert_to_fpc=args.fc_convert_to_fpc,
                    k=args.fc_k,
                    n=args.fc_n,
                    fc_nodata=args.fc_nodata,
                )
                print(out)
            except Exception as e:
                print(f"[ERR] dc4 build failed for {fc_file}: {e}")

    # Ensure footprint exists using the first available product as template
    sample_template = None
    if built:
        sample_template = built[0]
    else:
        # Try any dc4 created this run
        scene = args.tile
        prod = list(
            (
                Path.cwd()
                / Path(stdProjFilename(f"lztmre_{scene}_00000000_dc4mz.img")).parent
            ).glob("*dc4mz.img")
        )
        if prod:
            sample_template = str(prod[0])
    if sample_template:
        fp = _ensure_footprint(args.tile, sample_template)
        print(fp)

    print("Compat build complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

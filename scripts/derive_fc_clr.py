#!/usr/bin/env python
"""
Create fc3ms_clr by masking Fractional Cover (FC) with FMASK for matching dates.

- Finds FC files matching: ga_ls_fc_<PPP_RRR>_<YYYYMMDD>_fc3ms.tif (or uses explicit --fc path)
- Locates FMASK for the same date under the same tile root (D:\data\lsat\PPP_RRR\YYYY\YYYYMM)
- Writes ga_ls_fc_<PPP_RRR>_<YYYYMMDD>_fc3ms_clr.tif alongside the FC input

Mask logic (default): keep pixels where FMASK==1 (clear); set all others to 0.
You can override the clear class with --clear-values (comma-separated ints).

Examples (PowerShell):
  # Derive clr for one tile by scanning all FC files
  python scripts\derive_fc_clr.py --root D:\data\lsat --tile 089_080

  # Derive clr for specific FC file
  python scripts\derive_fc_clr.py --fc D:\\data\\lsat\\089_080\\2016\\201607\\ga_ls_fc_089080_20160708_fc3ms.tif

"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List

from osgeo import gdal
import subprocess
import sys

RE_FC = re.compile(r"^ga_ls_fc_(?P<pr>\d{6})_(?P<ymd>\d{8})_fc3ms\.tif$", re.IGNORECASE)


def _find_fmask_for(
    tile_pr: str, date: str, root: Path, search_days: int = 7
) -> Path | None:
    """Find FMASK file for given date, with proximity search if exact match not found."""
    pr_folder = f"{tile_pr[:3]}_{tile_pr[3:]}"
    year = date[:4]
    yearmonth = date[:6]
    d = root / pr_folder / year / yearmonth

    # First try exact date match with standardized naming
    if d.exists():
        # Try new standardized naming (sensor-specific)
        standardized_patterns = [
            f"ga_ls*_oa_{tile_pr}_{date}_fmask.tif",  # New format: ga_ls8c_oa_089078_20131004_fmask.tif
            f"ga_ls_fmask_{tile_pr}_{date}_fmask.tif",  # Previous format
        ]
        for pat in standardized_patterns:
            hits = list(d.glob(pat))
            if hits:
                return hits[0]

        # Then try original GA patterns
        original_patterns = [f"*{date}*fmask*.tif", f"*{date}*FMASK*.tif"]
        for pat in original_patterns:
            hits = list(d.glob(pat))
            if hits:
                return hits[0]

    # If no exact match and search_days > 0, try proximity search
    if search_days > 0:
        from datetime import datetime, timedelta

        try:
            target_dt = datetime.strptime(date, "%Y%m%d")

            # Search in nearby months too (±1 month from target)
            search_months = []
            for delta_months in [-1, 0, 1]:
                if delta_months == -1:
                    search_dt = target_dt.replace(day=1) - timedelta(
                        days=1
                    )  # Last day of previous month
                    search_dt = search_dt.replace(day=1)  # First day of previous month
                elif delta_months == 1:
                    # First day of next month
                    if target_dt.month == 12:
                        search_dt = target_dt.replace(
                            year=target_dt.year + 1, month=1, day=1
                        )
                    else:
                        search_dt = target_dt.replace(month=target_dt.month + 1, day=1)
                else:
                    search_dt = target_dt

                search_year = search_dt.strftime("%Y")
                search_yearmonth = search_dt.strftime("%Y%m")
                search_dir = root / pr_folder / search_year / search_yearmonth

                if search_dir.exists():
                    search_months.append((search_dir, search_dt))

            # Collect all FMASK files with their dates
            fmask_candidates = []
            for search_dir, _ in search_months:
                for fmask_file in search_dir.glob("*fmask*.tif"):
                    # Extract date from filename - handle both YYYYMMDD and YYYY-MM-DD formats
                    date_patterns = [
                        r"_(\d{8})_",  # YYYYMMDD format (standardized)
                        r"_(\d{4}-\d{2}-\d{2})_",  # YYYY-MM-DD format (original GA)
                    ]

                    for pattern in date_patterns:
                        date_match = re.search(pattern, fmask_file.name)
                        if date_match:
                            fmask_date_str = date_match.group(1)
                            try:
                                # Handle both date formats
                                if "-" in fmask_date_str:
                                    fmask_dt = datetime.strptime(
                                        fmask_date_str, "%Y-%m-%d"
                                    )
                                else:
                                    fmask_dt = datetime.strptime(
                                        fmask_date_str, "%Y%m%d"
                                    )

                                date_diff = abs((target_dt - fmask_dt).days)
                                if date_diff <= search_days:
                                    # Prefer standardized files over original GA files
                                    priority = (
                                        0
                                        if "ga_ls" in fmask_file.name
                                        and "_oa_" in fmask_file.name
                                        else 1
                                    )
                                    fmask_candidates.append(
                                        (fmask_file, date_diff, priority)
                                    )
                                break  # Found a valid date, stop trying patterns
                            except ValueError:
                                continue

            # Return closest match (prioritize standardized files)
            if fmask_candidates:
                fmask_candidates.sort(
                    key=lambda x: (x[2], x[1])
                )  # Sort by priority, then date difference
                closest_fmask = fmask_candidates[0]
                print(
                    f"[PROXY] Using FMASK {closest_fmask[0].name} (±{closest_fmask[1]} days) for {date}"
                )
                return closest_fmask[0]

        except Exception as e:
            print(f"[WARN] Error in proximity search for {date}: {e}")

    return None


def _mask_fc_with_fmask(
    fc_path: Path, fmask_path: Path, clear_values: List[int]
) -> Path:
    ds_fc = gdal.Open(str(fc_path), gdal.GA_ReadOnly)
    ds_fm = gdal.Open(str(fmask_path), gdal.GA_ReadOnly)
    if ds_fc is None or ds_fm is None:
        raise RuntimeError("Cannot open FC or FMASK input")
    xsize, ysize = ds_fc.RasterXSize, ds_fc.RasterYSize
    if (xsize, ysize) != (ds_fm.RasterXSize, ds_fm.RasterYSize):
        raise RuntimeError("FC and FMASK dimensions differ")
    geotrans, proj = ds_fc.GetGeoTransform(can_return_null=True), ds_fc.GetProjection()
    num_bands = ds_fc.RasterCount

    out_path = fc_path.with_name(fc_path.name.replace("_fc3ms.tif", "_fc3ms_clr.tif"))
    if out_path.exists():
        print(f"[SKIP] Exists: {out_path}")
        return out_path

    drv = gdal.GetDriverByName("GTiff")
    dst = drv.Create(
        str(out_path), xsize, ysize, num_bands, gdal.GDT_Byte, options=["COMPRESS=LZW"]
    )
    if geotrans:
        dst.SetGeoTransform(geotrans)
    if proj:
        dst.SetProjection(proj)

    # Read FMASK once for all bands
    fm = ds_fm.GetRasterBand(1).ReadAsArray()

    import numpy as np

    mask = np.isin(fm, np.array(clear_values, dtype=np.int32))

    # Process each band
    for band_idx in range(1, num_bands + 1):
        fc_band = ds_fc.GetRasterBand(band_idx).ReadAsArray()
        out_band = np.where(mask, fc_band, 0).astype("uint8")

        dst_band = dst.GetRasterBand(band_idx)
        dst_band.WriteArray(out_band)
        dst_band.SetNoDataValue(0)

    dst.FlushCache()
    del dst
    del ds_fc, ds_fm
    print(f"[OK] Wrote {out_path} ({num_bands} bands)")
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Derive fc3ms_clr from fc3ms using fmask")
    ap.add_argument(
        "--root", default=r"D:\\data\\lsat", help="Root folder containing PPP_RRR tiles"
    )
    ap.add_argument("--tile", help="Optional tile PPP_RRR or PPPRRR to restrict scan")
    ap.add_argument("--fc", help="Optional explicit FC file path to process")
    ap.add_argument(
        "--clear-values",
        default="1",
        help="Comma-separated FMASK values treated as clear (default 1)",
    )
    ap.add_argument(
        "--auto-fetch-fmask",
        action="store_true",
        help="If FMASK missing, attempt to fetch via ensure_sr_from_s3_or_ga.py for the date",
    )
    ap.add_argument(
        "--ensure-script",
        default="scripts/ensure_sr_from_s3_or_ga.py",
        help="Path to ensure SR/FM script",
    )
    ap.add_argument(
        "--search-days",
        type=int,
        default=7,
        help="Window (+/- days) to search for closest FMASK files (default: 7)",
    )
    args = ap.parse_args(argv)

    clear_vals = [int(x) for x in args.clear_values.split(",") if x.strip() != ""]

    root = Path(args.root)
    todo: List[Path] = []
    if args.fc:
        todo = [Path(args.fc)]
    else:
        # scan for fc3ms under root (optionally restricted to tile)
        tiles = [args.tile] if args.tile else []
        if tiles:
            t = tiles[0].strip()
            pr_folder = t if "_" in t else f"{t[:3]}_{t[3:]}"
            search_root = root / pr_folder
        else:
            search_root = root
        for dirpath, dirnames, filenames in os.walk(search_root):
            for fn in filenames:
                if RE_FC.match(fn):
                    todo.append(Path(dirpath) / fn)

    if not todo:
        print("No FC files found to process.")
        return 0

    for fc_path in sorted(todo):
        m = RE_FC.match(fc_path.name)
        if not m:
            continue
        pr = m.group("pr")
        ymd = m.group("ymd")
        fmask = _find_fmask_for(pr, ymd, root, args.search_days)
        if not fmask:
            if args.auto_fetch_fmask:
                tile_norm = f"{pr[:3]}_{pr[3:]}"
                cmd = [
                    sys.executable,
                    args.ensure_script,
                    "--tile",
                    tile_norm,
                    "--date",
                    ymd,
                    "--search-days",
                    str(args.search_days),
                    "--no-base-prefix",
                ]
                print(f"[FETCH] FMASK missing; invoking ensure script: {' '.join(cmd)}")
                try:
                    subprocess.run(cmd, check=False)
                except Exception as e:
                    print(f"[FETCH-ERR] ensure script failed for {ymd}: {e}")
                # Re-check
                fmask = _find_fmask_for(pr, ymd, root, args.search_days)
            if not fmask:
                print(f"[MISS] No FMASK found for {fc_path.name}")
                continue
        try:
            _mask_fc_with_fmask(fc_path, fmask, clear_vals)
        except Exception as e:
            print(f"[ERR] {fc_path.name}: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

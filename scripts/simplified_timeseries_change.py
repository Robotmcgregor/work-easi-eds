#!/usr/bin/env python
"""
Simplified vegetation clearing change detection script adapted from the legacy
edsadhoc_timeserieschange_d.py but decoupled from the SLATS metadb and mask system.

Inputs:
  --start-db8    Path to start reflectance stack (ENVI or GTiff) with 6 bands (B2..B7 order)
  --end-db8      Path to end reflectance stack (same georef as start)
  --dc4-glob     Glob pattern matching dc4 (FPC) single-band images for timeseries
                 (e.g. data/compat/files/p089r080/lztmre_p089r080_*_dc4mz.img)
  OR
  --dc4-list     Text file with one dc4 path per line

Outputs (written alongside compat files using original naming convention):
  lztmre_<scene>_<era>_dllmz.img  (change class)
  lztmre_<scene>_<era>_dljmz.img  (interpretation stack: spectralIndex, sTest, combinedIndex, clearingProb)

Era naming:
  Derived from years of start and end dates (e.g. start 20160708, end 20250903 -> e1625).

Simplifications vs original:
  - No database queries; timeseries provided directly.
  - No mask application; assumes inputs already cloud masked (clr).
  - Normalisation applied per-timeseries image using global mean/stddev of raw dc4 band.
  - Timeseries stats (mean, stddev, stderr, slope, intercept) computed directly with numpy.
  - If only one timeseries image provided, sTest/tTest set to 0 and slope/intercept fall back.

Dependencies: GDAL, NumPy.
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import re
from pathlib import Path
from typing import List, Tuple

import numpy as np
from osgeo import gdal

try:
    from rsc.utils.metadb import stdProjFilename
except Exception:
    def stdProjFilename(name: str) -> str:
        return name

DATE_RE = re.compile(r"_(\d{8})_")
SCENE_RE = re.compile(r"_(p\d{3}r\d{3})_")


def parse_date(path: str) -> str:
    m = DATE_RE.search(os.path.basename(path))
    if not m:
        raise ValueError(f"Cannot parse date from {path}")
    return m.group(1)


def parse_scene(path: str) -> str:
    m = SCENE_RE.search(os.path.basename(path).lower())
    if not m:
        raise ValueError(f"Cannot parse scene from {path}")
    return m.group(1)


def decimal_year(yyyymmdd: str) -> float:
    year = int(yyyymmdd[:4])
    month = int(yyyymmdd[4:6])
    day = int(yyyymmdd[6:])
    import datetime
    d = datetime.date(year, month, day)
    jan1 = datetime.date(year, 1, 1)
    dec31 = datetime.date(year, 12, 31)
    doy = (d - jan1).days
    days_in_year = (dec31 - jan1).days + 1
    return year + doy / days_in_year


def _parse_mmdd(mmdd: str) -> Tuple[int, int]:
    if len(mmdd) != 4 or not mmdd.isdigit():
        raise ValueError("MMDD must be 4 digits, e.g., 0701")
    return int(mmdd[:2]), int(mmdd[2:])


def _in_window(yyyymmdd: str, start_mmdd: str, end_mmdd: str) -> bool:
    m = int(yyyymmdd[4:6]); d = int(yyyymmdd[6:8])
    sm, sd = _parse_mmdd(start_mmdd)
    em, ed = _parse_mmdd(end_mmdd)
    # Handle wrap-around windows (e.g., Nov-Feb)
    if (sm, sd) <= (em, ed):
        return (m, d) >= (sm, sd) and (m, d) <= (em, ed)
    else:
        return (m, d) >= (sm, sd) or (m, d) <= (em, ed)


def load_raster(path: str) -> Tuple[np.ndarray, Tuple]:
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise IOError(f"Cannot open {path}")
    bands = []
    for i in range(1, ds.RasterCount + 1):
        arr = ds.GetRasterBand(i).ReadAsArray()
        bands.append(arr)
    arr_stack = np.stack(bands, axis=0)
    gt = ds.GetGeoTransform(can_return_null=True)
    proj = ds.GetProjection()
    ds = None
    return arr_stack, (gt, proj)


def harmonize_shapes(arrays: List[np.ndarray]) -> List[np.ndarray]:
    """Crop all (N,Y,X) or (Y,X) arrays to the minimal common (Y,X) footprint.
    This handles slight dimension mismatches across dc4 images.
    """
    ys = []
    xs = []
    for a in arrays:
        if a.ndim == 3:
            _, y, x = a.shape
        elif a.ndim == 2:
            y, x = a.shape
        else:
            raise ValueError("Unexpected array rank")
        ys.append(y); xs.append(x)
    min_y = min(ys); min_x = min(xs)
    cropped = []
    for a in arrays:
        if a.ndim == 3:
            cropped.append(a[..., :min_y, :min_x])
        else:
            cropped.append(a[:min_y, :min_x])
    return cropped


def normalise_fpc(arr: np.ndarray) -> np.ndarray:
    # arr is (Y,X) single-band FPC (0..100). Apply same normalisation logic.
    valid = arr > 0
    if not np.any(valid):
        return np.zeros_like(arr, dtype=np.uint8)
    mean = arr[valid].mean()
    std = arr[valid].std()
    if std == 0:
        std = 1.0
    norm = 125 + 15 * (arr.astype(np.float32) - mean) / std
    norm = np.clip(norm, 1, 255).astype(np.uint8)
    norm[~valid] = 0
    return norm


def timeseries_stats(norm_list: List[np.ndarray], date_list: List[str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # norm_list: list of (Y,X) uint8 arrays; convert to float32
    stack = np.stack([a.astype(np.float32) for a in norm_list], axis=0)  # (N,Y,X)
    mean = stack.mean(axis=0)
    std = stack.std(axis=0)
    n = stack.shape[0]
    stderr = std / math.sqrt(n) if n > 1 else np.zeros_like(mean)
    # Linear regression per pixel: y vs t (decimal year)
    if n > 1:
        t = np.array([decimal_year(d) for d in date_list], dtype=np.float32)
        t_mean = t.mean()
        denom = np.sum((t - t_mean) ** 2)
        if denom == 0:
            slope = np.zeros_like(mean)
            intercept = mean.copy()
        else:
            # Compute slope pixel-wise: sum( (t - t_mean)*(y - y_mean) ) / denom
            y_mean = mean
            slope = np.sum(((t - t_mean)[:, None, None]) * (stack - y_mean), axis=0) / denom
            intercept = y_mean - slope * t_mean
    else:
        slope = np.zeros_like(mean)
        intercept = mean.copy()
    return mean, std, stderr, slope, intercept


def classify(ref_start: np.ndarray, ref_end: np.ndarray, fpc_start_norm: np.ndarray,
             fpc_end_norm: np.ndarray, ts_mean: np.ndarray, ts_std: np.ndarray,
             ts_stderr: np.ndarray, ts_slope: np.ndarray, ts_intercept: np.ndarray,
             prediction_decimal_year: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Expect ref arrays shape (6,Y,X)
    refStart = ref_start.astype(np.float32)
    refEnd = ref_end.astype(np.float32)
    normedFpcStart = fpc_start_norm.astype(np.float32)
    normedFpcEnd = fpc_end_norm.astype(np.float32)

    fpcDiff = normedFpcEnd - normedFpcStart
    fpcDiffStdErr = -fpcDiff * ts_stderr

    predictedNormedFpc = ts_intercept + ts_slope * prediction_decimal_year
    observedNormedFpc = normedFpcEnd

    sTest = np.zeros_like(observedNormedFpc, dtype=np.float32)
    valid_stderr = ts_stderr >= 0.2
    sTest[valid_stderr] = (observedNormedFpc[valid_stderr] - predictedNormedFpc[valid_stderr]) / ts_stderr[valid_stderr]

    tTest = np.zeros_like(observedNormedFpc, dtype=np.float32)
    valid_std = ts_std >= 0.2
    tTest[valid_std] = (observedNormedFpc[valid_std] - ts_mean[valid_std]) / ts_std[valid_std]

    # Spectral index replicating original coefficients (log1p across bands 2,3,5,6 (0-based 1,2,4,5))
    spectralIndex = (
        (0.77801094 * np.log1p(refStart[1])) +
        (1.7713253  * np.log1p(refStart[2])) +
        (2.0714311  * np.log1p(refStart[4])) +
        (2.5403550  * np.log1p(refStart[5])) +
        (-0.2996241 * np.log1p(refEnd[1])) +
        (-0.5447928 * np.log1p(refEnd[2])) +
        (-2.2842536 * np.log1p(refEnd[4])) +
        (-4.0177752 * np.log1p(refEnd[5]))
    )

    combinedIndex = (-11.972499 * spectralIndex -
                     0.40357223 * fpcDiff -
                     5.2609715  * tTest -
                     4.3794265  * sTest)

    # Change classes
    NO_CLEARING = 10
    NULL_CLEARING = 0
    changeclass = np.full(spectralIndex.shape, NO_CLEARING, dtype=np.uint8)
    changeclass[combinedIndex > 21.80] = 34
    changeclass[(combinedIndex > 27.71) & (sTest < -0.27) & (spectralIndex < -0.86)] = 35
    changeclass[(combinedIndex > 33.40) & (sTest < -0.60) & (spectralIndex < -1.19)] = 36
    changeclass[(combinedIndex > 39.54) & (sTest < -1.01) & (spectralIndex < -1.50)] = 37
    changeclass[(combinedIndex > 47.05) & (sTest < -1.55) & (spectralIndex < -1.84)] = 38
    changeclass[(combinedIndex > 58.10) & (sTest < -2.34) & (spectralIndex < -2.27)] = 39
    changeclass[(tTest > -1.70) & (fpcDiffStdErr > 740)] = 3

    # Null out where reflectance has zeros
    refNullMask = (refStart == 0).any(axis=0) | (refEnd == 0).any(axis=0)
    changeclass[refNullMask] = NULL_CLEARING

    # Interpretation stack
    clearingProb = 200 * (1 - np.exp(-((0.01227 * combinedIndex) ** 3.18975)))
    clearingProb = np.round(clearingProb).astype(np.uint8)
    clearingProb[combinedIndex <= 0] = 0

    return changeclass, spectralIndex.astype(np.float32), sTest.astype(np.float32), combinedIndex.astype(np.float32), clearingProb


def write_envi(out_path: str, arrays: List[np.ndarray], georef: Tuple, dtype=gdal.GDT_Byte):
    gt, proj = georef
    ysize, xsize = arrays[0].shape
    drv = gdal.GetDriverByName("ENVI")
    ds = drv.Create(out_path, xsize, ysize, len(arrays), dtype)
    if gt:
        ds.SetGeoTransform(gt)
    if proj:
        ds.SetProjection(proj)
    for i, arr in enumerate(arrays, start=1):
        band = ds.GetRasterBand(i)
        band.WriteArray(arr)
        band.SetNoDataValue(0)
    ds.FlushCache()
    ds = None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Simplified clearing change detection")
    ap.add_argument("--start-db8", required=True)
    ap.add_argument("--end-db8", required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dc4-glob")
    group.add_argument("--dc4-list")
    ap.add_argument("--scene", help="Optional scene code pXXXrYYY (parsed from filenames if omitted)")
    ap.add_argument("--out-dir", default="data/compat/files", help="Output base directory")
    ap.add_argument("--verbose", action="store_true")
    # Seasonal-window options (optional). If provided, baseline stats are computed only from dc4 dates
    # within the window and strictly <= start date, mimicking the legacy seasonal approach.
    ap.add_argument("--window-start", help="Seasonal window start as MMDD, e.g., 0701 for Jul 1")
    ap.add_argument("--window-end", help="Seasonal window end as MMDD, e.g., 1031 for Oct 31")
    ap.add_argument("--year-lookback", type=int, default=10, help="Max baseline years before end year (default 10)")
    args = ap.parse_args(argv)

    start_date = parse_date(args.start_db8)
    end_date = parse_date(args.end_db8)
    scene = args.scene or parse_scene(args.start_db8)
    era = f"e{start_date[2:4]}{end_date[2:4]}"  # eYYYY

    # Collect dc4 files
    if args.dc4_glob:
        dc4_files = sorted(glob.glob(args.dc4_glob))
    else:
        with open(args.dc4_list, 'r', encoding='utf-8') as f:
            dc4_files = [l.strip() for l in f if l.strip()]
    if not dc4_files:
        raise SystemExit("No dc4 timeseries files found")

    # Load start/end reflectance
    ref_start, georef = load_raster(args.start_db8)
    ref_end, _ = load_raster(args.end_db8)

    # Load timeseries dc4 and normalise; harmonize shape
    raw_dc4 = []
    date_list = []
    for fp in dc4_files:
        arr, _ = load_raster(fp)
        if arr.shape[0] != 1:
            raise SystemExit(f"dc4 file must be single band: {fp}")
        raw_dc4.append(arr[0])
        date_list.append(parse_date(fp))
    # Compute a single common (Y,X) across refs and all dc4, then crop everything consistently
    all_for_shape = [ref_start, ref_end] + raw_dc4  # raw_dc4 entries are 2D; ref_* are 3D
    # Determine min shape
    ys = []; xs = []
    for a in all_for_shape:
        if a.ndim == 3:
            _, y, x = a.shape
        else:
            y, x = a.shape
        ys.append(y); xs.append(x)
    min_y = min(ys); min_x = min(xs)
    # Crop refs and dc4 to common shape
    def _crop(arr):
        if arr.ndim == 3:
            return arr[..., :min_y, :min_x]
        return arr[:min_y, :min_x]
    ref_start = _crop(ref_start)
    ref_end = _crop(ref_end)
    raw_dc4 = [_crop(a) for a in raw_dc4]
    norm_list = [normalise_fpc(a) for a in raw_dc4]

    # Optionally restrict the baseline to a seasonal window and to dates <= start_date
    baseline_dates = date_list
    baseline_norm = norm_list
    if args.window_start and args.window_end:
        try:
            _ = _parse_mmdd(args.window_start); _ = _parse_mmdd(args.window_end)
        except Exception as e:
            raise SystemExit(f"Invalid seasonal window: {e}")
        end_year = int(end_date[:4])
        start_cutoff = start_date
        # Keep only dates inside window, within lookback years, and <= start date
        filt = []
        for d, a in zip(date_list, norm_list):
            if not _in_window(d, args.window_start, args.window_end):
                continue
            y = int(d[:4])
            if y < end_year - args.year_lookback + 1 or y > end_year:
                continue
            if d > start_cutoff:
                continue
            filt.append((d, a))
        if len(filt) >= 2:
            # Optionally reduce to one per year by choosing date closest to end month/day
            target_mmdd = end_date[4:]
            tm, td = int(target_mmdd[:2]), int(target_mmdd[2:])
            by_year = {}
            for d, a in filt:
                y = int(d[:4])
                by_year.setdefault(y, []).append((d, a))
            sel_dates = []
            sel_norm = []
            for y, lst in sorted(by_year.items()):
                # choose the date closest in MMDD to target
                def md_dist(dstr: str) -> int:
                    m = int(dstr[4:6]); dd = int(dstr[6:8])
                    # distance in months first, then days (rough heuristic)
                    return abs((m - tm) * 31 + (dd - td))
                chosen = sorted(lst, key=lambda t: md_dist(t[0]))[0]
                sel_dates.append(chosen[0])
                sel_norm.append(chosen[1])
            baseline_dates = sel_dates
            baseline_norm = sel_norm
            if args.verbose:
                print(f"Seasonal baseline: {len(baseline_dates)} images across years {min(int(d[:4]) for d in baseline_dates)}-{max(int(d[:4]) for d in baseline_dates)}")
        else:
            if args.verbose:
                print("Seasonal filter yielded <2 images; falling back to all provided dc4 for baseline stats.")

    ts_mean, ts_std, ts_stderr, ts_slope, ts_intercept = timeseries_stats(baseline_norm, baseline_dates)

    # Choose first timeseries image matching start_date for start FPC; else use earliest
    # Pick start/end FPC images. Prefer exact matches; otherwise choose nearest within the seasonal window if provided.
    def nearest_idx(target: str, pool_dates: List[str], constrain_window: bool) -> int:
        if target in pool_dates:
            return pool_dates.index(target)
        best = None
        for i, d in enumerate(pool_dates):
            if constrain_window and args.window_start and args.window_end:
                if not _in_window(d, args.window_start, args.window_end):
                    continue
            # absolute day distance
            import datetime
            def to_date(s):
                return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            dist = abs((to_date(d) - to_date(target)).days)
            if best is None or dist < best[0]:
                best = (dist, i)
        return best[1] if best else 0

    idx_start = nearest_idx(start_date, date_list, constrain_window=True)
    idx_end = nearest_idx(end_date, date_list, constrain_window=True)
    fpc_start_norm = norm_list[idx_start]
    fpc_end_norm = norm_list[idx_end]

    prediction_decimal_year = decimal_year(end_date)

    changeclass, spectralIndex, sTest, combinedIndex, clearingProb = classify(
        ref_start, ref_end, fpc_start_norm, fpc_end_norm,
        ts_mean, ts_std, ts_stderr, ts_slope, ts_intercept,
        prediction_decimal_year
    )

    out_base_cls = stdProjFilename(f"lztmre_{scene}_{era}_dllmz.img")
    out_base_int = stdProjFilename(f"lztmre_{scene}_{era}_dljmz.img")
    Path(out_base_cls).parent.mkdir(parents=True, exist_ok=True)

    write_envi(out_base_cls, [changeclass], georef, dtype=gdal.GDT_Byte)
    write_envi(out_base_int, [spectralIndex.astype(np.float32),
                              sTest.astype(np.float32),
                              combinedIndex.astype(np.float32),
                              clearingProb.astype(np.uint8)], georef, dtype=gdal.GDT_Float32)

    if args.verbose:
        print(f"Wrote change class: {out_base_cls}")
        print(f"Wrote interpretation: {out_base_int}")
        print(f"Timeseries images (provided): {len(dc4_files)} | Baseline used: {len(baseline_dates)}")
    else:
        print(out_base_cls)
        print(out_base_int)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

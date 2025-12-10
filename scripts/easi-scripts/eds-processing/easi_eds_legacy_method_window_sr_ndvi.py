#!/usr/bin/env python
"""
Legacy seasonal-window change detection using NDVI (DLL/DLJ) — SR-based variant.

This adapts the legacy EDS seasonal-window approach to use NDVI computed from SR
instead of raw FPC values. The core methodology remains the same:
  - Compute NDVI from SR bands (RED=B4, NIR=B5) in the dc4 files.
  - Normalize NDVI timeseries: center at 125 with scale ~= 15 (uint8 1..255).
  - Select seasonal baseline: up to N years lookback within MMDD window, <= start date.
  - Time-series statistics: mean, std, stderr, slope (trend).
  - Spectral index from start/end SR bands 2,3,5,6; combined with NDVI trend.
  - Output classes: 10=no-clearing, 3=NDVI-only, 34..39=increasing clearing.
  - Interpretation (DLJ): stretch indices to uint8 and compute clearingProb.

Inputs:
    --scene pXXXrYYY                          Scene code used in output filenames
    --start-date YYYYMMDD                     Start date within the seasonal window
    --end-date   YYYYMMDD                     End date within the seasonal window
    --dc4-glob   pattern                      Glob for available NDVI dc4 files
    --start-db8  path                         Optional explicit start db8 stack
    --end-db8    path                         Optional explicit end db8 stack
    --window-start MMDD                       Seasonal window start (default = start-date MMDD)
    --window-end   MMDD                       Seasonal window end   (default = end-date MMDD)
    --lookback N                              Years to look back for baseline (default 10)
    --omit-ndvi-start-threshold               Do not apply the ndviStart<108 => no-clearing rule
    --verbose                                  Log baseline dates and output paths

Outputs:
    lztmre_<scene>_d<start><end>_dllmz.img    Change class (uint8): 10=no-clearing, 3=NDVI-only, 34..39=increasing clearing
    lztmre_<scene>_d<start><end>_dljmz.img    Interpretation (uint8 x4): [spectral, ndviTrend, combined, clearingProb]

Key differences from FC version:
    - dc4 images contain NDVI (0-200 scaled from [-1, 1]) instead of FPC (0-255).
    - Normalization uses the same mean/std approach but on NDVI values.
    - NDVI threshold check (start < 108 -> no-clearing) replaces FPC check.
    - Spectral index calculation remains the same (uses SR bands from db8).
"""

from __future__ import annotations

import argparse
import glob
import math
import os
from pathlib import Path
from typing import List, Tuple

import numpy as np
from osgeo import gdal

try:
    from rsc.utils.metadb import stdProjFilename
except Exception:

    def stdProjFilename(name: str) -> str:
        return name


def parse_date(path: str) -> str:
    """Extract YYYYMMDD from a file path."""
    import re
    filename = os.path.basename(path)
    m = re.search(r"(19|20)\d{6}", filename)
    if not m:
        raise ValueError(f"Cannot find a date in the file name: {path}")
    return m.group(0)


def decimal_year(yyyymmdd: str) -> float:
    """Convert YYYYMMDD to decimal year."""
    import datetime
    y = int(yyyymmdd[:4])
    m = int(yyyymmdd[4:6])
    d = int(yyyymmdd[6:])
    date = datetime.date(y, m, d)
    jan1 = datetime.date(y, 1, 1)
    dec31 = datetime.date(y, 12, 31)
    doy = (date - jan1).days
    days = (dec31 - jan1).days + 1
    return y + doy / days


from typing import Tuple


def _parse_mmdd(mmdd: str) -> Tuple[int, int]:
    """Parse MMDD into month and day."""
    if len(mmdd) != 4 or not mmdd.isdigit():
        raise ValueError("MMDD must be 4 digits, e.g., '0701' for 1st of July")
    month = int(mmdd[:2])
    day = int(mmdd[2:])
    return month, day


def in_window(yyyymmdd: str, start_mmdd: str, end_mmdd: str) -> bool:
    """Check whether a date falls inside a seasonal window (MMDD range)."""
    m = int(yyyymmdd[4:6])
    d = int(yyyymmdd[6:8])
    sm, sd = _parse_mmdd(start_mmdd)
    em, ed = _parse_mmdd(end_mmdd)
    if (sm, sd) <= (em, ed):
        return (m, d) >= (sm, sd) and (m, d) <= (em, ed)
    else:
        return (m, d) >= (sm, sd) or (m, d) <= (em, ed)


def load_raster(path: str) -> Tuple[np.ndarray, Tuple]:
    """Load a raster file and return the array(s) + georeferencing info."""
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise IOError(f"Cannot open {path}")
    bands = [ds.GetRasterBand(i + 1).ReadAsArray() for i in range(ds.RasterCount)]
    arr = np.stack(bands, axis=0) if len(bands) > 1 else bands[0]
    if len(bands) == 1 and arr.ndim == 2:
        arr = arr[np.newaxis, :, :]
    georef = (ds.GetGeoTransform(can_return_null=True), ds.GetProjection())
    ds = None
    return arr, georef


def write_envi(
    out_path: str,
    arrays: List[np.ndarray],
    georef: Tuple,
    dtype=gdal.GDT_Byte,
    nodata=0,
) -> None:
    """Write a multi-band raster in ENVI format."""
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
        band.SetNoDataValue(nodata)
    ds.FlushCache()
    ds = None


def normalise_ndvi(arr: np.ndarray) -> np.ndarray:
    """
    Normalize NDVI values to 0-255 range.
    
    NDVI input is expected to be in [0, 200] (representing [-1, 1] NDVI).
    We normalize using the same approach as FPC: center at 125 with scale ~= 15.
    Zeros are treated as nodata.
    """
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


def timeseries_stats(
    norm_list: List[np.ndarray], date_list: List[str]
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute baseline statistics across normalized NDVI stack."""
    stack = np.stack([a.astype(np.float32) for a in norm_list], axis=0)
    mean = stack.mean(axis=0)
    std = stack.std(axis=0)
    n = stack.shape[0]
    if n > 1:
        stderr = std / math.sqrt(n)
    else:
        stderr = np.zeros_like(mean)

    if n > 1:
        t = np.array([decimal_year(d) for d in date_list], dtype=np.float32)
        t_mean = t.mean()
        denom = np.sum((t - t_mean) ** 2)
        if denom == 0:
            slope = np.zeros_like(mean)
            intercept = mean.copy()
        else:
            y_mean = mean
            slope = np.sum(((t - t_mean)[:, None, None]) * (stack - y_mean), axis=0) / denom
            intercept = y_mean - slope * t_mean
    else:
        slope = np.zeros_like(mean)
        intercept = mean.copy()
    
    return mean, std, stderr, slope, intercept


def stretch(
    img: np.ndarray,
    mean: float,
    stddev: float,
    numStdDev: float,
    minVal: int,
    maxVal: int,
    ignoreVal: float,
) -> np.ndarray:
    """Apply legacy-style linear stretch."""
    stretched = minVal + (img - mean + stddev * numStdDev) * (maxVal - minVal) / (
        stddev * 2 * numStdDev
    )
    stretched = np.clip(stretched, minVal, maxVal).astype(np.float32)
    stretched[img == ignoreVal] = 0
    return stretched.astype(np.uint8)


def main(argv=None) -> int:
    """Execute the legacy seasonal-window change detection using NDVI."""
    ap = argparse.ArgumentParser(
        description="Legacy-method change detection (seasonal window) using NDVI from SR"
    )
    ap.add_argument("--scene", required=True)
    ap.add_argument("--start-date", required=True)
    ap.add_argument("--end-date", required=True)
    ap.add_argument("--dc4-glob", help="Glob for dc4 NDVI images; defaults to compat path")
    ap.add_argument("--start-db8")
    ap.add_argument("--end-db8")
    ap.add_argument("--window-start")
    ap.add_argument("--window-end")
    ap.add_argument("--lookback", type=int, default=10)
    ap.add_argument("--omit-ndvi-start-threshold", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    scene = args.scene.lower()
    sd = args.start_date
    ed = args.end_date
    ws = args.window_start or sd[4:]
    we = args.window_end or ed[4:]

    # Resolve SR db8 stacks
    if args.start_db8 and args.end_db8:
        start_db8 = args.start_db8
        end_db8 = args.end_db8
    else:
        start_db8 = stdProjFilename(f"lztmre_{scene}_{sd}_db8mz.img")
        end_db8 = stdProjFilename(f"lztmre_{scene}_{ed}_db8mz.img")

    if not os.path.exists(start_db8) or not os.path.exists(end_db8):
        raise SystemExit("Start/end db8 files not found; provide --start-db8/--end-db8 or build them.")

    # Resolve dc4 (NDVI) files
    if args.dc4_glob:
        dc4_files = sorted(glob.glob(args.dc4_glob))
    else:
        base = Path(stdProjFilename(f"lztmre_{scene}_00000000_dc4mz.img")).parent
        dc4_files = sorted(glob.glob(str(base / f"lztmre_{scene}_*_dc4mz.img")))

    if not dc4_files:
        raise SystemExit("No dc4 (NDVI) images found")

    # Load SR reflectance
    ref_start, georef = load_raster(start_db8)
    ref_end, _ = load_raster(end_db8)

    # Load NDVI dc4 images and crop to common shape
    raw_ndvi = []
    dates = []
    for p in dc4_files:
        arr, _ = load_raster(p)
        if arr.shape[0] != 1:
            raise SystemExit(f"dc4 (NDVI) must be single band: {p}")
        raw_ndvi.append(arr[0])
        dates.append(parse_date(p))

    # Determine common shape
    ys = []
    xs = []
    for a in [ref_start, ref_end] + raw_ndvi:
        if a.ndim == 3:
            _, y, x = a.shape
        else:
            y, x = a.shape
        ys.append(y)
        xs.append(x)

    min_y = min(ys)
    min_x = min(xs)

    def crop(a):
        if a.ndim == 3:
            return a[..., :min_y, :min_x]
        return a[:min_y, :min_x]

    ref_start = crop(ref_start).astype(np.float32)
    ref_end = crop(ref_end).astype(np.float32)
    raw_ndvi = [crop(a) for a in raw_ndvi]

    # Build seasonal baseline: select one NDVI per year within window, up to lookback years
    baseline_ndvi = []
    baseline_dates = []
    start_year = int(sd[:4])

    for year_offset in range(1, args.lookback + 1):
        baseline_year = start_year - year_offset
        candidates = [
            (p, d) for p, d in zip(raw_ndvi, dates)
            if int(d[:4]) == baseline_year
            and in_window(d, ws, we)
            and d <= sd
        ]
        if candidates:
            chosen = min(candidates, key=lambda x: abs(int(x[1][4:]) - int(sd[4:])))
            baseline_ndvi.append(chosen[0])
            baseline_dates.append(chosen[1])

    # Fallback if baseline is too small
    if len(baseline_ndvi) < 2:
        fallback = [
            (p, d) for p, d in zip(raw_ndvi, dates)
            if in_window(d, ws, we) and d <= sd
        ]
        if len(fallback) >= 2:
            baseline_ndvi = [p for p, d in sorted(fallback, key=lambda x: x[1])]
            baseline_dates = [d for p, d in sorted(fallback, key=lambda x: x[1])]
        else:
            raise SystemExit("Insufficient baseline NDVI images")

    if args.verbose:
        print(f"[Baseline NDVI] Found {len(baseline_ndvi)} images: {baseline_dates}")

    # Select start/end NDVI images
    start_candidates = [
        (p, d) for p, d in zip(raw_ndvi, dates)
        if in_window(d, ws, we) and d <= sd and d not in baseline_dates
    ]
    end_candidates = [
        (p, d) for p, d in zip(raw_ndvi, dates)
        if in_window(d, ws, we) and d >= ed and d not in baseline_dates
    ]

    if not start_candidates:
        start_ndvi, start_ndvi_date = baseline_ndvi[-1], baseline_dates[-1]
    else:
        start_ndvi, start_ndvi_date = min(start_candidates, key=lambda x: abs(int(x[1]) - int(sd)))

    if not end_candidates:
        end_ndvi, end_ndvi_date = baseline_ndvi[-1], baseline_dates[-1]
    else:
        end_ndvi, end_ndvi_date = min(end_candidates, key=lambda x: abs(int(x[1]) - int(ed)))

    if args.verbose:
        print(f"[Start NDVI] {start_ndvi_date}")
        print(f"[End NDVI]   {end_ndvi_date}")

    # Normalize NDVI
    norm_baseline = [normalise_ndvi(a) for a in baseline_ndvi]
    norm_start = normalise_ndvi(start_ndvi)
    norm_end = normalise_ndvi(end_ndvi)

    # Compute baseline statistics
    base_mean, base_std, base_stderr, base_slope, base_intercept = timeseries_stats(
        norm_baseline, baseline_dates
    )

    # Compute change indices
    # ndvi_trend: how much the (normalised) NDVI changed between start and end.
    # This mirrors fpcDiff in the FC script but uses NDVI instead of FPC.
    ndvi_trend = norm_end.astype(np.float32) - norm_start.astype(np.float32)

    # Spectral index from SR (db8) — use the same legacy weighted log1p combination
    # as the FC script. This looks at start vs end reflectance for bands 2,3,5,6.
    # Note: db8 indexing in legacy code refers to [1,2,4,5] for B2,B3,B5,B6 respectively.
    # Our arrays are 0-based, so indices become [1,2,4,5].
    refStart = ref_start
    refEnd = ref_end

    spectral_index = (
        (0.77801094 * np.log1p(refStart[1]))
        + (1.7713253 * np.log1p(refStart[2]))
        + (2.0714311 * np.log1p(refStart[4]))
        + (2.5403550 * np.log1p(refStart[5]))
        + (-0.2996241 * np.log1p(refEnd[1]))
        + (-0.5447928 * np.log1p(refEnd[2]))
        + (-2.2842536 * np.log1p(refEnd[4]))
        + (-4.0177752 * np.log1p(refEnd[5]))
    ).astype(np.float32)

    # Legacy-style tests using NDVI:
    # s_test: how far observed end NDVI is from the predicted trend (stderr units)
    # t_test: how far observed end NDVI is from the baseline mean (std units)
    s_test = np.zeros_like(norm_end, dtype=np.float32)
    t_test = np.zeros_like(norm_end, dtype=np.float32)
    valid_stderr = base_stderr >= 0.2
    valid_std = base_std >= 0.2
    prediction_decimal_year = decimal_year(ed)
    predicted_normed_ndvi = base_intercept + base_slope * prediction_decimal_year
    observed_normed_ndvi = norm_end.astype(np.float32)
    s_test[valid_stderr] = (
        observed_normed_ndvi[valid_stderr] - predicted_normed_ndvi[valid_stderr]
    ) / base_stderr[valid_stderr]
    t_test[valid_std] = (
        observed_normed_ndvi[valid_std] - base_mean[valid_std]
    ) / base_std[valid_std]

    # Combined index — use the same coefficients as the FC method but substitute NDVI trend
    combined_index = (
        -11.972499 * spectral_index
        - 0.40357223 * ndvi_trend
        - 5.2609715 * t_test
        - 4.3794265 * s_test
    ).astype(np.float32)

    # Clearing decision logic — mirror legacy DLL thresholds
    NO_CLEARING = 10
    NULL_CLEARING = 0
    dll_class = np.full(spectral_index.shape, NO_CLEARING, dtype=np.uint8)
    dll_class[combined_index > 21.80] = 34
    dll_class[(combined_index > 27.71) & (s_test < -0.27) & (spectral_index < -0.86)] = 35
    dll_class[(combined_index > 33.40) & (s_test < -0.60) & (spectral_index < -1.19)] = 36
    dll_class[(combined_index > 39.54) & (s_test < -1.01) & (spectral_index < -1.50)] = 37
    dll_class[(combined_index > 47.05) & (s_test < -1.55) & (spectral_index < -1.84)] = 38
    dll_class[(combined_index > 58.10) & (s_test < -2.34) & (spectral_index < -2.27)] = 39

    # NDVI-only class 3 (analogous to FPC-only): strong NDVI signal not explained by clearing thresholds
    ndviDiffStdErr = -ndvi_trend * base_stderr
    dll_class[(t_test > -1.70) & (ndviDiffStdErr > 740)] = 3

    # Optional: force no-clearing where starting NDVI is very low
    if not args.omit_ndvi_start_threshold:
        dll_class[norm_start < 108] = NO_CLEARING

    # Interpretation (DLJ): stretch indices to uint8
    # Interpretation layers & clearing probability — legacy-style
    spectralMean = float(np.mean(spectral_index[spectral_index != 0])) if np.any(spectral_index != 0) else 0.0
    spectralStd  = float(np.std(spectral_index[spectral_index != 0])) if np.any(spectral_index != 0) else 1.0
    sTestMean    = float(np.mean(s_test[s_test != 0])) if np.any(s_test != 0) else 0.0
    sTestStd     = float(np.std(s_test[s_test != 0])) if np.any(s_test != 0) else 1.0
    combMean     = float(np.mean(combined_index[combined_index != 0])) if np.any(combined_index != 0) else 0.0
    combStd      = float(np.std(combined_index[combined_index != 0])) if np.any(combined_index != 0) else 1.0

    spectral_stretch = stretch(spectral_index, spectralMean, spectralStd, 2, 1, 255, 0)
    trend_stretch     = stretch(s_test, sTestMean, sTestStd, 10, 1, 255, 0)
    combined_stretch  = stretch(combined_index, combMean, combStd, 10, 1, 255, 0)

    clearing_prob = 200 * (1 - np.exp(-((0.01227 * combined_index) ** 3.18975)))
    clearing_prob = np.round(clearing_prob).astype(np.uint8)
    clearing_prob[combined_index <= 0] = 0

    # Output filenames
    # Include the tile (scene) and the process used (vi=ndvi) in output names for traceability
    out_base = f"lztmre_{scene}_d{sd}{ed}_vi-ndvi"
    dll_path = stdProjFilename(f"{out_base}_dllmz.img")
    dlj_path = stdProjFilename(f"{out_base}_dljmz.img")

    if args.verbose:
        print(f"[Output] DLL: {dll_path}")
        print(f"[Output] DLJ: {dlj_path}")

    # Write outputs
    write_envi(dll_path, [dll_class], georef, dtype=gdal.GDT_Byte)
    write_envi(dlj_path, [spectral_stretch, trend_stretch, combined_stretch, clearing_prob], georef, dtype=gdal.GDT_Byte)

    # Lightweight JSON provenance log for traceability
    try:
        import json
        log = {
            "scene": scene,
            "start_date": sd,
            "end_date": ed,
            "process": "vi-ndvi",
            "window_start": ws,
            "window_end": we,
            "lookback_years": args.lookback,
            "baseline_dates": baseline_dates,
            "start_ndvi_date": start_ndvi_date,
            "end_ndvi_date": end_ndvi_date,
            "outputs": {
                "dll": dll_path,
                "dlj": dlj_path
            }
        }
        log_path = os.path.splitext(dll_path)[0] + "_log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        if args.verbose:
            print(f"[Output] LOG: {log_path}")
    except Exception as e:
        print(f"[WARN] Failed to write log JSON: {e}")

    print(f"[OK] Completed: {dll_path}, {dlj_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

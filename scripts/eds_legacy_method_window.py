#!/usr/bin/env python
"""
Legacy seasonal-window change detection (DLL/DLJ) — fully self-contained and annotated.

This re-implements the core of the legacy EDS approach (edsadhoc_timeserieschange_d.py) without
depending on the old DB/masks/gdaltimeseries stack. It preserves methodology and naming so other
downstream tools (styling, polygonization) work unchanged.

Key method components:
    - FPC normalization per image: global mean/std -> centered at 125 with scale ~= 15 (uint8 1..255).
    - Seasonal baseline selection: up to N years lookback, 1 image per year within MMDD window, <= start date.
    - Time-series statistics on normalized FPC: mean, std, stderr, slope, intercept (dec. year regression).
    - Spectral index: weighted log1p() combination of start/end reflectance bands 2,3,5,6 (db8 indices 1,2,4,5).
    - Combined index + tests: combinedIndex, sTest (vs regression), tTest (vs baseline mean), with legacy thresholds.
    - Optional rule: if raw FPC start < 108, force no-clearing (class 10) unless suppressed by flag.
    - Interpretation (DLJ): stretch spectral/sTest/combined to uint8 (legacy scales) and compute clearingProb (0..200 -> clipped to 0..255).

Inputs:
    --scene pXXXrYYY                          Scene code used in output filenames
    --start-date YYYYMMDD                     Start date within the seasonal window (target for FPC start)
    --end-date   YYYYMMDD                     End date within the seasonal window (target for FPC end)
    --dc4-glob   pattern                      Glob for available dc4 files (defaults to compat path)
    --start-db8  path                         Optional explicit start db8 stack
    --end-db8    path                         Optional explicit end db8 stack
    --window-start MMDD                       Seasonal window start (default = start-date MMDD)
    --window-end   MMDD                       Seasonal window end   (default = end-date MMDD)
    --lookback N                              Years to look back for baseline (default 10)
    --omit-fpc-start-threshold                Do not apply the fpcStart<108 => no-clearing rule
    --verbose                                  Log baseline dates and output paths

Outputs:
    lztmre_<scene>_d<start><end>_dllmz.img    Change class (uint8): 10=no-clearing, 3=FPC-only, 34..39=increasing clearing
    lztmre_<scene>_d<start><end>_dljmz.img    Interpretation (uint8 x4): [spectral, sTest, combined, clearingProb]

Assumptions:
    - Inputs are in the compatibility layout (db8/dc4 filenames) and pre-masked (e.g., using *_clr FC variants).
    - SR stacks (db8) contain at least bands 2,3,5,6; zeros are treated as nodata.
    - dc4 images are 1-band FPC arrays [0..255], with 0 treated as nodata when normalizing.

Notes on behavior:
    - The algorithm crops all inputs to the minimal common intersection of array shapes to avoid shape mismatches.
    - Baseline requires >= 2 images; if the one-per-year window pick yields <2, we fall back to “all available within window prior to start”.
    - When exact FPC start/end dates aren’t present, nearest images within the window are chosen.
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
    import re
    m = re.search(r"(19|20)\d{6}", os.path.basename(path))
    if not m:
        raise ValueError(f"Cannot parse date from {path}")
    return m.group(0)


def decimal_year(yyyymmdd: str) -> float:
    import datetime
    y = int(yyyymmdd[:4]); m = int(yyyymmdd[4:6]); d = int(yyyymmdd[6:])
    date = datetime.date(y, m, d)
    jan1 = datetime.date(y, 1, 1)
    dec31 = datetime.date(y, 12, 31)
    doy = (date - jan1).days
    days = (dec31 - jan1).days + 1
    return y + doy / days


def _parse_mmdd(mmdd: str) -> Tuple[int, int]:
    if len(mmdd) != 4 or not mmdd.isdigit():
        raise ValueError("MMDD must be 4 digits, e.g., 0701")
    return int(mmdd[:2]), int(mmdd[2:])


def in_window(yyyymmdd: str, start_mmdd: str, end_mmdd: str) -> bool:
    m = int(yyyymmdd[4:6]); d = int(yyyymmdd[6:8])
    sm, sd = _parse_mmdd(start_mmdd)
    em, ed = _parse_mmdd(end_mmdd)
    if (sm, sd) <= (em, ed):
        return (m, d) >= (sm, sd) and (m, d) <= (em, ed)
    else:
        return (m, d) >= (sm, sd) or (m, d) <= (em, ed)


def load_raster(path: str) -> Tuple[np.ndarray, Tuple]:
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise IOError(f"Cannot open {path}")
    bands = [ds.GetRasterBand(i+1).ReadAsArray() for i in range(ds.RasterCount)]
    arr = np.stack(bands, axis=0)
    georef = (ds.GetGeoTransform(can_return_null=True), ds.GetProjection())
    ds = None
    return arr, georef


def write_envi(out_path: str, arrays: List[np.ndarray], georef: Tuple, dtype=gdal.GDT_Byte, nodata=0) -> None:
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


def normalise_fpc(arr: np.ndarray) -> np.ndarray:
    """Normalize raw FPC image to legacy-style uint8 with mean~125 and scale~15.

    - Valid pixels are strictly > 0 (zeros are treated as nodata from masks).
    - If std==0 (flat image), we avoid division by zero by using std=1.0.
    - Output is clipped to [1,255], with nodata set back to 0.
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


def timeseries_stats(norm_list: List[np.ndarray], date_list: List[str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute baseline statistics across normalized FPC stack.

    Returns per-pixel arrays for:
      - mean, std, stderr (std/sqrt(N) when N>1, else zeros)
      - slope, intercept from linear fit in decimal year time
    """
    # Stack to shape (N, Y, X)
    stack = np.stack([a.astype(np.float32) for a in norm_list], axis=0)
    mean = stack.mean(axis=0)
    std = stack.std(axis=0)
    n = stack.shape[0]
    stderr = std / math.sqrt(max(n, 1)) if n > 1 else np.zeros_like(mean)
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


def stretch(img: np.ndarray, mean: float, stddev: float, numStdDev: float, minVal: int, maxVal: int, ignoreVal: float) -> np.ndarray:
    """Legacy-style linear stretch to uint8 given mean/std and a +-numStdDev window.

    Pixels equal to ignoreVal (e.g., 0) are forced to 0 in the output.
    """
    stretched = minVal + (img - mean + stddev * numStdDev) * (maxVal - minVal) / (stddev * 2 * numStdDev)
    stretched = np.clip(stretched, minVal, maxVal)
    stretched = stretched.astype(np.float32)
    stretched[img == ignoreVal] = 0
    return stretched.astype(np.uint8)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Legacy-method change detection (seasonal window)")
    ap.add_argument('--scene', required=True)
    ap.add_argument('--start-date', required=True)
    ap.add_argument('--end-date', required=True)
    ap.add_argument('--dc4-glob', help='Glob for dc4 images; defaults to compat path')
    ap.add_argument('--start-db8')
    ap.add_argument('--end-db8')
    ap.add_argument('--window-start')
    ap.add_argument('--window-end')
    ap.add_argument('--lookback', type=int, default=10)
    ap.add_argument('--omit-fpc-start-threshold', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args(argv)

    scene = args.scene.lower()
    sd = args.start_date
    ed = args.end_date
    ws = args.window_start or sd[4:]
    we = args.window_end or ed[4:]

    # Discover inputs
    # If explicit start/end db8 stacks are not supplied, derive their standard filenames.
    if args.start_db8 and args.end_db8:
        start_db8 = args.start_db8
        end_db8 = args.end_db8
    else:
        start_db8 = stdProjFilename(f"lztmre_{scene}_{sd}_db8mz.img")
        end_db8 = stdProjFilename(f"lztmre_{scene}_{ed}_db8mz.img")
    if not os.path.exists(start_db8) or not os.path.exists(end_db8):
        raise SystemExit("Start/end db8 files not found; provide --start-db8/--end-db8 or build them.")

    # dc4 sources: prefer explicit glob passed by the master; otherwise use scene-based directory.
    if args.dc4_glob:
        dc4_files = sorted(glob.glob(args.dc4_glob))
    else:
        base = Path(stdProjFilename(f"lztmre_{scene}_00000000_dc4mz.img")).parent
        dc4_files = sorted(glob.glob(str(base / f"lztmre_{scene}_*_dc4mz.img")))
    if not dc4_files:
        raise SystemExit("No dc4 images found")

    # Load reflectance
    ref_start, georef = load_raster(start_db8)
    ref_end, _ = load_raster(end_db8)

    # Load dc4 and crop all arrays to a common shape (minimal Y,X across all inputs).
    # This safeguards against slight dimension/transform mismatches in inputs.
    raw_dc4 = []
    dates = []
    for p in dc4_files:
        arr, _ = load_raster(p)
        if arr.shape[0] != 1:
            raise SystemExit(f"dc4 must be single band: {p}")
        raw_dc4.append(arr[0])
        dates.append(parse_date(p))
    # Determine minimal common shape across start/end reflectance and all dc4 rasters
    ys = []; xs = []
    for a in [ref_start, ref_end] + raw_dc4:
        if a.ndim == 3:
            _, y, x = a.shape
        else:
            y, x = a.shape
        ys.append(y); xs.append(x)
    min_y = min(ys); min_x = min(xs)
    def crop(a):
        if a.ndim == 3:
            return a[..., :min_y, :min_x]
        return a[:min_y, :min_x]
    ref_start = crop(ref_start).astype(np.float32)
    ref_end = crop(ref_end).astype(np.float32)
    raw_dc4 = [crop(a) for a in raw_dc4]

    # Build seasonal baseline: choose at most one dc4 image per prior year within the window, up to lookback.
    # Constraint: pick dates <= provided start-date. We choose the date closest (by MMDD) to the end target within each year.
    end_year = int(ed[:4])
    start_cutoff = sd
    # group dates by year
    by_year = {}
    for d, a in zip(dates, raw_dc4):
        y = int(d[:4])
        if y < end_year - args.lookback + 1 or y > end_year:
            continue
        if d > start_cutoff:
            continue
        if not in_window(d, ws, we):
            continue
        by_year.setdefault(y, []).append((d, a))
    # choose nearest to end MMDD within window
    tm, td = int(we[:2]), int(we[2:])
    def md_dist(d: str) -> int:
        return abs((int(d[4:6]) - tm) * 31 + (int(d[6:8]) - td))
    base_dates: List[str] = []
    base_raw: List[np.ndarray] = []
    for y in sorted(by_year.keys()):
        lst = by_year[y]
        if lst:
            d, a = sorted(lst, key=lambda t: md_dist(t[0]))[0]
            base_dates.append(d)
            base_raw.append(a)
    if len(base_dates) < 2:
        # Fallback: use all available dc4 prior to start within the window (not limited to 1 per year)
        base_dates = [d for d in dates if (d <= start_cutoff and in_window(d, ws, we))]
        base_raw = [a for d, a in zip(dates, raw_dc4) if (d <= start_cutoff and in_window(d, ws, we))]
        if len(base_dates) < 2:
            raise SystemExit("Baseline too small (<2 images) after seasonal filtering")

    # Normalise baseline
    base_norm = [normalise_fpc(a) for a in base_raw]
    ts_mean, ts_std, ts_stderr, ts_slope, ts_intercept = timeseries_stats(base_norm, base_dates)

    # Choose FPC start/end closest to provided dates (constrained to seasonal window).
    # If exact dates are present they are used; otherwise nearest-in-days inside the window.
    def nearest_idx(target: str, pool_dates: List[str]) -> int:
        if target in pool_dates:
            return pool_dates.index(target)
        best = None
        for i, d in enumerate(pool_dates):
            if not in_window(d, ws, we):
                continue
            import datetime
            def to_date(s):
                return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            dist = abs((to_date(d) - to_date(target)).days)
            if best is None or dist < best[0]:
                best = (dist, i)
        return best[1] if best else 0
    idx_start = nearest_idx(sd, dates)
    idx_end = nearest_idx(ed, dates)
    fpc_start_raw = raw_dc4[idx_start]
    fpc_end_raw = raw_dc4[idx_end]
    fpc_start_norm = normalise_fpc(fpc_start_raw)
    fpc_end_norm = normalise_fpc(fpc_end_raw)

    # Legacy indices and tests
    # fpcDiff is based on normalised FPC; its product with stderr (negated) follows the legacy sign convention.
    fpcDiff = fpc_end_norm.astype(np.float32) - fpc_start_norm.astype(np.float32)
    fpcDiffStdErr = -fpcDiff * ts_stderr
    prediction_decimal_year = decimal_year(ed)
    predictedNormedFpc = ts_intercept + ts_slope * prediction_decimal_year
    observedNormedFpc = fpc_end_norm.astype(np.float32)
    sTest = np.zeros_like(observedNormedFpc, dtype=np.float32)
    tTest = np.zeros_like(observedNormedFpc, dtype=np.float32)
    valid_stderr = ts_stderr >= 0.2
    valid_std = ts_std >= 0.2
    sTest[valid_stderr] = (observedNormedFpc[valid_stderr] - predictedNormedFpc[valid_stderr]) / ts_stderr[valid_stderr]
    tTest[valid_std] = (observedNormedFpc[valid_std] - ts_mean[valid_std]) / ts_std[valid_std]

    # Spectral index from start/end DB8: bands 2,3,5,6 are indices [1,2,4,5] in the db8 stack.
    # The weights and log1p() transform follow the legacy model.
    refStart = ref_start
    refEnd = ref_end
    spectralIndex = (
        (0.77801094 * np.log1p(refStart[1])) +
        (1.7713253  * np.log1p(refStart[2])) +
        (2.0714311  * np.log1p(refStart[4])) +
        (2.5403550  * np.log1p(refStart[5])) +
        (-0.2996241 * np.log1p(refEnd[1])) +
        (-0.5447928 * np.log1p(refEnd[2])) +
        (-2.2842536 * np.log1p(refEnd[4])) +
        (-4.0177752 * np.log1p(refEnd[5]))
    ).astype(np.float32)

    combinedIndex = (-11.972499 * spectralIndex -
                     0.40357223 * fpcDiff -
                     5.2609715  * tTest -
                     4.3794265  * sTest).astype(np.float32)

    # Change class assignment according to legacy thresholds.
    # 10 = no clearing (default), 3 = FPC-only signal, 34..39 = increasing clearing confidence/strength.
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

    # Optional rule: force no-clearing where raw fpcStart < 108 (applies before nulling by reflectance zeros).
    if not args.omit_fpc_start_threshold:
        changeclass[fpc_start_raw < 108] = NO_CLEARING

    # Null out where reflectance has zeros in any band for start or end.
    refNullMask = (refStart == 0).any(axis=0) | (refEnd == 0).any(axis=0)
    changeclass[refNullMask] = NULL_CLEARING

    # Interpretation stretch (legacy scales) and clearing probability.
    spectralMean = float(np.mean(spectralIndex[spectralIndex != 0])) if np.any(spectralIndex != 0) else 0.0
    spectralStd  = float(np.std(spectralIndex[spectralIndex != 0])) if np.any(spectralIndex != 0) else 1.0
    sTestMean    = float(np.mean(sTest[sTest != 0])) if np.any(sTest != 0) else 0.0
    sTestStd     = float(np.std(sTest[sTest != 0])) if np.any(sTest != 0) else 1.0
    combMean     = float(np.mean(combinedIndex[combinedIndex != 0])) if np.any(combinedIndex != 0) else 0.0
    combStd      = float(np.std(combinedIndex[combinedIndex != 0])) if np.any(combinedIndex != 0) else 1.0

    spectralStretched = stretch(spectralIndex, spectralMean, spectralStd, 2, 1, 255, 0)
    sTestStretched     = stretch(sTest, sTestMean, sTestStd, 10, 1, 255, 0)
    combinedStretched  = stretch(combinedIndex, combMean, combStd, 10, 1, 255, 0)

    clearingProb = 200 * (1 - np.exp(-((0.01227 * combinedIndex) ** 3.18975)))
    clearingProb = np.round(clearingProb).astype(np.uint8)
    clearingProb[combinedIndex <= 0] = 0

    # Outputs (ENVI .img with legacy-compatible names)
    era = f"d{sd}{ed}"
    out_cls = stdProjFilename(f"lztmre_{scene}_{era}_dllmz.img")
    out_int = stdProjFilename(f"lztmre_{scene}_{era}_dljmz.img")
    Path(out_cls).parent.mkdir(parents=True, exist_ok=True)

    write_envi(out_cls, [changeclass], georef, dtype=gdal.GDT_Byte, nodata=0)
    write_envi(out_int, [spectralStretched, sTestStretched, combinedStretched, clearingProb], georef, dtype=gdal.GDT_Byte, nodata=0)

    if args.verbose:
        print(f"Baseline dates ({len(base_dates)}): {','.join(base_dates)}")
        print(f"Wrote: {out_cls}")
        print(f"Wrote: {out_int}")
    else:
        print(out_cls)
        print(out_int)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

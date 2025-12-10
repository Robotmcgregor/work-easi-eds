#!/usr/bin/env python
"""
Seasonal-window change detection using SR with selectable vegetation index (DLL/DLJ).

This generalizes the NDVI variant to support multiple vegetation indices:
  - NDVI: (NIR - RED) / (NIR + RED)
  - EVI:  2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)
  - SAVI: (1 + L) * (NIR - RED) / (NIR + RED + L) with soil brightness factor L
  - NDMI: (NIR - SWIR1) / (NIR + SWIR1)

Core method mirrors legacy EDS seasonal-window (FC version):
  - Build seasonal baseline from the chosen index (dc4-like arrays) within MMDD window
  - Normalize per-image to legacy style (mean~125, scale~15; 0 as nodata)
  - Compute s_test and t_test vs baseline
  - Compute legacy spectral index from start/end SR (db8 bands 2,3,5,6)
  - Combine indices with legacy coefficients (replace fpcDiff with index change)
  - Classify DLL (10, 3, 34..39) and build DLJ interpretation + clearing probability

Inputs:
  --veg-index {ndvi,evi,savi,ndmi}           Which vegetation index to use
  --scene pXXXrYYY                           Scene code
  --start-date YYYYMMDD                      Start date in window
  --end-date   YYYYMMDD                      End date in window
  --dc4-glob pattern                         Glob for per-date index rasters (single-band)
  --start-db8 path                           Start SR stack (db8)
  --end-db8   path                           End SR stack (db8)
  --window-start MMDD                        Window start (default: start MMDD)
  --window-end   MMDD                        Window end   (default: end MMDD)
  --lookback N                               Years to look back (default 10)
  --savi-L float                             SAVI soil brightness term L (default 0.5)
  --omit-start-threshold                     Skip start<108 => no-clearing rule
  --verbose                                  Print baseline dates and paths

Output naming matches legacy: lztmre_<scene>_d<start><end>_dllmz.img / _dljmz.img

All steps include explanatory comments for non-technical readers.
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
    """Extract YYYYMMDD from a file path (first 8-digit number starting with 19/20)."""
    import re
    filename = os.path.basename(path)
    m = re.search(r"(19|20)\d{6}", filename)
    if not m:
        raise ValueError(f"Cannot find a date in the file name: {path}")
    return m.group(0)


def decimal_year(yyyymmdd: str) -> float:
    """Convert YYYYMMDD to decimal year for trend calculations."""
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
        raise ValueError("MMDD must be 4 digits, e.g., '0701'")
    return int(mmdd[:2]), int(mmdd[2:])


def in_window(yyyymmdd: str, start_mmdd: str, end_mmdd: str) -> bool:
    """Return True if date is inside a seasonal window (can cross new year)."""
    m = int(yyyymmdd[4:6]); d = int(yyyymmdd[6:8])
    sm, sd = _parse_mmdd(start_mmdd); em, ed = _parse_mmdd(end_mmdd)
    if (sm, sd) <= (em, ed):
        return (m, d) >= (sm, sd) and (m, d) <= (em, ed)
    else:
        return (m, d) >= (sm, sd) or (m, d) <= (em, ed)


def load_raster(path: str) -> Tuple[np.ndarray, Tuple]:
    """Load a raster: returns (bands, rows, cols) array and georeferencing."""
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise IOError(f"Cannot open {path}")
    bands = [ds.GetRasterBand(i + 1).ReadAsArray() for i in range(ds.RasterCount)]
    arr = np.stack(bands, axis=0)
    georef = (ds.GetGeoTransform(can_return_null=True), ds.GetProjection())
    ds = None
    return arr, georef


def write_envi(out_path: str, arrays: List[np.ndarray], georef: Tuple, dtype=gdal.GDT_Byte, nodata=0) -> None:
    """Write arrays as ENVI raster (with a .hdr), keeping georeferencing."""
    gt, proj = georef; ysize, xsize = arrays[0].shape
    drv = gdal.GetDriverByName("ENVI"); ds = drv.Create(out_path, xsize, ysize, len(arrays), dtype)
    if gt: ds.SetGeoTransform(gt)
    if proj: ds.SetProjection(proj)
    for i, arr in enumerate(arrays, start=1):
        band = ds.GetRasterBand(i); band.WriteArray(arr); band.SetNoDataValue(nodata)
    ds.FlushCache(); ds = None


def normalise_image(arr: np.ndarray) -> np.ndarray:
    """Legacy-style normalisation: center at ~125 with scale ~15; 0 is nodata."""
    valid = arr > 0
    if not np.any(valid):
        return np.zeros_like(arr, dtype=np.uint8)
    mean = arr[valid].mean(); std = arr[valid].std()
    if std == 0: std = 1.0
    norm = 125 + 15 * (arr.astype(np.float32) - mean) / std
    norm = np.clip(norm, 1, 255).astype(np.uint8)
    norm[~valid] = 0
    return norm


# --- Vegetation index helpers ------------------------------------------------

def compute_vi(name: str, ref_bandstack: np.ndarray, L: float = 0.5) -> np.ndarray:
    """
    Compute a vegetation index from an SR band stack (db8-like), per image.
    Expected band order (0-based): [B2, B3, B4(RED), B5(NIR), B6(SWIR1), B7(SWIR2)]
    Returns a float32 array in the same shape as a single band.
    """
    B2 = ref_bandstack[0].astype(np.float32)
    B3 = ref_bandstack[1].astype(np.float32)
    B4 = ref_bandstack[2].astype(np.float32)  # RED
    B5 = ref_bandstack[3].astype(np.float32)  # NIR
    B6 = ref_bandstack[4].astype(np.float32)  # SWIR1

    if name == "ndvi":
        num = B5 - B4; den = B5 + B4 + 1e-6
        vi = num / den
    elif name == "evi":
        vi = 2.5 * (B5 - B4) / (B5 + 6.0 * B4 - 7.5 * B2 + 1.0 + 1e-6)
    elif name == "savi":
        vi = (1.0 + L) * (B5 - B4) / (B5 + B4 + L + 1e-6)
    elif name == "ndmi":
        vi = (B5 - B6) / (B5 + B6 + 1e-6)
    else:
        raise SystemExit(f"Unsupported veg index: {name}")

    # Map typical index [-1,1] into [0,200] then clip; 0 reserved for nodata
    scaled = np.clip((vi + 1.0) * 100.0, 0, 200).astype(np.float32)
    # Respect nodata in SR (any band zero -> nodata)
    nodata = (ref_bandstack == 0).any(axis=0)
    scaled[nodata] = 0.0
    return scaled


def spectral_index_legacy(refStart: np.ndarray, refEnd: np.ndarray) -> np.ndarray:
    """
    Legacy weighted spectral index from FC method, using log1p of SR bands.
    Uses bands [1,2,4,5] (0-based) which correspond to B2,B3,B6,B7 in a 6-band stack.
    """
    return (
        (0.77801094 * np.log1p(refStart[1]))
        + (1.7713253 * np.log1p(refStart[2]))
        + (2.0714311 * np.log1p(refStart[4]))
        + (2.5403550 * np.log1p(refStart[5]))
        + (-0.2996241 * np.log1p(refEnd[1]))
        + (-0.5447928 * np.log1p(refEnd[2]))
        + (-2.2842536 * np.log1p(refEnd[4]))
        + (-4.0177752 * np.log1p(refEnd[5]))
    ).astype(np.float32)


def timeseries_stats(norm_list: List[np.ndarray], date_list: List[str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    stack = np.stack([a.astype(np.float32) for a in norm_list], axis=0)
    mean = stack.mean(axis=0); std = stack.std(axis=0)
    n = stack.shape[0]
    stderr = std / math.sqrt(n) if n > 1 else np.zeros_like(mean)
    if n > 1:
        t = np.array([decimal_year(d) for d in date_list], dtype=np.float32)
        t_mean = t.mean(); denom = np.sum((t - t_mean) ** 2)
        if denom == 0:
            slope = np.zeros_like(mean); intercept = mean.copy()
        else:
            y_mean = mean
            slope = np.sum(((t - t_mean)[:, None, None]) * (stack - y_mean), axis=0) / denom
            intercept = y_mean - slope * t_mean
    else:
        slope = np.zeros_like(mean); intercept = mean.copy()
    return mean, std, stderr, slope, intercept


def stretch(img: np.ndarray, mean: float, stddev: float, numStdDev: float, minVal: int, maxVal: int, ignoreVal: float) -> np.ndarray:
    stretched = minVal + (img - mean + stddev * numStdDev) * (maxVal - minVal) / (stddev * 2 * numStdDev)
    stretched = np.clip(stretched, minVal, maxVal).astype(np.float32)
    stretched[img == ignoreVal] = 0
    return stretched.astype(np.uint8)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Seasonal-window change detection (SR) with selectable veg index")
    ap.add_argument("--veg-index", choices=["ndvi", "evi", "savi", "ndmi"], default="ndvi")
    ap.add_argument("--scene", required=True)
    ap.add_argument("--start-date", required=True)
    ap.add_argument("--end-date", required=True)
    ap.add_argument("--dc4-glob", help="Glob for per-date index rasters (single-band, scaled to 0..200)")
    ap.add_argument("--start-db8")
    ap.add_argument("--end-db8")
    ap.add_argument("--window-start")
    ap.add_argument("--window-end")
    ap.add_argument("--lookback", type=int, default=10)
    ap.add_argument("--savi-L", type=float, default=0.5)
    ap.add_argument("--omit-start-threshold", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    scene = args.scene.lower(); sd = args.start_date; ed = args.end_date
    ws = args.window_start or sd[4:]; we = args.window_end or ed[4:]

    # Resolve SR reflectance stacks (db8)
    if args.start_db8 and args.end_db8:
        start_db8 = args.start_db8; end_db8 = args.end_db8
    else:
        start_db8 = stdProjFilename(f"lztmre_{scene}_{sd}_db8mz.img")
        end_db8   = stdProjFilename(f"lztmre_{scene}_{ed}_db8mz.img")
    if not os.path.exists(start_db8) or not os.path.exists(end_db8):
        raise SystemExit("Start/end db8 files not found; provide --start-db8/--end-db8 or build them.")

    # Resolve per-date index rasters (dc4-like)
    if args.dc4_glob:
        dc4_files = sorted(glob.glob(args.dc4_glob))
    else:
        base = Path(stdProjFilename(f"lztmre_{scene}_00000000_dc4mz.img")).parent
        dc4_files = sorted(glob.glob(str(base / f"lztmre_{scene}_*_dc4mz.img")))
    if not dc4_files:
        raise SystemExit("No per-date index rasters found (dc4)")

    # Load reflectance and index rasters; crop to common shape
    ref_start, georef = load_raster(start_db8)
    ref_end, _ = load_raster(end_db8)

    raw_idx = []; dates = []
    for p in dc4_files:
        arr, _ = load_raster(p)
        if arr.shape[0] != 1:
            raise SystemExit(f"Index rasters must be single band: {p}")
        raw_idx.append(arr[0]); dates.append(parse_date(p))

    ys = []; xs = []
    for a in [ref_start, ref_end] + raw_idx:
        if a.ndim == 3:
            _, y, x = a.shape
        else:
            y, x = a.shape
        ys.append(y); xs.append(x)
    min_y = min(ys); min_x = min(xs)

    def crop(a):
        return a[..., :min_y, :min_x] if a.ndim == 3 else a[:min_y, :min_x]

    ref_start = crop(ref_start).astype(np.float32)
    ref_end   = crop(ref_end).astype(np.float32)
    raw_idx   = [crop(a) for a in raw_idx]

    # Build seasonal baseline: one image per prior year in window, up to lookback
    end_year = int(ed[:4]); start_cutoff = sd
    by_year = {}
    for d, a in zip(dates, raw_idx):
        y = int(d[:4])
        if y < end_year - args.lookback + 1 or y > end_year: continue
        if d > start_cutoff: continue
        if not in_window(d, ws, we): continue
        by_year.setdefault(y, []).append((d, a))

    tm, td = int(we[:2]), int(we[2:])
    def md_dist(d: str) -> int:
        return abs((int(d[4:6]) - tm) * 31 + (int(d[6:8]) - td))

    base_dates: List[str] = []; base_raw: List[np.ndarray] = []
    for y in sorted(by_year.keys()):
        lst = by_year[y]
        if lst:
            d, a = sorted(lst, key=lambda t: md_dist(t[0]))[0]
            base_dates.append(d); base_raw.append(a)
    if len(base_dates) < 2:
        base_dates = [d for d in dates if (d <= start_cutoff and in_window(d, ws, we))]
        base_raw = [a for d, a in zip(dates, raw_idx) if (d <= start_cutoff and in_window(d, ws, we))]
        if len(base_dates) < 2:
            raise SystemExit("Baseline too small (<2 images) after seasonal filtering")

    # Normalise baseline and compute time-series stats
    base_norm = [normalise_image(a) for a in base_raw]
    ts_mean, ts_std, ts_stderr, ts_slope, ts_intercept = timeseries_stats(base_norm, base_dates)

    # Select start/end index images (closest within window)
    def nearest_idx(target: str, pool_dates: List[str]) -> int:
        if target in pool_dates: return pool_dates.index(target)
        best = None
        import datetime
        def to_date(s): return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        for i, d in enumerate(pool_dates):
            if not in_window(d, ws, we): continue
            dist = abs((to_date(d) - to_date(target)).days)
            if best is None or dist < best[0]: best = (dist, i)
        return best[1] if best else 0

    idx_start = nearest_idx(sd, dates); idx_end = nearest_idx(ed, dates)
    start_raw = raw_idx[idx_start]; end_raw = raw_idx[idx_end]
    start_norm = normalise_image(start_raw); end_norm = normalise_image(end_raw)

    # Index change (analogue of fpcDiff)
    index_diff = end_norm.astype(np.float32) - start_norm.astype(np.float32)

    # Legacy spectral index from SR start/end
    spectralIndex = spectral_index_legacy(ref_start, ref_end)

    # Legacy-style tests (using the chosen veg index stack)
    sTest = np.zeros_like(end_norm, dtype=np.float32)
    tTest = np.zeros_like(end_norm, dtype=np.float32)
    valid_stderr = ts_stderr >= 0.2; valid_std = ts_std >= 0.2
    prediction_decimal_year = decimal_year(ed)
    predictedNormedIndex = ts_intercept + ts_slope * prediction_decimal_year
    observedNormedIndex = end_norm.astype(np.float32)
    sTest[valid_stderr] = (observedNormedIndex[valid_stderr] - predictedNormedIndex[valid_stderr]) / ts_stderr[valid_stderr]
    tTest[valid_std]    = (observedNormedIndex[valid_std] - ts_mean[valid_std]) / ts_std[valid_std]

    # Combined index with legacy coefficients (replace fpcDiff with index_diff)
    combinedIndex = (
        -11.972499 * spectralIndex
        - 0.40357223 * index_diff
        - 5.2609715  * tTest
        - 4.3794265  * sTest
    ).astype(np.float32)

    # DLL classes (legacy thresholds)
    NO_CLEARING = 10; NULL_CLEARING = 0
    changeclass = np.full(spectralIndex.shape, NO_CLEARING, dtype=np.uint8)
    changeclass[combinedIndex > 21.80] = 34
    changeclass[(combinedIndex > 27.71) & (sTest < -0.27) & (spectralIndex < -0.86)] = 35
    changeclass[(combinedIndex > 33.40) & (sTest < -0.60) & (spectralIndex < -1.19)] = 36
    changeclass[(combinedIndex > 39.54) & (sTest < -1.01) & (spectralIndex < -1.50)] = 37
    changeclass[(combinedIndex > 47.05) & (sTest < -1.55) & (spectralIndex < -1.84)] = 38
    changeclass[(combinedIndex > 58.10) & (sTest < -2.34) & (spectralIndex < -2.27)] = 39

    # Index-only class 3 (analogue of FPC-only)
    indexDiffStdErr = -index_diff * ts_stderr
    changeclass[(tTest > -1.70) & (indexDiffStdErr > 740)] = 3

    # Optional rule: start<108 => force no clearing
    if not args.omit_start_threshold:
        changeclass[start_raw < 108] = NO_CLEARING

    # Null out where reflectance has zeros (outside valid SR data)
    refNullMask = (ref_start == 0).any(axis=0) | (ref_end == 0).any(axis=0)
    changeclass[refNullMask] = NULL_CLEARING

    # Interpretation layers and clearing probability (legacy)
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

    # Include the tile (scene) and the vegetation index used in output names
    era = f"d{sd}{ed}"; base_dir = Path(start_db8).parent
    out_base = f"lztmre_{scene}_{era}_vi-{args.veg_index}"
    out_cls = stdProjFilename(str(base_dir / f"{out_base}_dllmz.img"))
    out_int = stdProjFilename(str(base_dir / f"{out_base}_dljmz.img"))
    Path(out_cls).parent.mkdir(parents=True, exist_ok=True)

    write_envi(out_cls, [changeclass], georef, dtype=gdal.GDT_Byte, nodata=0)
    write_envi(out_int, [spectralStretched, sTestStretched, combinedStretched, clearingProb], georef, dtype=gdal.GDT_Byte, nodata=0)

    # Lightweight JSON provenance log
    try:
        import json
        log = {
            "scene": scene,
            "start_date": sd,
            "end_date": ed,
            "process": f"vi-{args.veg_index}",
            "parameters": {
                "savi_L": args.savi_L if args.veg_index == "savi" else None
            },
            "window_start": ws,
            "window_end": we,
            "lookback_years": args.lookback,
            "baseline_dates": base_dates,
            "selected_start_date": dates[idx_start],
            "selected_end_date": dates[idx_end],
            "outputs": {
                "dll": out_cls,
                "dlj": out_int
            }
        }
        log_path = os.path.splitext(out_cls)[0] + "_log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        if args.verbose:
            print(f"Wrote: {log_path}")
    except Exception as e:
        print(f"[WARN] Failed to write log JSON: {e}")

    if args.verbose:
        print(f"Baseline dates ({len(base_dates)}): {','.join(base_dates)}")
        print(f"Wrote: {out_cls}"); print(f"Wrote: {out_int}")
    else:
        print(out_cls); print(out_int)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

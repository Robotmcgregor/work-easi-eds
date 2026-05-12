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


def _finite_percentiles(values: np.ndarray, percentiles: list[float]) -> list[float]:
    v = values.astype(np.float64, copy=False)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return [float("nan") for _ in percentiles]
    return [float(x) for x in np.percentile(v, percentiles)]


def _print_stack_summary(label: str, arr: np.ndarray, *, band_indices_0based: list[int] | None = None) -> None:
    """Lightweight numeric summary to help diagnose scaling/masking."""
    if arr.ndim == 2:
        arr = arr[np.newaxis, :, :]

    print(f"[VALIDATION] {label}: dtype={arr.dtype} shape={tuple(arr.shape)}")
    if band_indices_0based is None:
        band_indices_0based = list(range(arr.shape[0]))

    for bi in band_indices_0based:
        if bi < 0 or bi >= arr.shape[0]:
            print(f"[VALIDATION] {label}: band[{bi+1}] (1-based) not present")
            continue
        b = arr[bi]
        # Common for these products: 0 used as nodata/fill. Show both all-values
        # and nonzero-only summaries.
        p_all = _finite_percentiles(b, [0, 1, 5, 50, 95, 99, 100])
        b_nz = b[(b != 0) & np.isfinite(b)]
        p_nz = _finite_percentiles(b_nz, [0, 1, 5, 50, 95, 99, 100])
        print(
            f"[VALIDATION] {label}: band[{bi+1}] p(min,p01,p05,p50,p95,p99,max)="
            f"({p_all[0]:.6g},{p_all[1]:.6g},{p_all[2]:.6g},{p_all[3]:.6g},{p_all[4]:.6g},{p_all[5]:.6g},{p_all[6]:.6g})"
        )
        print(
            f"[VALIDATION] {label}: band[{bi+1}] nonzero p(min,p01,p05,p50,p95,p99,max)="
            f"({p_nz[0]:.6g},{p_nz[1]:.6g},{p_nz[2]:.6g},{p_nz[3]:.6g},{p_nz[4]:.6g},{p_nz[5]:.6g},{p_nz[6]:.6g})"
        )


def _print_metric_summary(label: str, arr: np.ndarray, *, treat_zero_as_nodata: bool = True) -> None:
    a = arr.astype(np.float64, copy=False)
    finite = np.isfinite(a)
    if treat_zero_as_nodata:
        finite &= (a != 0)

    total = a.size
    valid = int(np.count_nonzero(finite))
    pct_valid = (valid / total * 100.0) if total else 0.0
    print(f"[VALIDATION] {label}: valid={valid}/{total} ({pct_valid:.3f}%)")
    if valid == 0:
        return
    v = a[finite]
    p = np.percentile(v, [0, 1, 5, 50, 95, 99, 100])
    print(
        f"[VALIDATION] {label}: p(min,p01,p05,p50,p95,p99,max)="
        f"({p[0]:.6g},{p[1]:.6g},{p[2]:.6g},{p[3]:.6g},{p[4]:.6g},{p[5]:.6g},{p[6]:.6g})"
    )


def _print_gdal_info(label: str, path: str) -> None:
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        print(f"[VALIDATION] {label}: cannot open {path}")
        return
    drv = ds.GetDriver().ShortName if ds.GetDriver() else "(unknown)"
    proj = ds.GetProjection() or ""
    gt = ds.GetGeoTransform(can_return_null=True)
    print(f"[VALIDATION] {label}: path={path}")
    print(f"[VALIDATION] {label}: driver={drv} size=({ds.RasterXSize},{ds.RasterYSize}) bands={ds.RasterCount}")
    if gt:
        print(f"[VALIDATION] {label}: geotransform={gt}")
    if proj:
        proj_snip = proj.replace("\n", " ")
        if len(proj_snip) > 160:
            proj_snip = proj_snip[:160] + "..."
        print(f"[VALIDATION] {label}: projection={proj_snip}")
    # Print datatype + nodata for the first few bands
    for i in range(1, min(ds.RasterCount, 6) + 1):
        b = ds.GetRasterBand(i)
        dt_name = gdal.GetDataTypeName(b.DataType)
        nd = b.GetNoDataValue()
        print(f"[VALIDATION] {label}: band[{i}] dtype={dt_name} nodata={nd}")
    ds = None

def sanitise_sr_for_log(arr: np.ndarray, nodata: float = -9999.0) -> np.ndarray:
    """
    Prepare SR stack for legacy log1p spectral index.

    Key requirement: avoid NaNs propagating into global stats.

    - convert to float32
    - coerce nodata/fill/invalid values to 0 (legacy uses 0 as null)
    - coerce any negative values to 0 (reflectance should be >= 0)
    """
    out = arr.astype(np.float32, copy=True)
    out[~np.isfinite(out)] = 0.0
    # Common fill values
    out[out == nodata] = 0.0
    # Any negative reflectance is treated as nodata
    out[out < 0] = 0.0
    return out

# def write_envi(
#     out_path: str,
#     arrays: List[np.ndarray],
#     georef: Tuple,
#     dtype=gdal.GDT_Byte,
#     nodata=0,
# ) -> None:
#     """Write a multi-band raster in ENVI format."""
#     gt, proj = georef
#     ysize, xsize = arrays[0].shape
#     drv = gdal.GetDriverByName("ENVI")
#     ds = drv.Create(out_path, xsize, ysize, len(arrays), dtype)
#     if gt:
#         ds.SetGeoTransform(gt)
#     if proj:
#         ds.SetProjection(proj)
#     for i, arr in enumerate(arrays, start=1):
#         band = ds.GetRasterBand(i)
#         band.WriteArray(arr)
#         band.SetNoDataValue(nodata)
#     ds.FlushCache()
#     ds = None
def write_gtiff(
    out_path,
    arrays,
    georef,
    dtype=gdal.GDT_Byte,
    nodata=0,
    band_names: List[str] | None = None,
):
    gt, proj = georef

    ysize, xsize = arrays[0].shape

    drv = gdal.GetDriverByName("GTiff")

    ds = drv.Create(
        out_path,
        xsize,
        ysize,
        len(arrays),
        dtype,
        options=[
            "COMPRESS=LZW",
            "TILED=YES",
            "BIGTIFF=IF_SAFER"
        ],
    )

    if gt:
        ds.SetGeoTransform(gt)

    if proj:
        ds.SetProjection(proj)

    for i, arr in enumerate(arrays, start=1):
        band = ds.GetRasterBand(i)
        band.WriteArray(arr)
        band.SetNoDataValue(nodata)

        if band_names is not None:
            if len(band_names) != len(arrays):
                raise ValueError(
                    f"band_names length ({len(band_names)}) must match arrays length ({len(arrays)})"
                )
            band.SetDescription(str(band_names[i - 1]))

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

def write_diag_stats_csv(values: np.ndarray, out_csv: Path, *, thresholds=(2.5, 6.0, 10.0)) -> None:
    v = values.astype(np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        out_csv.write_text("metric,count\nndviDiffStdErr,0\n", encoding="utf-8")
        return

    pct = np.percentile(v, [0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100])
    lines = []
    lines.append("metric,count,mean,std,min,p01,p05,p10,p25,p50,p75,p90,p95,p99,max")
    lines.append(
        "ndviDiffStdErr,"
        f"{v.size},{v.mean():.6f},{v.std():.6f},"
        f"{pct[0]:.6f},{pct[1]:.6f},{pct[2]:.6f},{pct[3]:.6f},{pct[4]:.6f},"
        f"{pct[5]:.6f},{pct[6]:.6f},{pct[7]:.6f},{pct[8]:.6f},{pct[9]:.6f},{pct[10]:.6f}"
    )

    # threshold exceedance rates
    lines.append("")
    lines.append("threshold,percent_ge")
    for t in thresholds:
        lines.append(f"{t},{(np.mean(v >= t) * 100):.4f}")

    out_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_diag_bins_csv(values: np.ndarray, out_csv: Path, *, bins=256, clip_abs=200.0) -> None:
    v = values.astype(np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        out_csv.write_text("bin_left,bin_right,count\n", encoding="utf-8")
        return

    v = np.clip(v, -clip_abs, clip_abs)
    counts, edges = np.histogram(v, bins=bins)
    with out_csv.open("w", encoding="utf-8") as f:
        f.write("bin_left,bin_right,count\n")
        for i in range(len(counts)):
            f.write(f"{edges[i]:.6f},{edges[i+1]:.6f},{int(counts[i])}\n")

def write_stats_csv(values: np.ndarray, out_csv: Path) -> None:
    v = values[np.isfinite(values)]
    if v.size == 0:
        out_csv.write_text("count,mean,std,min,p01,p05,p10,p25,p50,p75,p90,p95,p99,max\n0\n")
        return

    pct = np.percentile(v, [1,5,10,25,50,75,90,95,99])
    lines = [
        "count,mean,std,min,p01,p05,p10,p25,p50,p75,p90,p95,p99,max",
        f"{v.size},{v.mean():.6f},{v.std():.6f},{v.min():.6f},"
        f"{pct[0]:.6f},{pct[1]:.6f},{pct[2]:.6f},{pct[3]:.6f},"
        f"{pct[4]:.6f},{pct[5]:.6f},{pct[6]:.6f},{pct[7]:.6f},{pct[8]:.6f},{v.max():.6f}",
        "",
        "threshold,percent_ge",
        f"2.5,{(np.mean(v >= 2.5) * 100):.4f}",
        f"4.0,{(np.mean(v >= 4.0) * 100):.4f}",
        f"6.0,{(np.mean(v >= 6.0) * 100):.4f}",
        f"10.0,{(np.mean(v >= 10.0) * 100):.4f}",
    ]
    out_csv.write_text("\n".join(lines) + "\n")


def write_bins_csv(values: np.ndarray, out_csv: Path, bins=256, clip=200.0) -> None:
    v = values[np.isfinite(values)]
    if v.size == 0:
        out_csv.write_text("bin_left,bin_right,count\n")
        return

    v = np.clip(v, -clip, clip)
    counts, edges = np.histogram(v, bins=bins)

    with out_csv.open("w") as f:
        f.write("bin_left,bin_right,count\n")
        for i in range(len(counts)):
            f.write(f"{edges[i]:.6f},{edges[i+1]:.6f},{counts[i]}\n")


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
    ap.add_argument("--diagnostics", action="store_true", help="Write diagnostic stats/histograms for ndviDiffStdErr")
    ap.add_argument("--vi-tag", default="vi-ndvi", help="Tag used in diagnostic filenames (default: vi-ndvi)")
    ap.add_argument("--diag-bins", type=int, default=256, help="Histogram bin count (default 256)")
    ap.add_argument("--diag-clip", type=float, default=200.0, help="Clip abs(values) for histograms (default 200)")
    ap.add_argument("--diagnostics-dir", help="Directory for diagnostic rasters, CSVs, and plots")

    args = ap.parse_args(argv)

    scene = args.scene.lower()
    sd = args.start_date
    ed = args.end_date
    ws = args.window_start or sd[4:]
    we = args.window_end or ed[4:]
    output_dir = Path.cwd()
    diagnostics_dir = Path(args.diagnostics_dir) if args.diagnostics_dir else (output_dir / "diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

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

    if args.verbose:
        _print_gdal_info("db8_start", start_db8)
        _print_gdal_info("db8_end", end_db8)
        # Legacy spectral index uses bands 2,3,5,6 (1-based). Our arrays are 0-based.
        _print_stack_summary("db8_start_raw", ref_start, band_indices_0based=[1, 2, 4, 5])
        _print_stack_summary("db8_end_raw", ref_end, band_indices_0based=[1, 2, 4, 5])

        # Heuristic hint for SR scaling: reflectance should typically be ~0..1 (or ~0..2 after offset)
        # whereas DN-scaled SR is often in the thousands.
        b5 = ref_start[4] if (ref_start.ndim == 3 and ref_start.shape[0] > 4) else None
        if b5 is not None:
            b5_nz = b5[(b5 != 0) & np.isfinite(b5)]
            if b5_nz.size:
                med = float(np.median(b5_nz))
                print(f"[VALIDATION] sr_scale_hint: start_db8 band5 median_nonzero={med:.6g} (expect ~0..1 if reflectance-scaled)")

    # Sanitise SR stacks so nodata/fill values do not break log1p()
    ref_start = sanitise_sr_for_log(ref_start, nodata=-9999.0)
    ref_end = sanitise_sr_for_log(ref_end, nodata=-9999.0)

    # Load NDVI dc4 images and crop to common shape
    raw_ndvi = []
    dates = []
    paths = []
    for p in dc4_files:
        arr, _ = load_raster(p)
        if arr.shape[0] != 1:
            raise SystemExit(f"dc4 (NDVI) must be single band: {p}")
        raw_ndvi.append(arr[0])
        dates.append(parse_date(p))
        paths.append(p)

    if args.verbose and raw_ndvi:
        # DC4 NDVI is expected in [0..200] (scaled from [-1..1]) with 0 as nodata.
        _print_gdal_info("dc4_ndvi_sample", dc4_files[0])
        _print_stack_summary("dc4_ndvi_sample", raw_ndvi[0])

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
    baseline_paths = []
    start_year = int(sd[:4])

    for year_offset in range(1, args.lookback + 1):
        baseline_year = start_year - year_offset
        candidates = [
            (p, d, fp) for p, d, fp in zip(raw_ndvi, dates, paths)
            if int(d[:4]) == baseline_year
            and in_window(d, ws, we)
            and d <= sd
        ]
        if candidates:
            chosen = min(candidates, key=lambda x: abs(int(x[1][4:]) - int(sd[4:])))
            baseline_ndvi.append(chosen[0])
            baseline_dates.append(chosen[1])
            baseline_paths.append(chosen[2])

    # Fallback if baseline is too small
    if len(baseline_ndvi) < 2:
        fallback = [
            (p, d, fp) for p, d, fp in zip(raw_ndvi, dates, paths)
            if in_window(d, ws, we) and d <= sd
        ]
        if len(fallback) >= 2:
            baseline_ndvi = [p for p, d, fp in sorted(fallback, key=lambda x: x[1])]
            baseline_dates = [d for p, d, fp in sorted(fallback, key=lambda x: x[1])]
            baseline_paths = [fp for p, d, fp in sorted(fallback, key=lambda x: x[1])]
        else:
            raise SystemExit("Insufficient baseline NDVI images")

    if args.verbose:
        print(f"[VALIDATION] baseline_ndvi_count: {len(baseline_ndvi)}")
        print(f"[VALIDATION] baseline_dates: {baseline_dates}")
        print(f"[VALIDATION] baseline_paths: {baseline_paths}")

    # Select start/end NDVI images
    start_candidates = [
        (p, d, fp) for p, d, fp in zip(raw_ndvi, dates, paths)
        if in_window(d, ws, we) and d <= sd and d not in baseline_dates
    ]
    end_candidates = [
        (p, d, fp) for p, d, fp in zip(raw_ndvi, dates, paths)
        if in_window(d, ws, we) and d >= ed and d not in baseline_dates
    ]

    if not start_candidates:
        start_ndvi, start_ndvi_date, start_ndvi_path = baseline_ndvi[-1], baseline_dates[-1], baseline_paths[-1]
    else:
        start_ndvi, start_ndvi_date, start_ndvi_path = min(start_candidates, key=lambda x: abs(int(x[1]) - int(sd)))

    if not end_candidates:
        end_ndvi, end_ndvi_date, end_ndvi_path = baseline_ndvi[-1], baseline_dates[-1], baseline_paths[-1]
    else:
        end_ndvi, end_ndvi_date, end_ndvi_path = min(end_candidates, key=lambda x: abs(int(x[1]) - int(ed)))

    if args.verbose:
        print(f"[VALIDATION] start_ndvi_date: {start_ndvi_date}")
        print(f"[VALIDATION] end_ndvi_date:   {end_ndvi_date}")
        print(f"[VALIDATION] start_ndvi_path: {start_ndvi_path}")
        print(f"[VALIDATION] end_ndvi_path:   {end_ndvi_path}")

        # Summarise chosen start/end NDVI values to diagnose masking/range.
        _print_stack_summary("ndvi_start_raw", start_ndvi)
        _print_stack_summary("ndvi_end_raw", end_ndvi)

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

    if args.verbose:
        # Summarise intermediate arrays to diagnose scaling/variance.
        _print_metric_summary("base_std", base_std, treat_zero_as_nodata=False)
        _print_metric_summary("base_stderr", base_stderr, treat_zero_as_nodata=False)
        print(
            f"[VALIDATION] valid_std_pct: {float(np.mean(base_std >= 0.2) * 100):.3f}% | "
            f"valid_stderr_pct: {float(np.mean(base_stderr >= 0.2) * 100):.3f}%"
        )
        _print_metric_summary("spectral_index", spectral_index, treat_zero_as_nodata=True)
        _print_metric_summary("ndvi_trend(norm_end-norm_start)", ndvi_trend, treat_zero_as_nodata=False)
        _print_metric_summary("t_test", t_test, treat_zero_as_nodata=True)
        _print_metric_summary("s_test", s_test, treat_zero_as_nodata=True)
        _print_metric_summary("combined_index", combined_index, treat_zero_as_nodata=True)

    # # --------------------------------------------------
    # # DIAGNOSTIC OUTPUT: raw combined index (UNSTRETCHED)
    # # --------------------------------------------------

    # out_base = f"lztmre_{scene}_d{sd}{ed}_{args.vi_tag}"
    # diag_dir = Path(stdProjFilename(f"{out_base}_dllmz.img")).parent / "diagnostics"

    # print("diag dir: ", diag_dir)
    # diag_dir.mkdir(exist_ok=True)

    # # diag_name = f"{args.scene}_d{sd}"

    # # combined_img = diag_dir / f"lztmre_{scene}_{sd}{ed}_combined_raw.img"

    # # # combined_out = stdProjFilename(
    # # #     f"lztmre_{scene}_{sd}_combined_raw.img"
    # # # )

    # # write_envi(
    # #     combined_img,
    # #     [combined_index],
    # #     georef,
    # #     dtype=gdal.GDT_Float32,
    # #     nodata=0
    # # )
    # combined_img = diag_dir / f"{platform}olre_{tile}_d{sd}{ed}_combined_raw_e{epsg}.tif"

    # write_gtiff(
    #     str(combined_img),
    #     [combined_index],
    #     georef,
    #     dtype=gdal.GDT_Float32,
    #     nodata=0,
    # )

    # print("file sent to ", combined_img)


    # # In legacy FC:
    # #  - spectral_term ≈ small, stable
    # #  - fc_term ≈ bounded (0–100ish)
    # # → combined values clustered near 20–60

    # # With NDVI:
    # #  - ndvi_term:
    # #  - can be negative
    # #  - can spike strongly
    # #  - has different variance

    # # → combined values now span –50 to 700+

    # # Clearing decision logic — mirror legacy DLL thresholds
    # NO_CLEARING = 10
    # NULL_CLEARING = 0
    # dll_class = np.full(spectral_index.shape, NO_CLEARING, dtype=np.uint8)
    # dll_class[combined_index > 21.80] = 34
    # dll_class[(combined_index > 27.71) & (s_test < -0.27) & (spectral_index < -0.86)] = 35
    # dll_class[(combined_index > 33.40) & (s_test < -0.60) & (spectral_index < -1.19)] = 36
    # dll_class[(combined_index > 39.54) & (s_test < -1.01) & (spectral_index < -1.50)] = 37
    # dll_class[(combined_index > 47.05) & (s_test < -1.55) & (spectral_index < -1.84)] = 38
    # dll_class[(combined_index > 58.10) & (s_test < -2.34) & (spectral_index < -2.27)] = 39

    # # NDVI-only class 3 (analogous to FPC-only): strong NDVI signal not explained by clearing thresholds
    # # ndviDiffStdErr = -ndvi_trend * base_stderr - original QLD calculation
    # # dll_class[(t_test > -1.70) & (ndviDiffStdErr > 740)] = 3

    # # ---- NDVI-only diagnostic metric (standardised change) ----
    # ndviDiffStdErr = -(ndvi_trend) / np.maximum(base_stderr, 0.2)

    # dll_class[(t_test > -1.70) & (ndviDiffStdErr > 6.0)] = 3   # you can tune this

    # # Output filenames (define early so diagnostics can use them)
    # # out_base = f"lztmre_{scene}_d{sd}{ed}_{args.vi_tag}"
    # # dll_path = stdProjFilename(f"{out_base}_dllmz.img")
    # # dlj_path = stdProjFilename(f"{out_base}_dljmz.img")

    # # NEW NAMING
    # tile = scene.lower()

    # # derive platform + epsg from end_db8 filename
    # import re
    # end_name = os.path.basename(end_db8)

    # m = re.match(r"(sl\d)olre_(p\d+r\d+)_\d{8}_ga0.*_e(\d+)\.tif", end_name)

    # if not m:
    #     raise RuntimeError(f"Could not parse GA0 filename: {end_name}")

    # platform = m.group(1)
    # epsg = m.group(3)

    # dll_path = f"{platform}olre_{tile}_d{sd}{ed}_dll_e{epsg}.tif"
    # dlj_path = f"{platform}olre_{tile}_d{sd}{ed}_dlj_e{epsg}.tif"


    # # ------------------ DIAGNOSTICS ------------------
    # if args.diagnostics:
    #     diag_mask = (
    #         np.isfinite(ndviDiffStdErr)
    #         & (base_stderr >= 0.2)
    #         & (norm_start > 0)
    #         & (norm_end > 0)
    #     )
    #     vals = ndviDiffStdErr[diag_mask]

    #     diag_dir = Path(stdProjFilename(f"{out_base}_dllmz.img")).parent / "diagnostics"

    #     print("diag dir: ", diag_dir)
    #     diag_dir.mkdir(exist_ok=True)

    #     diag_name = f"{args.scene}_d{sd}{ed}_{args.vi_tag}"

    #     stats_csv = diag_dir / f"{diag_name}_ndviDiffStdErr_stats.csv"
    #     bins_csv  = diag_dir / f"{diag_name}_ndviDiffStdErr_bins.csv"

    #     write_diag_stats_csv(vals, stats_csv)
    #     write_diag_bins_csv(vals, bins_csv, bins=args.diag_bins, clip_abs=args.diag_clip)

    #     print(f"[DIAG] Stats CSV: {stats_csv}")
    #     print(f"[DIAG] Bins  CSV: {bins_csv}")

    #     # Optional histogram PNG (never crash if matplotlib missing)
    #     try:
    #         import matplotlib.pyplot as plt

    #         vclip = np.clip(vals, -args.diag_clip, args.diag_clip)
    #         plt.figure()
    #         plt.hist(vclip, bins=args.diag_bins)
    #         plt.axvline(2.5, linestyle="--")
    #         plt.axvline(-2.5, linestyle="--")
    #         plt.title("ndviDiffStdErr histogram (clipped)")
    #         png_path = diag_dir / f"{diag_name}_ndviDiffStdErr.png"
    #         plt.savefig(png_path, dpi=150, bbox_inches="tight")
    #         plt.close()
    #         print(f"[DIAG] Histogram PNG: {png_path}")
    #     except Exception as e:
    #         print(f"[DIAG] Histogram skipped (matplotlib unavailable): {e}")
    # # ------------------ /DIAGNOSTICS ------------------


    # # Optional: force no-clearing where starting NDVI is very low
    # if not args.omit_ndvi_start_threshold:
    #     dll_class[norm_start < 108] = NO_CLEARING

    # # Interpretation (DLJ): stretch indices to uint8
    # # Interpretation layers & clearing probability — legacy-style
    # spectralMean = float(np.mean(spectral_index[spectral_index != 0])) if np.any(spectral_index != 0) else 0.0
    # spectralStd  = float(np.std(spectral_index[spectral_index != 0])) if np.any(spectral_index != 0) else 1.0
    # sTestMean    = float(np.mean(s_test[s_test != 0])) if np.any(s_test != 0) else 0.0
    # sTestStd     = float(np.std(s_test[s_test != 0])) if np.any(s_test != 0) else 1.0
    # combMean     = float(np.mean(combined_index[combined_index != 0])) if np.any(combined_index != 0) else 0.0
    # combStd      = float(np.std(combined_index[combined_index != 0])) if np.any(combined_index != 0) else 1.0

    # spectral_stretch = stretch(spectral_index, spectralMean, spectralStd, 2, 1, 255, 0)
    # trend_stretch     = stretch(s_test, sTestMean, sTestStd, 10, 1, 255, 0)
    # combined_stretch  = stretch(combined_index, combMean, combStd, 10, 1, 255, 0)

    # clearing_prob = 200 * (1 - np.exp(-((0.01227 * combined_index) ** 3.18975)))
    # clearing_prob = np.round(clearing_prob).astype(np.uint8)
    # clearing_prob[combined_index <= 0] = 0

    # # Output filenames
    # # Include the tile (scene) and the process used (vi=ndvi) in output names for traceability
    # # out_base = f"lztmre_{scene}_d{sd}{ed}_vi-ndvi"
    # # dll_path = stdProjFilename(f"{out_base}_dllmz.img")
    # # dlj_path = stdProjFilename(f"{out_base}_dljmz.img")

    # if args.verbose:
    #     print(f"[Output] DLL: {dll_path}")
    #     print(f"[Output] DLJ: {dlj_path}")

    # # Write outputs
    # # write_envi(dll_path, [dll_class], georef, dtype=gdal.GDT_Byte)
    # # write_envi(dlj_path, [spectral_stretch, trend_stretch, combined_stretch, clearing_prob], georef, dtype=gdal.GDT_Byte)

    # write_gtiff(dll_path, [dll_class], georef)

    # write_gtiff(
    #     dlj_path,
    #     [spectral_stretch, trend_stretch, combined_stretch, clearing_prob],
    #     georef
    # )
    # # Lightweight JSON provenance log for traceability
    # try:
    #     import json
    #     log = {
    #         "scene": scene,
    #         "start_date": sd,
    #         "end_date": ed,
    #         "process": "vi-ndvi",
    #         "window_start": ws,
    #         "window_end": we,
    #         "lookback_years": args.lookback,
    #         "baseline_dates": baseline_dates,
    #         "start_ndvi_date": start_ndvi_date,
    #         "end_ndvi_date": end_ndvi_date,
    #         "outputs": {
    #             "dll": dll_path,
    #             "dlj": dlj_path
    #         }
    #     }
    #     log_path = os.path.splitext(dll_path)[0] + "_log.json"
    #     with open(log_path, "w", encoding="utf-8") as f:
    #         json.dump(log, f, indent=2)
    #     if args.verbose:
    #         print(f"[Output] LOG: {log_path}")
    # except Exception as e:
    #     print(f"[WARN] Failed to write log JSON: {e}")

    # print(f"[OK] Completed: {dll_path}, {dlj_path}")
    # return 0

    
    # --------------------------------------------------
    # Derive final output naming once from end_db8
    # --------------------------------------------------
    tile = scene.lower()

    import re
    end_name = os.path.basename(end_db8)

    m = re.match(r"(sl\d)olre_(p\d+r\d+)_\d{8}_ga0.*_e(\d+)\.tif", end_name)
    if not m:
        raise RuntimeError(f"Could not parse GA0 filename: {end_name}")

    platform = m.group(1)   # e.g. sl8
    epsg = m.group(3)       # e.g. 32756

    dll_path = output_dir / f"{platform}olre_{tile}_d{sd}{ed}_dll_e{epsg}.tif"
    dlj_path = output_dir / f"{platform}olre_{tile}_d{sd}{ed}_dlj_e{epsg}.tif"

    # --------------------------------------------------
    # DIAGNOSTIC OUTPUT: raw combined index (UNSTRETCHED)
    # --------------------------------------------------
    combined_img = diagnostics_dir / f"{platform}olre_{tile}_d{sd}{ed}_combined_raw_e{epsg}.tif"

    write_gtiff(
        str(combined_img),
        [combined_index],
        georef,
        dtype=gdal.GDT_Float32,
        nodata=0,
    ) 

    print("file sent to ", combined_img)

    # In legacy FC:
    #  - spectral_term ≈ small, stable
    #  - fc_term ≈ bounded (0–100ish)
    # → combined values clustered near 20–60

    # With NDVI:
    #  - ndvi_term:
    #  - can be negative
    #  - can spike strongly
    #  - has different variance

    # → combined values now span –50 to 700+

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

    # NDVI-only diagnostic metric (standardised change)
    ndviDiffStdErr = -(ndvi_trend) / np.maximum(base_stderr, 0.2)
    dll_class[(t_test > -1.70) & (ndviDiffStdErr > 6.0)] = 3

    if args.verbose:
        _print_metric_summary("ndviDiffStdErr", ndviDiffStdErr, treat_zero_as_nodata=False)
        uniq, cnt = np.unique(dll_class, return_counts=True)
        parts = [f"{int(u)}:{int(c)}" for u, c in zip(uniq, cnt)]
        print(f"[VALIDATION] dll_class_counts: {' '.join(parts)}")

    # ------------------ DIAGNOSTICS ------------------
    if args.diagnostics:
        diag_mask = (
            np.isfinite(ndviDiffStdErr)
            & (base_stderr >= 0.2)
            & (norm_start > 0)
            & (norm_end > 0)
        )
        vals = ndviDiffStdErr[diag_mask]

        diag_name = f"{platform}olre_{tile}_d{sd}{ed}_{args.vi_tag}_e{epsg}"

        stats_csv = diagnostics_dir / f"{diag_name}_ndviDiffStdErr_stats.csv"
        bins_csv  = diagnostics_dir / f"{diag_name}_ndviDiffStdErr_bins.csv"

        write_diag_stats_csv(vals, stats_csv)
        write_diag_bins_csv(vals, bins_csv, bins=args.diag_bins, clip_abs=args.diag_clip)

        print(f"[DIAG] Stats CSV: {stats_csv}")
        print(f"[DIAG] Bins  CSV: {bins_csv}")

        try:
            import matplotlib.pyplot as plt

            vclip = np.clip(vals, -args.diag_clip, args.diag_clip)
            plt.figure()
            plt.hist(vclip, bins=args.diag_bins)
            plt.axvline(2.5, linestyle="--")
            plt.axvline(-2.5, linestyle="--")
            plt.title("ndviDiffStdErr histogram (clipped)")
            png_path = diagnostics_dir / f"{diag_name}_ndviDiffStdErr.png"
            plt.savefig(png_path, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"[DIAG] Histogram PNG: {png_path}")
        except Exception as e:
            print(f"[DIAG] Histogram skipped (matplotlib unavailable): {e}")
    # ------------------ /DIAGNOSTICS ------------------

    # Optional: force no-clearing where starting NDVI is very low
    if not args.omit_ndvi_start_threshold:
        dll_class[norm_start < 108] = NO_CLEARING

    # Interpretation (DLJ): stretch indices to uint8
    # Robust global stats: ignore zeros and any non-finite values.
    spec_vals = spectral_index[np.isfinite(spectral_index) & (spectral_index != 0)]
    stest_vals = s_test[np.isfinite(s_test) & (s_test != 0)]
    comb_vals = combined_index[np.isfinite(combined_index) & (combined_index != 0)]

    spectralMean = float(spec_vals.mean()) if spec_vals.size else 0.0
    spectralStd = float(spec_vals.std()) if spec_vals.size else 1.0
    sTestMean = float(stest_vals.mean()) if stest_vals.size else 0.0
    sTestStd = float(stest_vals.std()) if stest_vals.size else 1.0
    combMean = float(comb_vals.mean()) if comb_vals.size else 0.0
    combStd = float(comb_vals.std()) if comb_vals.size else 1.0

    # Final safety: no NaNs in the arrays we stretch.
    spectral_index = np.where(np.isfinite(spectral_index), spectral_index, 0).astype(np.float32)
    s_test = np.where(np.isfinite(s_test), s_test, 0).astype(np.float32)
    combined_index = np.where(np.isfinite(combined_index), combined_index, 0).astype(np.float32)

    spectral_stretch = stretch(spectral_index, spectralMean, spectralStd, 2, 1, 255, 0)
    trend_stretch    = stretch(s_test, sTestMean, sTestStd, 10, 1, 255, 0)
    combined_stretch = stretch(combined_index, combMean, combStd, 10, 1, 255, 0)

    clearing_prob = 200 * (1 - np.exp(-((0.01227 * combined_index) ** 3.18975)))
    clearing_prob = np.round(clearing_prob).astype(np.uint8)
    clearing_prob[combined_index <= 0] = 0

    if args.verbose:
        print(f"[Output] DLL: {dll_path}")
        print(f"[Output] DLJ: {dlj_path}")

    # Write outputs directly as GeoTIFF
    write_gtiff(
        str(dll_path),
        [dll_class],
        georef,
        dtype=gdal.GDT_Byte,
        nodata=0,
        band_names=["dll_class"],
    )

    write_gtiff(
        str(dlj_path),
        [spectral_stretch, trend_stretch, combined_stretch, clearing_prob],
        georef,
        dtype=gdal.GDT_Byte,
        nodata=0,
        band_names=["spectralIndex", "ndviTrend", "combinedIndex", "clearingProb"],
    )

    # Lightweight JSON provenance log
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
                "dll": str(dll_path),
                "dlj": str(dlj_path),
            },
        }
        log_path = output_dir / f"{platform}olre_{tile}_d{sd}{ed}_dll_log_e{epsg}.json"
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

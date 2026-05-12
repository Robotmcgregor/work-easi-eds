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
import posixpath
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


def _is_vsi_path(path: str) -> bool:
    return path.startswith("/vsi")


def _normalise_output_base(path: str) -> str:
    """Normalise output base path.

    Supports:
      - local paths
      - GDAL VSI paths such as /vsis3/bucket/prefix
      - convenience s3://bucket/prefix -> /vsis3/bucket/prefix
    """
    if path.startswith("s3://"):
        return "/vsis3/" + path[len("s3://") :].lstrip("/")
    if path.startswith("/vsi"):
        return path
    return os.path.expanduser(path)


def _join_out(base: str, name: str) -> str:
    base = base.rstrip("/\\")
    if _is_vsi_path(base):
        return posixpath.join(base, name)
    return str(Path(base) / name)


def _ensure_local_dir(path: str) -> None:
    if _is_vsi_path(path):
        return
    Path(path).mkdir(parents=True, exist_ok=True)


def _write_bytes_anywhere(path: str, data: bytes) -> None:
    """Write bytes to local filesystem or GDAL VSI path."""
    if _is_vsi_path(path):
        f = gdal.VSIFOpenL(path, "wb")
        if not f:
            raise IOError(f"Failed to open for write: {path}")
        try:
            gdal.VSIFWriteL(data, 1, len(data), f)
        finally:
            gdal.VSIFCloseL(f)
        return

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fp:
        fp.write(data)


def _write_text_anywhere(path: str, text: str, *, encoding: str = "utf-8") -> None:
    _write_bytes_anywhere(path, text.encode(encoding))


def _dataset_bounds(gt: Tuple[float, float, float, float, float, float], xsize: int, ysize: int) -> Tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax) bounds for a north-up geotransform."""
    xmin = gt[0]
    xres = gt[1]
    ymax = gt[3]
    yres = gt[5]
    xmax = xmin + xres * xsize
    ymin = ymax + yres * ysize
    return (xmin, ymin, xmax, ymax)


def _georef_nearly_equal(a: Tuple | None, b: Tuple | None, *, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        try:
            if abs(float(x) - float(y)) > tol:
                return False
        except Exception:
            if x != y:
                return False
    return True


def load_single_band_raster(
    path: str,
    *,
    align_to_path: str | None = None,
    resample: str = "bilinear",
    src_nodata: float | None = -9999.0,
    dst_nodata: float | None = -9999.0,
) -> Tuple[np.ndarray, bool]:
    """Load a single-band raster; optionally warp it onto the grid of align_to_path."""
    ds = gdal.Open(path, gdal.GA_ReadOnly)
    if ds is None:
        raise IOError(f"Cannot open {path}")
    if ds.RasterCount != 1:
        raise ValueError(f"Expected 1 band in {path}; got {ds.RasterCount}")

    if not align_to_path:
        arr = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        return arr, False

    ref = gdal.Open(align_to_path, gdal.GA_ReadOnly)
    if ref is None:
        ds = None
        raise IOError(f"Cannot open reference dataset {align_to_path}")

    src_gt = ds.GetGeoTransform(can_return_null=True)
    src_proj = ds.GetProjection() or ""
    ref_gt = ref.GetGeoTransform(can_return_null=True)
    ref_proj = ref.GetProjection() or ""

    # If already aligned (same proj + very similar geotransform + same shape), skip warp.
    if (
        (src_proj == ref_proj)
        and _georef_nearly_equal(src_gt, ref_gt, tol=1e-6)
        and ds.RasterXSize == ref.RasterXSize
        and ds.RasterYSize == ref.RasterYSize
    ):
        arr = ds.GetRasterBand(1).ReadAsArray()
        ds = None
        ref = None
        return arr, False

    alg_map = {
        "nearest": gdal.GRA_NearestNeighbour,
        "bilinear": gdal.GRA_Bilinear,
        "cubic": gdal.GRA_Cubic,
    }
    if resample not in alg_map:
        raise ValueError(f"Unsupported resample='{resample}' (choose from {sorted(alg_map.keys())})")

    if not ref_gt:
        ds = None
        ref = None
        raise ValueError(f"Reference dataset {align_to_path} has no geotransform")

    bounds = _dataset_bounds(ref_gt, ref.RasterXSize, ref.RasterYSize)

    warped = gdal.Warp(
        "",
        ds,
        format="MEM",
        dstSRS=ref_proj,
        outputBounds=bounds,
        width=ref.RasterXSize,
        height=ref.RasterYSize,
        resampleAlg=alg_map[resample],
        srcNodata=src_nodata,
        dstNodata=dst_nodata,
    )
    ds = None
    ref = None
    if warped is None:
        raise RuntimeError(f"gdal.Warp failed for {path} -> {align_to_path}")

    arr = warped.GetRasterBand(1).ReadAsArray()
    warped = None
    return arr, True

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


def infer_sr_scale_factor(sr_stack: np.ndarray) -> float:
    """Infer an SR scale factor for GA0-like SR stacks.

    Many GA0 SR products encode reflectance as reflectance*10000 (0..10000).
    The legacy coefficients expect reflectance-scale magnitudes before log1p().

    Heuristic: if the median nonzero of band 5 (NIR, 1-based) is > ~2, assume
    scale=10000.
    """
    if sr_stack.ndim != 3 or sr_stack.shape[0] < 5:
        return 1.0

    b5 = sr_stack[4].astype(np.float32, copy=False)
    b5 = b5[np.isfinite(b5) & (b5 != 0)]
    if b5.size == 0:
        return 1.0
    med = float(np.median(b5))
    return 10000.0 if med > 2.0 else 1.0

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
    
    Supports both:
      - legacy scaled NDVI in [0, 200] (representing [-1, 1]) where 0 is often nodata
      - float NDVI in [-1, 1] with nodata typically -9999

    We normalize using the same approach as FPC: center at 125 with scale ~= 15.
    """
    a = arr.astype(np.float32, copy=False)
    finite = np.isfinite(a)

    # Common nodata sentinel used by our pipeline after warping.
    nodata_mask = a <= -9990.0

    # Decide which NDVI encoding we have.
    v = a[finite & ~nodata_mask]
    if v.size == 0:
        return np.zeros_like(a, dtype=np.uint8)

    p99_abs = float(np.percentile(np.abs(v), 99))

    if p99_abs <= 1.5:
        # Float NDVI in approx [-1, 1]. Do NOT discard negative NDVI.
        scaled = (a + 1.0) * 100.0  # [-1,1] -> [0,200]
        valid = finite & ~nodata_mask
    else:
        # Assume legacy 0..200 encoding. In this regime, 0 is typically nodata/fill.
        scaled = a
        valid = finite & (a > 0)

    if not np.any(valid):
        return np.zeros_like(a, dtype=np.uint8)

    mean = float(np.mean(scaled[valid]))
    std = float(np.std(scaled[valid]))
    if std == 0 or not np.isfinite(std):
        std = 1.0

    norm = 125.0 + 15.0 * (scaled - mean) / std
    norm = np.clip(norm, 1, 255).astype(np.uint8)
    norm[~valid] = 0
    return norm


def timeseries_stats(
    norm_list: List[np.ndarray],
    date_list: List[str],
    *,
    include_nodata_zeros: bool = False,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute baseline statistics across normalized NDVI stack.

    Normalised NDVI uses 0 as nodata. By default we IGNORE zeros when computing
    baseline mean/std/stderr and regression slope/intercept.

    Set include_nodata_zeros=True to force legacy behaviour (treat zeros as data).

    Returns: mean, std, stderr, slope, intercept, n_valid
    """
    stack = np.stack([a.astype(np.float32) for a in norm_list], axis=0)
    n_total = int(stack.shape[0])

    if include_nodata_zeros:
        mean = stack.mean(axis=0)
        std = stack.std(axis=0)
        n_valid = np.full(mean.shape, n_total, dtype=np.int16)
        if n_total > 1:
            stderr = std / math.sqrt(n_total)
        else:
            stderr = np.zeros_like(mean)

        if n_total > 1:
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

        return mean, std, stderr, slope, intercept, n_valid

    # Default (improved): ignore nodata zeros
    valid = stack > 0
    n_valid = valid.sum(axis=0).astype(np.int16)
    n_valid_f = n_valid.astype(np.float32)

    sum_y = (stack * valid).sum(axis=0)
    mean = np.zeros_like(sum_y, dtype=np.float32)
    mean[n_valid > 0] = (sum_y[n_valid > 0] / n_valid_f[n_valid > 0]).astype(np.float32)

    # std over valid observations only
    resid = (stack - mean[None, :, :])
    var = np.zeros_like(mean, dtype=np.float32)
    if np.any(n_valid > 0):
        sse = ((resid * resid) * valid).sum(axis=0)
        var[n_valid > 0] = (sse[n_valid > 0] / n_valid_f[n_valid > 0]).astype(np.float32)
    std = np.sqrt(var, dtype=np.float32)

    stderr = np.zeros_like(std, dtype=np.float32)
    mask2 = n_valid > 1
    if np.any(mask2):
        stderr[mask2] = std[mask2] / np.sqrt(n_valid_f[mask2])

    # Per-pixel masked linear regression (closed form) using only valid dates
    slope = np.zeros_like(mean, dtype=np.float32)
    intercept = np.zeros_like(mean, dtype=np.float32)

    if n_total > 1:
        t = np.array([decimal_year(d) for d in date_list], dtype=np.float32)
        tt = (t * t).astype(np.float32)

        sum_t = ((t[:, None, None]) * valid).sum(axis=0)
        sum_tt = ((tt[:, None, None]) * valid).sum(axis=0)
        sum_ty = ((t[:, None, None]) * (stack * valid)).sum(axis=0)

        den = (n_valid_f * sum_tt) - (sum_t * sum_t)
        ok = (n_valid >= 2) & (den != 0)
        if np.any(ok):
            slope[ok] = ((n_valid_f[ok] * sum_ty[ok]) - (sum_t[ok] * sum_y[ok])) / den[ok]
            intercept[ok] = (sum_y[ok] - slope[ok] * sum_t[ok]) / n_valid_f[ok]

        # For pixels with <2 obs, fall back to mean and zero slope.
        ok0 = (n_valid == 1)
        if np.any(ok0):
            intercept[ok0] = mean[ok0]

    else:
        # Single baseline image
        intercept[n_valid > 0] = mean[n_valid > 0]

    return mean, std, stderr, slope, intercept, n_valid


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

def write_diag_stats_csv(values: np.ndarray, out_csv: str | Path, *, thresholds=(2.5, 6.0, 10.0)) -> None:
    v = values.astype(np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        _write_text_anywhere(str(out_csv), "metric,count\nndviDiffStdErr,0\n", encoding="utf-8")
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

    _write_text_anywhere(str(out_csv), "\n".join(lines) + "\n", encoding="utf-8")


def write_diag_bins_csv(values: np.ndarray, out_csv: str | Path, *, bins=256, clip_abs=200.0) -> None:
    v = values.astype(np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        _write_text_anywhere(str(out_csv), "bin_left,bin_right,count\n", encoding="utf-8")
        return

    v = np.clip(v, -clip_abs, clip_abs)
    counts, edges = np.histogram(v, bins=bins)
    lines = ["bin_left,bin_right,count"]
    for i in range(len(counts)):
        lines.append(f"{edges[i]:.6f},{edges[i+1]:.6f},{int(counts[i])}")
    _write_text_anywhere(str(out_csv), "\n".join(lines) + "\n", encoding="utf-8")

def write_stats_csv(values: np.ndarray, out_csv: str | Path) -> None:
    v = values[np.isfinite(values)]
    if v.size == 0:
        _write_text_anywhere(str(out_csv), "count,mean,std,min,p01,p05,p10,p25,p50,p75,p90,p95,p99,max\n0\n")
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
    _write_text_anywhere(str(out_csv), "\n".join(lines) + "\n")


def write_bins_csv(values: np.ndarray, out_csv: str | Path, bins=256, clip=200.0) -> None:
    v = values[np.isfinite(values)]
    if v.size == 0:
        _write_text_anywhere(str(out_csv), "bin_left,bin_right,count\n")
        return

    v = np.clip(v, -clip, clip)
    counts, edges = np.histogram(v, bins=bins)

    lines = ["bin_left,bin_right,count"]
    for i in range(len(counts)):
        lines.append(f"{edges[i]:.6f},{edges[i+1]:.6f},{int(counts[i])}")
    _write_text_anywhere(str(out_csv), "\n".join(lines) + "\n")


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
    ap.add_argument(
        "--output-dir",
        help="Directory/prefix for outputs. Supports local paths and S3 via s3://bucket/prefix or /vsis3/bucket/prefix",
    )
    ap.add_argument(
        "--no-align-dc4-to-db8",
        action="store_true",
        help="Disable warping dc4 NDVI rasters onto the start-db8 grid (recommended to keep aligned)",
    )
    ap.add_argument(
        "--dc4-resample",
        default="bilinear",
        choices=["nearest", "bilinear", "cubic"],
        help="Resampling used when aligning dc4 to db8 grid (default: bilinear)",
    )

    ap.add_argument(
        "--sr-scale",
        type=float,
        default=None,
        help=(
            "MANUAL override for SR scaling. Divides SR bands by this factor before log1p() "
            "(e.g. 10000 for reflectance*10000 products). If omitted, scaling is auto-detected "
            "unless --no-auto-sr-scale is set."
        ),
    )
    ap.add_argument(
        "--no-auto-sr-scale",
        action="store_true",
        help=(
            "Disable SR scale auto-detection and FORCE no scaling (sr_scale_factor=1). "
            "By default, scaling is auto-detected and reflectance*10000 products are rescaled."
        ),
    )

    ap.add_argument(
        "--baseline-include-nodata",
        action="store_true",
        help=(
            "Use LEGACY baseline statistics behaviour: include nodata zeros when computing baseline mean/std/stderr/slope. "
            "Default (recommended) ignores zeros (treats 0 as nodata)."
        ),
    )

    args = ap.parse_args(argv)

    scene = args.scene.lower()
    sd = args.start_date
    ed = args.end_date
    ws = args.window_start or sd[4:]
    we = args.window_end or ed[4:]
    output_base = _normalise_output_base(args.output_dir or os.getcwd())
    diagnostics_base = _normalise_output_base(args.diagnostics_dir or _join_out(output_base, "diagnostics"))
    _ensure_local_dir(output_base)
    _ensure_local_dir(diagnostics_base)

    if args.verbose:
        print(f"[VALIDATION] output_dir: {output_base}")
        print(f"[VALIDATION] diagnostics_dir: {diagnostics_base}")

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

    # ------------------------------------------------------------------
    # SR scale handling (high impact for legacy log1p spectral coefficients)
    # ------------------------------------------------------------------
    if args.sr_scale is not None:
        sr_scale = float(args.sr_scale)
        sr_scale_source = "manual"
    elif args.no_auto_sr_scale:
        sr_scale = 1.0
        sr_scale_source = "no-auto"
    else:
        sr_scale = infer_sr_scale_factor(ref_start)
        sr_scale_source = "auto"

    def _fmt_factor_for_name(x: float) -> str:
        try:
            xi = int(round(float(x)))
            if abs(float(x) - float(xi)) < 1e-6:
                return str(xi)
        except Exception:
            pass
        return (f"{float(x):.6g}").replace(".", "p").replace("-", "m")

    diag_suffix = f"sr-{sr_scale_source}-{_fmt_factor_for_name(sr_scale)}_base-{'legacy' if args.baseline_include_nodata else 'nodataaware'}"

    if sr_scale <= 0:
        raise ValueError(f"Invalid --sr-scale: {sr_scale}")

    if args.verbose:
        print(f"[VALIDATION] sr_scale_factor: {sr_scale} (source={sr_scale_source}; applied as ref /= sr_scale before log1p)")

    if sr_scale != 1.0:
        ref_start = (ref_start / sr_scale).astype(np.float32)
        ref_end = (ref_end / sr_scale).astype(np.float32)

        # Safety: keep any tiny negatives at 0
        ref_start[ref_start < 0] = 0.0
        ref_end[ref_end < 0] = 0.0

        if args.verbose:
            _print_stack_summary("db8_start_scaled", ref_start, band_indices_0based=[1, 2, 4, 5])
            _print_stack_summary("db8_end_scaled", ref_end, band_indices_0based=[1, 2, 4, 5])

    # Load NDVI dc4 images (optionally align to start_db8 grid)
    raw_ndvi = []
    dates = []
    paths = []
    warped_count = 0
    for p in dc4_files:
        if args.no_align_dc4_to_db8:
            arr, _ = load_raster(p)
            if arr.shape[0] != 1:
                raise SystemExit(f"dc4 (NDVI) must be single band: {p}")
            raw_ndvi.append(arr[0])
        else:
            # Warp onto db8 grid to avoid misregistration between GA0 (SR) and GA1 (NDVI).
            nd, did_warp = load_single_band_raster(
                p,
                align_to_path=start_db8,
                resample=args.dc4_resample,
                src_nodata=-9999.0,
                dst_nodata=-9999.0,
            )
            raw_ndvi.append(nd)
            if did_warp:
                warped_count += 1
        dates.append(parse_date(p))
        paths.append(p)

    if args.verbose and not args.no_align_dc4_to_db8:
        print(f"[VALIDATION] dc4_alignment: aligned_to_db8=true resample={args.dc4_resample} warped_files={warped_count}/{len(dc4_files)}")
    elif args.verbose:
        print("[VALIDATION] dc4_alignment: aligned_to_db8=false")

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
    base_mean, base_std, base_stderr, base_slope, base_intercept, base_n_valid = timeseries_stats(
        norm_baseline,
        baseline_dates,
        include_nodata_zeros=bool(args.baseline_include_nodata),
    )

    # Compute change indices
    # ndvi_trend: how much the (normalised) NDVI changed between start and end.
    # IMPORTANT: treat norm==0 as nodata and do not let nodata differences dominate.
    ndvi_valid = (norm_start > 0) & (norm_end > 0)
    ndvi_trend = (norm_end.astype(np.float32) - norm_start.astype(np.float32))
    ndvi_trend[~ndvi_valid] = 0.0

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
    valid_stderr = (base_stderr >= 0.2) & ndvi_valid
    valid_std = (base_std >= 0.2) & ndvi_valid
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
        try:
            nz = base_n_valid[base_n_valid > 0]
            if nz.size:
                p = np.percentile(nz.astype(np.float32), [0, 5, 50, 95, 100])
                print(
                    f"[VALIDATION] baseline_n_valid: min={p[0]:.3g} p05={p[1]:.3g} p50={p[2]:.3g} p95={p[3]:.3g} max={p[4]:.3g} (total_baseline={len(norm_baseline)})"
                )
        except Exception:
            pass
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

    dll_path = _join_out(output_base, f"{platform}olre_{tile}_d{sd}{ed}_dll_e{epsg}.tif")
    dlj_path = _join_out(output_base, f"{platform}olre_{tile}_d{sd}{ed}_dlj_e{epsg}.tif")

    # --------------------------------------------------
    # DIAGNOSTIC OUTPUT: raw combined index (UNSTRETCHED)
    # --------------------------------------------------
    # NOTE: This diagnostic raster is intended to be created only when
    # --diagnostics is enabled.
    if args.diagnostics:
        combined_img = _join_out(diagnostics_base, f"{platform}olre_{tile}_d{sd}{ed}_combined_raw_e{epsg}.tif")

        # ArcGIS tends to behave best when float rasters use a conventional
        # nodata sentinel like -9999 rather than relying on 0.
        diag_nodata = np.float32(-9999.0)
        combined_diag = combined_index.astype(np.float32, copy=True)
        combined_diag[~ndvi_valid] = diag_nodata

        write_gtiff(
            str(combined_img),
            [combined_diag],
            georef,
            dtype=gdal.GDT_Float32,
            nodata=float(diag_nodata),
            band_names=["combined_index_raw"],
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
        # Emit a small JSON run-metadata file so batch A/B runs can be summarised quickly.
        # This is intentionally diagnostics-only to avoid changing core outputs.
        import json
        import csv
        import io

        def _pct(arr: np.ndarray, *, treat_zero_as_nodata: bool) -> dict:
            a = arr.astype(np.float64)
            m = np.isfinite(a)
            if treat_zero_as_nodata:
                m &= (a != 0)
            v = a[m]
            if v.size == 0:
                return {"count": 0}
            p = np.percentile(v, [0, 1, 5, 50, 95, 99, 100])
            return {
                "count": int(v.size),
                "mean": float(v.mean()),
                "std": float(v.std()),
                "min": float(p[0]),
                "p01": float(p[1]),
                "p05": float(p[2]),
                "p50": float(p[3]),
                "p95": float(p[4]),
                "p99": float(p[5]),
                "max": float(p[6]),
            }

        def _flatten_pct(prefix: str, d: dict) -> dict:
            # stable schema for CSV concatenation
            out = {f"{prefix}_count": int(d.get("count", 0))}
            for k in ("mean", "std", "min", "p01", "p05", "p50", "p95", "p99", "max"):
                v = d.get(k, None)
                out[f"{prefix}_{k}"] = "" if v is None else float(v)
            return out

        diag_mask = (
            np.isfinite(ndviDiffStdErr)
            & (base_stderr >= 0.2)
            & (norm_start > 0)
            & (norm_end > 0)
        )
        vals = ndviDiffStdErr[diag_mask]

        diag_name_base = f"{platform}olre_{tile}_d{sd}{ed}_{args.vi_tag}_e{epsg}"
        diag_name = f"{diag_name_base}_{diag_suffix}"

        stats_csv = _join_out(diagnostics_base, f"{diag_name}_ndviDiffStdErr_stats.csv")
        bins_csv  = _join_out(diagnostics_base, f"{diag_name}_ndviDiffStdErr_bins.csv")

        write_diag_stats_csv(vals, stats_csv)
        write_diag_bins_csv(vals, bins_csv, bins=args.diag_bins, clip_abs=args.diag_clip)

        print(f"[DIAG] Stats CSV: {stats_csv}")
        print(f"[DIAG] Bins  CSV: {bins_csv}")

        uniq, cnt = np.unique(dll_class, return_counts=True)
        dll_counts = {str(int(u)): int(c) for u, c in zip(uniq, cnt)}

        runmeta = {
            "scene": scene,
            "tile": tile,
            "platform": platform,
            "start_date": sd,
            "end_date": ed,
            "window_start": ws,
            "window_end": we,
            "lookback": int(args.lookback),
            "sr_scale_factor": float(sr_scale),
            "sr_scale_source": sr_scale_source,
            "baseline_include_nodata": bool(args.baseline_include_nodata),
            "baseline_n_valid": _pct(base_n_valid.astype(np.float32), treat_zero_as_nodata=False),
            "ndvi_valid_pct": float(np.mean(ndvi_valid) * 100.0),
            "valid_std_pct": float(np.mean(base_std >= 0.2) * 100.0),
            "valid_stderr_pct": float(np.mean(base_stderr >= 0.2) * 100.0),
            "dll_class_counts": dll_counts,
            "spectral_index": _pct(spectral_index, treat_zero_as_nodata=True),
            "t_test": _pct(t_test, treat_zero_as_nodata=True),
            "s_test": _pct(s_test, treat_zero_as_nodata=True),
            "combined_index": _pct(combined_index, treat_zero_as_nodata=True),
            "ndviDiffStdErr": _pct(ndviDiffStdErr, treat_zero_as_nodata=False),
        }
        runmeta_path = _join_out(diagnostics_base, f"{diag_name}_runmeta.json")
        _write_text_anywhere(str(runmeta_path), json.dumps(runmeta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[DIAG] Run meta JSON: {runmeta_path}")

        # Also emit a one-row wide CSV for easy concatenation across tiles/runs.
        # Keep columns stable (missing values become blank / 0).
        known_classes = [0, 3, 10, 34, 35, 36, 37, 38, 39]
        row = {
            "scene": scene,
            "tile": tile,
            "platform": platform,
            "start_date": sd,
            "end_date": ed,
            "window_start": ws,
            "window_end": we,
            "lookback": int(args.lookback),
            "sr_scale_factor": float(sr_scale),
            "sr_scale_source": sr_scale_source,
            "baseline_include_nodata": bool(args.baseline_include_nodata),
            "ndvi_valid_pct": float(np.mean(ndvi_valid) * 100.0),
            "valid_std_pct": float(np.mean(base_std >= 0.2) * 100.0),
            "valid_stderr_pct": float(np.mean(base_stderr >= 0.2) * 100.0),
        }

        # DLL counts
        total_px = int(dll_class.size)
        row["dll_total_px"] = total_px
        for c in known_classes:
            row[f"dll_count_{c}"] = int(dll_counts.get(str(c), 0))
        row["dll_count_other"] = int(sum(v for k, v in dll_counts.items() if int(k) not in known_classes))

        # Metric percentiles
        row.update(_flatten_pct("baseline_n_valid", _pct(base_n_valid.astype(np.float32), treat_zero_as_nodata=False)))
        row.update(_flatten_pct("spectral_index", _pct(spectral_index, treat_zero_as_nodata=True)))
        row.update(_flatten_pct("t_test", _pct(t_test, treat_zero_as_nodata=True)))
        row.update(_flatten_pct("s_test", _pct(s_test, treat_zero_as_nodata=True)))
        row.update(_flatten_pct("combined_index", _pct(combined_index, treat_zero_as_nodata=True)))
        row.update(_flatten_pct("ndviDiffStdErr", _pct(ndviDiffStdErr, treat_zero_as_nodata=False)))

        # Threshold exceedance rates (handy precision/false-positive proxy)
        v = vals.astype(np.float64)
        v = v[np.isfinite(v)]
        for t in (2.5, 6.0, 10.0):
            row[f"ndviDiffStdErr_pct_ge_{str(t).replace('.', '_')}"] = float(np.mean(v >= t) * 100.0) if v.size else 0.0

        csv_buf = io.StringIO()
        writer = csv.DictWriter(csv_buf, fieldnames=list(row.keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)
        summary_csv = _join_out(diagnostics_base, f"{diag_name}_summary.csv")
        _write_text_anywhere(str(summary_csv), csv_buf.getvalue(), encoding="utf-8")
        print(f"[DIAG] Summary CSV: {summary_csv}")

        # ---- SR scaling verification CSV (dedicated, one-row) ----
        # Captures pre/post scaling SR band percentiles for the key legacy bands (B2,B3,B5,B6)
        # so SR scaling behaviour can be audited across tiles.
        sr_row = {
            "scene": scene,
            "tile": tile,
            "platform": platform,
            "start_date": sd,
            "end_date": ed,
            "sr_scale_factor": float(sr_scale),
            "sr_scale_source": sr_scale_source,
            "baseline_include_nodata": bool(args.baseline_include_nodata),
        }

        # Re-compute raw-vs-scaled band stats.
        # NOTE: ref_start/ref_end have already had scaling applied (if any) by this point.
        # We reconstruct "raw" as "scaled * sr_scale" for verification purposes.
        bands_0 = [1, 2, 4, 5]  # B2,B3,B5,B6
        for which, arr_scaled in (("start", ref_start), ("end", ref_end)):
            for b0 in bands_0:
                band_scaled = arr_scaled[b0].astype(np.float32)
                band_raw = band_scaled * float(sr_scale)

                sr_row.update(_flatten_pct(f"{which}_b{b0+1}_raw", _pct(band_raw, treat_zero_as_nodata=True)))
                sr_row.update(_flatten_pct(f"{which}_b{b0+1}_scaled", _pct(band_scaled, treat_zero_as_nodata=True)))

        sr_csv_buf = io.StringIO()
        sr_writer = csv.DictWriter(sr_csv_buf, fieldnames=list(sr_row.keys()), extrasaction="ignore")
        sr_writer.writeheader()
        sr_writer.writerow(sr_row)

        sr_verify_csv = _join_out(diagnostics_base, f"{diag_name}_sr_scale_verify.csv")
        _write_text_anywhere(str(sr_verify_csv), sr_csv_buf.getvalue(), encoding="utf-8")
        print(f"[DIAG] SR scale verify CSV: {sr_verify_csv}")

        try:
            import matplotlib.pyplot as plt

            vclip = np.clip(vals, -args.diag_clip, args.diag_clip)
            plt.figure()
            plt.hist(vclip, bins=args.diag_bins)
            plt.axvline(2.5, linestyle="--")
            plt.axvline(-2.5, linestyle="--")
            plt.title("ndviDiffStdErr histogram (clipped)")
            png_path = _join_out(diagnostics_base, f"{diag_name}_ndviDiffStdErr.png")
            if _is_vsi_path(str(png_path)):
                raise RuntimeError("Skipping PNG output to VSI path")
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
        log_path = _join_out(output_base, f"{platform}olre_{tile}_d{sd}{ed}_dll_log_e{epsg}.json")
        _write_text_anywhere(str(log_path), json.dumps(log, indent=2) + "\n", encoding="utf-8")
        if args.verbose:
            print(f"[Output] LOG: {log_path}")
    except Exception as e:
        print(f"[WARN] Failed to write log JSON: {e}")

    print(f"[OK] Completed: {dll_path}, {dlj_path}")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())

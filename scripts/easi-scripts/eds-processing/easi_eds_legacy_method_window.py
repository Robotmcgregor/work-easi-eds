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


# def parse_date(path: str) -> str:
#     import re
#     m = re.search(r"(19|20)\d{6}", os.path.basename(path))
#     if not m:
#         raise ValueError(f"Cannot parse date from {path}")
#     return m.group(0)

def parse_date(path: str) -> str:
    """
    Look at a file path and pull out the first 8-digit date we can find
    that starts with 19 or 20 (e.g. 20200611 or 19981231).

    Example:
        "/some/folder/lztmre_p104r072_20200611_db8mz.img"
        -> "20200611"
    """
    import re
    import os

    # We only care about the file name itself, not the whole folder path.
    # For example: "lztmre_p104r072_20200611_db8mz.img"
    filename = os.path.basename(path)

    # Look for a pattern that “looks like a date”:
    # - starts with 19 or 20 (year 1900–2099)
    # - followed by 6 digits (MMDDYY style, but we treat it as YYYYMMDD overall)
    #
    # find me the first 8-digit number that could be a year+month+day.
    m = re.search(r"(19|20)\d{6}", filename)

    # If we can’t find any such 8-digit date in the filename, stop and complain clearly.
    if not m:
        raise ValueError(f"Cannot find a date in the file name: {path}")

    # If we found one, return the matched text, e.g. "20200611".
    return m.group(0)



# def decimal_year(yyyymmdd: str) -> float:
#     import datetime
#     y = int(yyyymmdd[:4]); m = int(yyyymmdd[4:6]); d = int(yyyymmdd[6:])
#     date = datetime.date(y, m, d)
#     jan1 = datetime.date(y, 1, 1)
#     dec31 = datetime.date(y, 12, 31)
#     doy = (date - jan1).days
#     days = (dec31 - jan1).days + 1
#     return y + doy / days

def decimal_year(yyyymmdd: str) -> float:
    """
    Convert a date written as 'YYYYMMDD' into a decimal year.

    Example:
        "20200611" (11 June 2020) might become something like 2020.44

    Why do this?
        Some maths (like trend lines over time) are easier if we treat dates
        as a single number instead of separate year / month / day.
    """
    import datetime

    # Pull the year, month, and day out of the text.
    # For "20200611":
    #   y = 2020, m = 06, d = 11
    y = int(yyyymmdd[:4])
    m = int(yyyymmdd[4:6])
    d = int(yyyymmdd[6:])

    # Turn that into a real calendar date Python understands.
    date = datetime.date(y, m, d)

    # Work out the first and last day of that year.
    jan1 = datetime.date(y, 1, 1)
    dec31 = datetime.date(y, 12, 31)

    # How many days have passed since 1 January?
    # (This is the "day of year", starting from 0.)
    doy = (date - jan1).days

    # How many days are in this year (365 or 366 in a leap year)?
    days = (dec31 - jan1).days + 1

    # Decimal year = whole year + fraction of the year that has passed.
    # For example, halfway through the year is roughly y + 0.5.
    return y + doy / days

# def _parse_mmdd(mmdd: str) -> Tuple[int, int]:
#     if len(mmdd) != 4 or not mmdd.isdigit():
#         raise ValueError("MMDD must be 4 digits, e.g., 0701")
#     return int(mmdd[:2]), int(mmdd[2:])

from typing import Tuple

def _parse_mmdd(mmdd: str) -> Tuple[int, int]:
    """
    Take a short date code like 'MMDD' (month + day) and split it into
    separate numbers for month and day.

    Example:
        "0701"  ->  (7, 1)   # 1st of July
        "1231"  ->  (12, 31) # 31st of December
    """
    # Basic safety check:
    # - it must be exactly 4 characters long
    # - all 4 characters must be digits (0–9)
    if len(mmdd) != 4 or not mmdd.isdigit():
        raise ValueError("MMDD must be 4 digits, e.g., '0701' for 1st of July")

    # First two characters = month, last two = day.
    month = int(mmdd[:2])
    day = int(mmdd[2:])

    return month, day

# def in_window(yyyymmdd: str, start_mmdd: str, end_mmdd: str) -> bool:
#     m = int(yyyymmdd[4:6]); d = int(yyyymmdd[6:8])
#     sm, sd = _parse_mmdd(start_mmdd)
#     em, ed = _parse_mmdd(end_mmdd)
#     if (sm, sd) <= (em, ed):
#         return (m, d) >= (sm, sd) and (m, d) <= (em, ed)
#     else:
#         return (m, d) >= (sm, sd) or (m, d) <= (em, ed)
def in_window(yyyymmdd: str, start_mmdd: str, end_mmdd: str) -> bool:
    """
    Check whether a given date falls inside a seasonal window.

    Inputs:
        yyyymmdd  - full date as 'YYYYMMDD', e.g. '20200611' (11 June 2020)
        start_mmdd - window start as 'MMDD', e.g. '0701' (1 July)
        end_mmdd   - window end   as 'MMDD', e.g. '0930' (30 September)

    The window can:
        - stay within a single year (e.g. 0701–0930), or
        - cross New Year (e.g. 1101–0301 = 1 Nov to 1 Mar).

    Returns:
        True if the date is inside the window, otherwise False.
    """
    # Pull month and day out of the full date.
    # "20200611" -> m = 6, d = 11
    m = int(yyyymmdd[4:6])
    d = int(yyyymmdd[6:8])

    # Turn the start and end 'MMDD' codes into (month, day) numbers.
    sm, sd = _parse_mmdd(start_mmdd)
    em, ed = _parse_mmdd(end_mmdd)

    # Here, start <= end in simple calendar order.
    if (sm, sd) <= (em, ed):
        # Inside the window if:
        #   date >= start AND date <= end
        return (m, d) >= (sm, sd) and (m, d) <= (em, ed)

    # Here, start is "later" than end in the calendar year,
    # so the window wraps around the year boundary.
    else:
        # Inside the window if:
        #   date is on/after the start of the window (e.g. 1 Nov–31 Dec)
        #   OR on/before the end of the window (e.g. 1 Jan–1 Mar).
        return (m, d) >= (sm, sd) or (m, d) <= (em, ed)


# def load_raster(path: str) -> Tuple[np.ndarray, Tuple]:
#     ds = gdal.Open(path, gdal.GA_ReadOnly)
#     if ds is None:
#         raise IOError(f"Cannot open {path}")
#     bands = [ds.GetRasterBand(i+1).ReadAsArray() for i in range(ds.RasterCount)]
#     arr = np.stack(bands, axis=0)
#     georef = (ds.GetGeoTransform(can_return_null=True), ds.GetProjection())
#     ds = None
#     return arr, georef
# from typing import Tuple
# import numpy as np
# from osgeo import gdal

def load_raster(path: str) -> Tuple[np.ndarray, Tuple]:
    """
    Open a raster file and return:
      1. The pixel values as a NumPy array.
      2. Georeferencing info.

    Output array shape:
        (bands, rows, cols)

    """
    # GDAL to open the file in "read only".
    ds = gdal.Open(path, gdal.GA_ReadOnly)

    # If GDAL couldn’t open the file, stop script and raise error (see below).
    if ds is None:
        raise IOError(f"Cannot open raster file: {path}")

    # Read each band (layer) into memory as a 2D array.
    # ds.RasterCount tells us how many bands the raster has.
    # GetRasterBand(i+1) because GDAL bands are 1-based (start at 1, not 0).
    bands = [
        ds.GetRasterBand(i + 1).ReadAsArray()
        for i in range(ds.RasterCount)
    ]

    # Stack the band arrays into a single 3D array:
    #   (band, row, column)
    arr = np.stack(bands, axis=0)

    # Store the georeferencing:
    # - GeoTransform: how pixel coordinates map to real-world coordinates.
    # - Projection: the coordinate reference system (e.g. EPSG:3577).
    georef = (
        ds.GetGeoTransform(can_return_null=True),
        ds.GetProjection()
    )

    # Close the dataset to free resources.
    ds = None

    # Return both the pixel data and the georeferencing together.
    return arr, georef


# def write_envi(out_path: str, arrays: List[np.ndarray], georef: Tuple, dtype=gdal.GDT_Byte, nodata=0) -> None:
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


def write_envi(
    out_path: str,
    arrays: List[np.ndarray],
    georef: Tuple,
    dtype=gdal.GDT_Byte,
    nodata=0,
) -> None:
    """
    Save one or more 2D arrays as an ENVI raster file on disk.

    This is the "opposite" of load_raster:
      - load_raster: file  -> NumPy array + georeferencing
      - write_envi:  array -> file on disk (with georeferencing)

    Inputs:
        out_path  - where to save the new raster (e.g. '/path/to/output.img')
        arrays    - list of 2D arrays, one per band/layer
                    all arrays must have the same shape: (rows, cols)
        georef    - (GeoTransform, Projection) tuple, usually taken from
                    load_raster(), so spatial position is preserved
        dtype     - GDAL data type (e.g. gdal.GDT_Byte for 0–255 values)
        nodata    - value used to mark "no data" pixels (e.g. 0)

    The file will be written in ENVI format, which also creates a .hdr file.
    """

    # Unpack georeferencing information.
    # gt   = how pixels map to real-world coordinates
    # proj = coordinate reference system (e.g. EPSG code wrapped in WKT)
    gt, proj = georef

    # Work out the image size from the first array.
    # Each array is 2D: (rows, columns)
    ysize, xsize = arrays[0].shape

    # Create a new ENVI raster with the requested size and number of bands.
    drv = gdal.GetDriverByName("ENVI")
    ds = drv.Create(
        out_path,
        xsize,             # number of columns
        ysize,             # number of rows
        len(arrays),       # number of bands
        dtype,             # pixel data type
    )

    # Attach georeferencing if we have it.
    if gt:
        ds.SetGeoTransform(gt)
    if proj:
        ds.SetProjection(proj)

    # Write each array into its own band.
    for i, arr in enumerate(arrays, start=1):
        band = ds.GetRasterBand(i)
        band.WriteArray(arr)
        band.SetNoDataValue(nodata)

    # Make sure everything is written to disk.
    ds.FlushCache()

    # Close the dataset to free resources.
    ds = None


# def normalise_fpc(arr: np.ndarray) -> np.ndarray:
#     """Normalize raw FPC image to legacy-style uint8 with mean~125 and scale~15.

#     - Valid pixels are strictly > 0 (zeros are treated as nodata from masks).
#     - If std==0 (flat image), we avoid division by zero by using std=1.0.
#     - Output is clipped to [1,255], with nodata set back to 0.
#     """
#     valid = arr > 0
#     if not np.any(valid):
#         return np.zeros_like(arr, dtype=np.uint8)
#     mean = arr[valid].mean()
#     std = arr[valid].std()
#     if std == 0:
#         std = 1.0
#     norm = 125 + 15 * (arr.astype(np.float32) - mean) / std
#     norm = np.clip(norm, 1, 255).astype(np.uint8)
#     norm[~valid] = 0
#     return norm


def normalise_fpc(arr: np.ndarray) -> np.ndarray:
    """
    Take a raw FPC (fractional cover) image and convert it into a
    “standardised” 8-bit image (values 0–255) in the legacy EDS style.

    What this does in plain language:
      - Treat 0 as "no data" (masked out pixels).
      - Look at the valid pixels (>0) and:
          * centre them around 125
          * spread them out so most values fall within about ±15 of 125
      - Clip to the range 1..255
      - Set no-data pixels back to 0

    Why?
      - Older tools and styling expect FPC to be on this 0–255 scale,
        with typical “real” values around the middle (125).
    """

    # Valid pixels are strictly > 0.
    # Zeros are treated as nodata (coming from masks).
    valid = arr > 0

    # If there are no valid pixels at all, just return an array of zeros
    # (everything is nodata).
    if not np.any(valid):
        return np.zeros_like(arr, dtype=np.uint8)

    # Calculate the mean and standard deviation using only the valid pixels.
    mean = arr[valid].mean()
    std = arr[valid].std()

    # Guard against a completely flat image (std = 0),
    # which would cause a divide-by-zero error.
    if std == 0:
        std = 1.0

    # Normalise:
    #   - subtract the mean so values are centred around 0
    #   - divide by std so we measure in "standard deviations"
    #   - multiply by 15 and add 125 so the typical range sits around 125
    #     with a spread of roughly ±15.
    norm = 125 + 15 * (arr.astype(np.float32) - mean) / std

    # Force everything into the range [1, 255].
    # (0 is reserved for nodata, which we’ll set explicitly next.)
    norm = np.clip(norm, 1, 255).astype(np.uint8)

    # Put nodata pixels back to 0.
    norm[~valid] = 0

    return norm


# def timeseries_stats(norm_list: List[np.ndarray], date_list: List[str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
#     """Compute baseline statistics across normalized FPC stack.

#     Returns per-pixel arrays for:
#       - mean, std, stderr (std/sqrt(N) when N>1, else zeros)
#       - slope, intercept from linear fit in decimal year time
#     """
#     # Stack to shape (N, Y, X)
#     stack = np.stack([a.astype(np.float32) for a in norm_list], axis=0)
#     mean = stack.mean(axis=0)
#     std = stack.std(axis=0)
#     n = stack.shape[0]
#     stderr = std / math.sqrt(max(n, 1)) if n > 1 else np.zeros_like(mean)
#     if n > 1:
#         t = np.array([decimal_year(d) for d in date_list], dtype=np.float32)
#         t_mean = t.mean()
#         denom = np.sum((t - t_mean) ** 2)
#         if denom == 0:
#             slope = np.zeros_like(mean)
#             intercept = mean.copy()
#         else:
#             y_mean = mean
#             slope = np.sum(((t - t_mean)[:, None, None]) * (stack - y_mean), axis=0) / denom
#             intercept = y_mean - slope * t_mean
#     else:
#         slope = np.zeros_like(mean)
#         intercept = mean.copy()
#     return mean, std, stderr, slope, intercept
from typing import List, Tuple
import math
import numpy as np

def timeseries_stats(
    norm_list: List[np.ndarray],
    date_list: List[str]
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Calculate basic time-series statistics for a stack of normalised FPC images.

    Inputs:
        norm_list - list of 2D arrays (one per date), all the same shape (rows, cols).
                    Each array is a normalised FPC image (e.g. from normalise_fpc()).
        date_list - list of dates as 'YYYYMMDD' strings, in the same order as norm_list.

    For every pixel location (row, col), this function works across time and returns:
        mean      - average value over all dates
        std       - standard deviation (how much it varies over time)
        stderr    - standard error of the mean (std / sqrt(N) when N > 1, else 0)
        slope     - trend over time (change per year) using a straight-line fit
        intercept - baseline value of that trend at time "zero" (from the line fit)

    These outputs are all 2D arrays with the same shape as the input images.
    """

    # Stack all images into a single 3D array:
    #   shape = (N, Y, X)
    #   N = number of dates
    #   Y = number of rows
    #   X = number of columns
    stack = np.stack([a.astype(np.float32) for a in norm_list], axis=0)

    # Mean and standard deviation over time, for each pixel.
    mean = stack.mean(axis=0)
    std = stack.std(axis=0)

    # Number of time steps (images).
    n = stack.shape[0]

    # Standard error of the mean (per pixel).
    # Only meaningful when we have more than 1 image.
    if n > 1:
        stderr = std / math.sqrt(n)
    else:
        stderr = np.zeros_like(mean)

    # If we only have one image, we can't fit a trend line,
    # so set slope = 0 and intercept = mean.
    if n > 1:
        # Convert dates into decimal years (e.g. 2020.45).
        t = np.array([decimal_year(d) for d in date_list], dtype=np.float32)

        # Average of the time values.
        t_mean = t.mean()

        # Denominator used in the least-squares line fit.
        # sum of (t - t_mean)^2
        denom = np.sum((t - t_mean) ** 2)

        if denom == 0:
            # All time values are the same (no time spread) — can't fit a line.
            slope = np.zeros_like(mean)
            intercept = mean.copy()
        else:
            # Mean image over time is our "average signal".
            y_mean = mean

            # Compute the slope (rate of change per year) per pixel.
            #
            # This is a standard linear regression formula:
            #   slope = sum( (t - t_mean) * (y - y_mean) ) / sum( (t - t_mean)^2 )
            #
            # We do this for every pixel in one go by using broadcasting.
            slope = np.sum(
                ((t - t_mean)[:, None, None]) * (stack - y_mean),
                axis=0
            ) / denom

            # Intercept: value of the line when t = 0,
            # derived from: y = slope * t + intercept -> intercept = y_mean - slope * t_mean
            intercept = y_mean - slope * t_mean
    else:
        slope = np.zeros_like(mean)
        intercept = mean.copy()

    return mean, std, stderr, slope, intercept


# def stretch(img: np.ndarray, mean: float, stddev: float, numStdDev: float, minVal: int, maxVal: int, ignoreVal: float) -> np.ndarray:
#     """Legacy-style linear stretch to uint8 given mean/std and a +-numStdDev window.

#     Pixels equal to ignoreVal (e.g., 0) are forced to 0 in the output.
#     """
#     stretched = minVal + (img - mean + stddev * numStdDev) * (maxVal - minVal) / (stddev * 2 * numStdDev)
#     stretched = np.clip(stretched, minVal, maxVal)
#     stretched = stretched.astype(np.float32)
#     stretched[img == ignoreVal] = 0
#     return stretched.astype(np.uint8)



def stretch(
    img: np.ndarray,
    mean: float,
    stddev: float,
    numStdDev: float,
    minVal: int,
    maxVal: int,
    ignoreVal: float,
) -> np.ndarray:
    """
    Apply a simple linear "stretch" to a raster image so that values fit nicely
    into a display range (for example 1–255 for an 8-bit image).

    In plain language:
      - We take an image (img) and assume we know its overall mean and spread (stddev).
      - We choose a window around the mean: mean ± numStdDev * stddev.
      - Values inside this window are mapped into [minVal, maxVal].
      - Values below/above the window are clipped to the ends.
      - Any pixels equal to ignoreVal (e.g. 0) are treated as nodata and set to 0.

    This matches the legacy behaviour used in the original EDS code.
    """

    # Linear stretch:
    #   - Shift the image so that the "window" [mean - numStdDev*stddev,
    #     mean + numStdDev*stddev] is scaled into [minVal, maxVal].
    #
    # Formula breakdown:
    #   (img - mean + stddev * numStdDev) / (stddev * 2 * numStdDev)
    #       -> normalises values into a 0..1 range across the chosen window.
    #   * (maxVal - minVal)
    #       -> scales 0..1 into the desired output range.
    #   + minVal
    #       -> shifts the range to start at minVal.
    stretched = (
        minVal
        + (img - mean + stddev * numStdDev)
        * (maxVal - minVal)
        / (stddev * 2 * numStdDev)
    )

    # Clip anything outside the range into [minVal, maxVal].
    stretched = np.clip(stretched, minVal, maxVal)

    # Work in float for the nodata handling, then convert to uint8 at the end.
    stretched = stretched.astype(np.float32)

    # Any pixel that matches the ignore value (e.g. 0) is forced to 0
    # in the output. This keeps "nodata" or masked-out areas dark.
    stretched[img == ignoreVal] = 0

    # Return as 8-bit integers (0–255), suitable for ENVI / display.
    return stretched.astype(np.uint8)



# def main(argv=None) -> int:
#     ap = argparse.ArgumentParser(description="Legacy-method change detection (seasonal window)")
#     ap.add_argument('--scene', required=True)
#     ap.add_argument('--start-date', required=True)
#     ap.add_argument('--end-date', required=True)
#     ap.add_argument('--dc4-glob', help='Glob for dc4 images; defaults to compat path')
#     ap.add_argument('--start-db8')
#     ap.add_argument('--end-db8')
#     ap.add_argument('--window-start')
#     ap.add_argument('--window-end')
#     ap.add_argument('--lookback', type=int, default=10)
#     ap.add_argument('--omit-fpc-start-threshold', action='store_true')
#     ap.add_argument('--verbose', action='store_true')
#     args = ap.parse_args(argv)

#     scene = args.scene.lower()
#     sd = args.start_date
#     ed = args.end_date
#     ws = args.window_start or sd[4:]
#     we = args.window_end or ed[4:]

#     # Discover inputs
#     # If explicit start/end db8 stacks are not supplied, derive their standard filenames.
#     if args.start_db8 and args.end_db8:
#         start_db8 = args.start_db8
#         end_db8 = args.end_db8
#     else:
#         start_db8 = stdProjFilename(f"lztmre_{scene}_{sd}_db8mz.img")
#         end_db8 = stdProjFilename(f"lztmre_{scene}_{ed}_db8mz.img")
#     if not os.path.exists(start_db8) or not os.path.exists(end_db8):
#         raise SystemExit("Start/end db8 files not found; provide --start-db8/--end-db8 or build them.")

#     # dc4 sources: prefer explicit glob passed by the master; otherwise use scene-based directory.
#     if args.dc4_glob:
#         dc4_files = sorted(glob.glob(args.dc4_glob))
#     else:
#         base = Path(stdProjFilename(f"lztmre_{scene}_00000000_dc4mz.img")).parent
#         dc4_files = sorted(glob.glob(str(base / f"lztmre_{scene}_*_dc4mz.img")))
#     if not dc4_files:
#         raise SystemExit("No dc4 images found")

#     # Load reflectance
#     ref_start, georef = load_raster(start_db8)
#     ref_end, _ = load_raster(end_db8)

#     # Load dc4 and crop all arrays to a common shape (minimal Y,X across all inputs).
#     # This safeguards against slight dimension/transform mismatches in inputs.
#     raw_dc4 = []
#     dates = []
#     for p in dc4_files:
#         arr, _ = load_raster(p)
#         if arr.shape[0] != 1:
#             raise SystemExit(f"dc4 must be single band: {p}")
#         raw_dc4.append(arr[0])
#         dates.append(parse_date(p))
#     # Determine minimal common shape across start/end reflectance and all dc4 rasters
#     ys = []; xs = []
#     for a in [ref_start, ref_end] + raw_dc4:
#         if a.ndim == 3:
#             _, y, x = a.shape
#         else:
#             y, x = a.shape
#         ys.append(y); xs.append(x)
#     min_y = min(ys); min_x = min(xs)
#     def crop(a):
#         if a.ndim == 3:
#             return a[..., :min_y, :min_x]
#         return a[:min_y, :min_x]
#     ref_start = crop(ref_start).astype(np.float32)
#     ref_end = crop(ref_end).astype(np.float32)
#     raw_dc4 = [crop(a) for a in raw_dc4]

#     # Build seasonal baseline: choose at most one dc4 image per prior year within the window, up to lookback.
#     # Constraint: pick dates <= provided start-date. We choose the date closest (by MMDD) to the end target within each year.
#     end_year = int(ed[:4])
#     start_cutoff = sd
#     # group dates by year
#     by_year = {}
#     for d, a in zip(dates, raw_dc4):
#         y = int(d[:4])
#         if y < end_year - args.lookback + 1 or y > end_year:
#             continue
#         if d > start_cutoff:
#             continue
#         if not in_window(d, ws, we):
#             continue
#         by_year.setdefault(y, []).append((d, a))
#     # choose nearest to end MMDD within window
#     tm, td = int(we[:2]), int(we[2:])
#     def md_dist(d: str) -> int:
#         return abs((int(d[4:6]) - tm) * 31 + (int(d[6:8]) - td))
#     base_dates: List[str] = []
#     base_raw: List[np.ndarray] = []
#     for y in sorted(by_year.keys()):
#         lst = by_year[y]
#         if lst:
#             d, a = sorted(lst, key=lambda t: md_dist(t[0]))[0]
#             base_dates.append(d)
#             base_raw.append(a)
#     if len(base_dates) < 2:
#         # Fallback: use all available dc4 prior to start within the window (not limited to 1 per year)
#         base_dates = [d for d in dates if (d <= start_cutoff and in_window(d, ws, we))]
#         base_raw = [a for d, a in zip(dates, raw_dc4) if (d <= start_cutoff and in_window(d, ws, we))]
#         if len(base_dates) < 2:
#             raise SystemExit("Baseline too small (<2 images) after seasonal filtering")

#     # Normalise baseline
#     base_norm = [normalise_fpc(a) for a in base_raw]
#     ts_mean, ts_std, ts_stderr, ts_slope, ts_intercept = timeseries_stats(base_norm, base_dates)

#     # Choose FPC start/end closest to provided dates (constrained to seasonal window).
#     # If exact dates are present they are used; otherwise nearest-in-days inside the window.
#     def nearest_idx(target: str, pool_dates: List[str]) -> int:
#         if target in pool_dates:
#             return pool_dates.index(target)
#         best = None
#         for i, d in enumerate(pool_dates):
#             if not in_window(d, ws, we):
#                 continue
#             import datetime
#             def to_date(s):
#                 return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
#             dist = abs((to_date(d) - to_date(target)).days)
#             if best is None or dist < best[0]:
#                 best = (dist, i)
#         return best[1] if best else 0
#     idx_start = nearest_idx(sd, dates)
#     idx_end = nearest_idx(ed, dates)
#     fpc_start_raw = raw_dc4[idx_start]
#     fpc_end_raw = raw_dc4[idx_end]
#     fpc_start_norm = normalise_fpc(fpc_start_raw)
#     fpc_end_norm = normalise_fpc(fpc_end_raw)

#     # Legacy indices and tests
#     # fpcDiff is based on normalised FPC; its product with stderr (negated) follows the legacy sign convention.
#     fpcDiff = fpc_end_norm.astype(np.float32) - fpc_start_norm.astype(np.float32)
#     fpcDiffStdErr = -fpcDiff * ts_stderr
#     prediction_decimal_year = decimal_year(ed)
#     predictedNormedFpc = ts_intercept + ts_slope * prediction_decimal_year
#     observedNormedFpc = fpc_end_norm.astype(np.float32)
#     sTest = np.zeros_like(observedNormedFpc, dtype=np.float32)
#     tTest = np.zeros_like(observedNormedFpc, dtype=np.float32)
#     valid_stderr = ts_stderr >= 0.2
#     valid_std = ts_std >= 0.2
#     sTest[valid_stderr] = (observedNormedFpc[valid_stderr] - predictedNormedFpc[valid_stderr]) / ts_stderr[valid_stderr]
#     tTest[valid_std] = (observedNormedFpc[valid_std] - ts_mean[valid_std]) / ts_std[valid_std]

#     # Spectral index from start/end DB8: bands 2,3,5,6 are indices [1,2,4,5] in the db8 stack.
#     # The weights and log1p() transform follow the legacy model.
#     refStart = ref_start
#     refEnd = ref_end
#     spectralIndex = (
#         (0.77801094 * np.log1p(refStart[1])) +
#         (1.7713253  * np.log1p(refStart[2])) +
#         (2.0714311  * np.log1p(refStart[4])) +
#         (2.5403550  * np.log1p(refStart[5])) +
#         (-0.2996241 * np.log1p(refEnd[1])) +
#         (-0.5447928 * np.log1p(refEnd[2])) +
#         (-2.2842536 * np.log1p(refEnd[4])) +
#         (-4.0177752 * np.log1p(refEnd[5]))
#     ).astype(np.float32)

#     combinedIndex = (-11.972499 * spectralIndex -
#                      0.40357223 * fpcDiff -
#                      5.2609715  * tTest -
#                      4.3794265  * sTest).astype(np.float32)

#     # Change class assignment according to legacy thresholds.
#     # 10 = no clearing (default), 3 = FPC-only signal, 34..39 = increasing clearing confidence/strength.
#     NO_CLEARING = 10
#     NULL_CLEARING = 0
#     changeclass = np.full(spectralIndex.shape, NO_CLEARING, dtype=np.uint8)
#     changeclass[combinedIndex > 21.80] = 34
#     changeclass[(combinedIndex > 27.71) & (sTest < -0.27) & (spectralIndex < -0.86)] = 35
#     changeclass[(combinedIndex > 33.40) & (sTest < -0.60) & (spectralIndex < -1.19)] = 36
#     changeclass[(combinedIndex > 39.54) & (sTest < -1.01) & (spectralIndex < -1.50)] = 37
#     changeclass[(combinedIndex > 47.05) & (sTest < -1.55) & (spectralIndex < -1.84)] = 38
#     changeclass[(combinedIndex > 58.10) & (sTest < -2.34) & (spectralIndex < -2.27)] = 39
#     changeclass[(tTest > -1.70) & (fpcDiffStdErr > 740)] = 3

#     # Optional rule: force no-clearing where raw fpcStart < 108 (applies before nulling by reflectance zeros).
#     if not args.omit_fpc_start_threshold:
#         changeclass[fpc_start_raw < 108] = NO_CLEARING

#     # Null out where reflectance has zeros in any band for start or end.
#     refNullMask = (refStart == 0).any(axis=0) | (refEnd == 0).any(axis=0)
#     changeclass[refNullMask] = NULL_CLEARING

#     # Interpretation stretch (legacy scales) and clearing probability.
#     spectralMean = float(np.mean(spectralIndex[spectralIndex != 0])) if np.any(spectralIndex != 0) else 0.0
#     spectralStd  = float(np.std(spectralIndex[spectralIndex != 0])) if np.any(spectralIndex != 0) else 1.0
#     sTestMean    = float(np.mean(sTest[sTest != 0])) if np.any(sTest != 0) else 0.0
#     sTestStd     = float(np.std(sTest[sTest != 0])) if np.any(sTest != 0) else 1.0
#     combMean     = float(np.mean(combinedIndex[combinedIndex != 0])) if np.any(combinedIndex != 0) else 0.0
#     combStd      = float(np.std(combinedIndex[combinedIndex != 0])) if np.any(combinedIndex != 0) else 1.0

#     print(f"[EDS DEBUG] - spectralMean {spectralMean}")
#     print(f"[EDS DEBUG] - spectralStd {spectralStd}")
#     print(f"[EDS DEBUG] - sTestMean {sTestMean}")
#     print(f"[EDS DEBUG] - sTestStd {sTestStd}")
#     print(f"[EDS DEBUG] - combMean {combMean}")
#     print(f"[EDS DEBUG] - combStd {combStd}")

#     spectralStretched = stretch(spectralIndex, spectralMean, spectralStd, 2, 1, 255, 0)
#     sTestStretched     = stretch(sTest, sTestMean, sTestStd, 10, 1, 255, 0)
#     combinedStretched  = stretch(combinedIndex, combMean, combStd, 10, 1, 255, 0)

#     clearingProb = 200 * (1 - np.exp(-((0.01227 * combinedIndex) ** 3.18975)))
#     clearingProb = np.round(clearingProb).astype(np.uint8)
#     clearingProb[combinedIndex <= 0] = 0

#     # Outputs (ENVI .img with legacy-compatible names)
#     # era = f"d{sd}{ed}"
#     # out_cls = stdProjFilename(f"lztmre_{scene}_{era}_dllmz.img")
#     # out_int = stdProjFilename(f"lztmre_{scene}_{era}_dljmz.img")
#     # Path(out_cls).parent.mkdir(parents=True, exist_ok=True)

#     # write_envi(out_cls, [changeclass], georef, dtype=gdal.GDT_Byte, nodata=0)
#     # write_envi(out_int, [spectralStretched, sTestStretched, combinedStretched, clearingProb], georef, dtype=gdal.GDT_Byte, nodata=0)
#     # Outputs (ENVI .img with legacy-compatible names)
#     era = f"d{sd}{ed}"
#     # Put outputs in the same folder as the start db8 (i.e. the compat scene folder)
#     base_dir = Path(start_db8).parent

#     out_cls = stdProjFilename(str(base_dir / f"lztmre_{scene}_{era}_dllmz.img"))
#     out_int = stdProjFilename(str(base_dir / f"lztmre_{scene}_{era}_dljmz.img"))
#     Path(out_cls).parent.mkdir(parents=True, exist_ok=True)

#     write_envi(out_cls, [changeclass], georef, dtype=gdal.GDT_Byte, nodata=0)
#     write_envi(out_int, [spectralStretched, sTestStretched, combinedStretched, clearingProb],
#                georef, dtype=gdal.GDT_Byte, nodata=0)

#     if args.verbose:
#         print(f"Baseline dates ({len(base_dates)}): {','.join(base_dates)}")
#         print(f"Wrote: {out_cls}")
#         print(f"Wrote: {out_int}")
#     else:
#         print(out_cls)
#         print(out_int)
#     return 0


# if __name__ == '__main__':
#     raise SystemExit(main())


def main(argv=None) -> int:
    """
    Run the legacy EDS-style change detection for one scene and one
    seasonal window, then write out two ENVI rasters:

      - *_dllmz.img : change class (clearing / no-clearing etc.)
      - *_dljmz.img : interpretation layers + clearing probability

    This function is usually called from the command line, e.g.:

        python script.py \
          --scene p104r072 \
          --start-date 20200611 \
          --end-date   20220812
    """
    # ---------------------------------------------
    # 1. Read command-line options
    # ---------------------------------------------
    ap = argparse.ArgumentParser(description="Legacy-method change detection (seasonal window)")
    ap.add_argument('--scene', required=True, help="Scene code, e.g. p104r072")
    ap.add_argument('--start-date', required=True, help="Start date YYYYMMDD (baseline up to here, FPC start target)")
    ap.add_argument('--end-date', required=True, help="End date YYYYMMDD (FPC end target)")
    ap.add_argument('--dc4-glob', help="Optional glob for dc4 FPC images; if missing, use default compat layout")
    ap.add_argument('--start-db8', help="Optional explicit path to start reflectance stack (db8)")
    ap.add_argument('--end-db8', help="Optional explicit path to end reflectance stack (db8)")
    ap.add_argument('--window-start', help="Seasonal window start as MMDD; defaults to start-date month/day")
    ap.add_argument('--window-end', help="Seasonal window end as MMDD; defaults to end-date month/day")
    ap.add_argument('--lookback', type=int, default=10, help="How many years to look back for the baseline (default 10)")
    ap.add_argument('--omit-fpc-start-threshold', action='store_true',
                    help="Skip the rule that forces no-clearing where starting FPC < 108")
    ap.add_argument('--verbose', action='store_true', help="Print extra information (baseline dates, output paths)")
    args = ap.parse_args(argv)

    # Normalise scene code to lower case (e.g. 'P104R072' -> 'p104r072')
    scene = args.scene.lower()

    # Short names for the key dates:
    sd = args.start_date  # start date YYYYMMDD (string)
    ed = args.end_date    # end date   YYYYMMDD (string)

    # Seasonal window:
    # If the user did not specify a window, use the month+day from
    # the start and end dates:
    #   ws = start month/day  (MMDD)
    #   we = end   month/day  (MMDD)
    ws = args.window_start or sd[4:]
    we = args.window_end   or ed[4:]

    # ---------------------------------------------
    # 2. Find the input reflectance stacks (db8)
    # ---------------------------------------------
    # If the user gave explicit paths for the start/end db8 stacks,
    # use those; otherwise, build standard filenames used in the
    # legacy system.
    if args.start_db8 and args.end_db8:
        start_db8 = args.start_db8
        end_db8 = args.end_db8
    else:
        start_db8 = stdProjFilename(f"lztmre_{scene}_{sd}_db8mz.img")
        end_db8   = stdProjFilename(f"lztmre_{scene}_{ed}_db8mz.img")

    # Basic safety check: both files must exist.
    if not os.path.exists(start_db8) or not os.path.exists(end_db8):
        raise SystemExit("Start/end db8 files not found; provide --start-db8/--end-db8 or build them.")

    # ---------------------------------------------
    # 3. Find the FPC time-series (dc4 images)
    # ---------------------------------------------
    # dc4 images hold the fractional cover (FPC) stack over many dates.
    # Prefer an explicit glob pattern if the user gives one; otherwise,
    # look in the standard compat directory for this scene.
    if args.dc4_glob:
        # Use the pattern directly (e.g. '/path/to/lztmre_p104r072_*_dc4mz.img')
        dc4_files = sorted(glob.glob(args.dc4_glob))
    else:
        # Build a standard path to where dc4 images live for this scene.
        # We use a dummy filename to find the folder, then glob inside it.
        base = Path(stdProjFilename(f"lztmre_{scene}_00000000_dc4mz.img")).parent
        dc4_files = sorted(glob.glob(str(base / f"lztmre_{scene}_*_dc4mz.img")))

    if not dc4_files:
        raise SystemExit("No dc4 images found")

    # ---------------------------------------------
    # 4. Load reflectance (db8) and FPC (dc4), align shapes
    # ---------------------------------------------
    # Load start/end reflectance stacks; keep georeferencing from the start.
    ref_start, georef = load_raster(start_db8)
    ref_end, _ = load_raster(end_db8)

    # Load each dc4 image (FPC). Each dc4 is expected to be a single band.
    raw_dc4 = []  # list of 2D arrays, one per date
    dates = []    # corresponding list of dates as 'YYYYMMDD' strings
    for p in dc4_files:
        arr, _ = load_raster(p)
        if arr.shape[0] != 1:
            # The code expects dc4 images to be 1-band rasters.
            raise SystemExit(f"dc4 must be single band: {p}")
        raw_dc4.append(arr[0])      # take the single band
        dates.append(parse_date(p)) # extract date from filename

    # The reflectance and dc4 images might not be *exactly* the same size.
    # To keep everything consistent, we crop all arrays to the smallest
    # common height/width across all inputs.
    ys = []
    xs = []
    for a in [ref_start, ref_end] + raw_dc4:
        if a.ndim == 3:
            # Multiband: (bands, rows, cols)
            _, y, x = a.shape
        else:
            # Single band: (rows, cols)
            y, x = a.shape
        ys.append(y)
        xs.append(x)

    # Common minimal size
    min_y = min(ys)
    min_x = min(xs)

    # Helper function to crop any array (single or multi-band) to [min_y, min_x].
    def crop(a):
        if a.ndim == 3:
            # Crop along the last two dimensions (rows, cols)
            return a[..., :min_y, :min_x]
        return a[:min_y, :min_x]

    # Crop & convert reflectance to float32 for later maths
    ref_start = crop(ref_start).astype(np.float32)
    ref_end   = crop(ref_end).astype(np.float32)

    # Crop all dc4 images to the common shape
    raw_dc4 = [crop(a) for a in raw_dc4]

    # ---------------------------------------------
    # 5. Build the baseline FPC time-series (seasonal window + lookback)
    # ---------------------------------------------
    # We want a "baseline" that represents typical FPC values before the
    # change period. The rules are:
    #   - Look back up to N years (lookback).
    #   - Only use dates within the seasonal window (ws..we).
    #   - For each year, pick at most one date (closest to the window end).
    #   - Only use dates <= start date (sd).
    end_year = int(ed[:4])
    start_cutoff = sd  # do not use dates after the chosen start date

    # Group dc4 images by year.
    by_year = {}
    for d, a in zip(dates, raw_dc4):
        y = int(d[:4])

        # Skip if outside the lookback range.
        if y < end_year - args.lookback + 1 or y > end_year:
            continue

        # Skip if later than the start date (we want "history" only).
        if d > start_cutoff:
            continue

        # Skip if outside the seasonal window (e.g. not in dry season)
        if not in_window(d, ws, we):
            continue

        by_year.setdefault(y, []).append((d, a))

    # Within each year, choose the date closest to the "end" of the window
    # (we use MMDD distance to the target end MMDD).
    tm, td = int(we[:2]), int(we[2:])  # target month, day from end of window

    def md_dist(d: str) -> int:
        """Rough distance in days between date d and target month/day (tm, td)."""
        return abs((int(d[4:6]) - tm) * 31 + (int(d[6:8]) - td))

    base_dates: List[str] = []
    base_raw: List[np.ndarray] = []

    for y in sorted(by_year.keys()):
        lst = by_year[y]
        if lst:
            # Pick the date in this year closest to the target window end.
            d, a = sorted(lst, key=lambda t: md_dist(t[0]))[0]
            base_dates.append(d)
            base_raw.append(a)

    # If we ended up with fewer than 2 baseline images, fall back to:
    #   "all available dc4 prior to start within the window"
    if len(base_dates) < 2:
        base_dates = [d for d in dates if (d <= start_cutoff and in_window(d, ws, we))]
        base_raw = [a for d, a in zip(dates, raw_dc4) if (d <= start_cutoff and in_window(d, ws, we))]
        if len(base_dates) < 2:
            # The algorithm requires at least 2 images to define a baseline.
            raise SystemExit("Baseline too small (<2 images) after seasonal filtering")

    # ---------------------------------------------
    # 6. Turn baseline into normalised FPC & time-series stats
    # ---------------------------------------------
    # Convert each baseline image into the legacy-style normalised FPC.
    base_norm = [normalise_fpc(a) for a in base_raw]

    # For each pixel, we now compute:
    #   - mean, std, standard error
    #   - slope and intercept of a linear trend over time (decimal years)
    ts_mean, ts_std, ts_stderr, ts_slope, ts_intercept = timeseries_stats(base_norm, base_dates)

    # ---------------------------------------------
    # 7. Pick start and end FPC images for change detection
    # ---------------------------------------------
    # We want two FPC images:
    #   - one representing the "start" of the change period
    #   - one representing the "end"
    #
    # If dc4 exists exactly on the requested dates (sd, ed) we use them.
    # Otherwise, we pick the nearest date within the seasonal window.
    def nearest_idx(target: str, pool_dates: List[str]) -> int:
        """Return the index of the dc4 image closest in time to 'target'."""
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
        # If we never found anything inside the window, fall back to index 0.
        return best[1] if best else 0

    idx_start = nearest_idx(sd, dates)
    idx_end   = nearest_idx(ed, dates)

    # Corresponding raw FPC images
    fpc_start_raw = raw_dc4[idx_start]
    fpc_end_raw   = raw_dc4[idx_end]

    # Normalised versions for use in the indices/tests
    fpc_start_norm = normalise_fpc(fpc_start_raw)
    fpc_end_norm   = normalise_fpc(fpc_end_raw)

    # ---------------------------------------------
    # 8. Compute legacy indices and tests
    # ---------------------------------------------
    # fpcDiff: difference between end and start normalised FPC.
    fpcDiff = fpc_end_norm.astype(np.float32) - fpc_start_norm.astype(np.float32)

    # fpcDiffStdErr: FPC difference weighted by baseline standard error.
    # The minus sign follows the original legacy sign convention.
    fpcDiffStdErr = -fpcDiff * ts_stderr

    # Predict what the FPC should be at the end date, based on baseline trend.
    prediction_decimal_year = decimal_year(ed)
    predictedNormedFpc = ts_intercept + ts_slope * prediction_decimal_year

    # Observed FPC at the end date.
    observedNormedFpc = fpc_end_norm.astype(np.float32)

    # sTest and tTest start as zero everywhere.
    sTest = np.zeros_like(observedNormedFpc, dtype=np.float32)
    tTest = np.zeros_like(observedNormedFpc, dtype=np.float32)

    # Pixels where we trust the baseline stats:
    valid_stderr = ts_stderr >= 0.2
    valid_std    = ts_std    >= 0.2

    # sTest: how far the observed FPC is from the predicted trend
    # in units of standard error.
    sTest[valid_stderr] = (
        (observedNormedFpc[valid_stderr] - predictedNormedFpc[valid_stderr])
        / ts_stderr[valid_stderr]
    )

    # tTest: how far the observed FPC is from the baseline mean
    # in units of standard deviation.
    tTest[valid_std] = (
        (observedNormedFpc[valid_std] - ts_mean[valid_std])
        / ts_std[valid_std]
    )

    # ---------------------------------------------
    # 9. Spectral index from start/end reflectance (db8)
    # ---------------------------------------------
    # The spectral index combines multiple reflectance bands (2,3,5,6)
    # at start and end, using legacy weights and log1p() for stability.
    refStart = ref_start
    refEnd   = ref_end

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

    # Combined index that mixes spectral change, FPC change, and the tests.
    combinedIndex = (
        -11.972499 * spectralIndex
        - 0.40357223 * fpcDiff
        - 5.2609715  * tTest
        - 4.3794265  * sTest
    ).astype(np.float32)

    # ---------------------------------------------
    # 10. Assign change classes (clearing / no clearing)
    # ---------------------------------------------
    # Values:
    #   10 = no clearing (default)
    #   3  = FPC-only signal
    #   34..39 = increasing clearing confidence/strength
    NO_CLEARING   = 10
    NULL_CLEARING = 0

    # Start with all pixels set to "no clearing".
    changeclass = np.full(spectralIndex.shape, NO_CLEARING, dtype=np.uint8)

    # Apply a set of legacy threshold rules to classify clearing strength.
    changeclass[combinedIndex > 21.80] = 34
    changeclass[(combinedIndex > 27.71) & (sTest < -0.27) & (spectralIndex < -0.86)] = 35
    changeclass[(combinedIndex > 33.40) & (sTest < -0.60) & (spectralIndex < -1.19)] = 36
    changeclass[(combinedIndex > 39.54) & (sTest < -1.01) & (spectralIndex < -1.50)] = 37
    changeclass[(combinedIndex > 47.05) & (sTest < -1.55) & (spectralIndex < -1.84)] = 38
    changeclass[(combinedIndex > 58.10) & (sTest < -2.34) & (spectralIndex < -2.27)] = 39

    # Class 3: strong FPC signal where FPC change is large and tTest is
    # not strongly negative (so we treat it differently from clearing).
    changeclass[(tTest > -1.70) & (fpcDiffStdErr > 740)] = 3

    # Optional rule:
    # If the starting FPC is very low (<108), force "no clearing".
    # Idea: you can’t "clear" where there wasn’t much cover to begin with.
    if not args.omit_fpc_start_threshold:
        changeclass[fpc_start_raw < 108] = NO_CLEARING

    # Null out pixels where reflectance has zeros in any band at start or end.
    # This catches areas outside valid data (e.g. nodata edges).
    refNullMask = (refStart == 0).any(axis=0) | (refEnd == 0).any(axis=0)
    changeclass[refNullMask] = NULL_CLEARING

    # ---------------------------------------------
    # 11. Build interpretation layers & clearing probability
    # ---------------------------------------------
    # For visual interpretation, we stretch the spectral, sTest, and combined
    # indices into 1..255 ranges, and compute a clearing probability.
    spectralMean = float(np.mean(spectralIndex[spectralIndex != 0])) if np.any(spectralIndex != 0) else 0.0
    spectralStd  = float(np.std(spectralIndex[spectralIndex != 0]))  if np.any(spectralIndex != 0) else 1.0
    sTestMean    = float(np.mean(sTest[sTest != 0]))                  if np.any(sTest != 0)         else 0.0
    sTestStd     = float(np.std(sTest[sTest != 0]))                   if np.any(sTest != 0)         else 1.0
    combMean     = float(np.mean(combinedIndex[combinedIndex != 0]))  if np.any(combinedIndex != 0) else 0.0
    combStd      = float(np.std(combinedIndex[combinedIndex != 0]))   if np.any(combinedIndex != 0) else 1.0

    # Debug prints to help understand the stretch statistics.
    print(f"[EDS DEBUG] - spectralMean {spectralMean}")
    print(f"[EDS DEBUG] - spectralStd {spectralStd}")
    print(f"[EDS DEBUG] - sTestMean {sTestMean}")
    print(f"[EDS DEBUG] - sTestStd {sTestStd}")
    print(f"[EDS DEBUG] - combMean {combMean}")
    print(f"[EDS DEBUG] - combStd {combStd}")

    # Stretch each index into display-friendly 1..255 range.
    spectralStretched = stretch(spectralIndex, spectralMean, spectralStd, 2, 1, 255, 0)
    sTestStretched    = stretch(sTest,         sTestMean,    sTestStd,    10, 1, 255, 0)
    combinedStretched = stretch(combinedIndex, combMean,     combStd,     10, 1, 255, 0)

    # Clearing probability formula from the legacy method.
    clearingProb = 200 * (1 - np.exp(-((0.01227 * combinedIndex) ** 3.18975)))
    clearingProb = np.round(clearingProb).astype(np.uint8)
    clearingProb[combinedIndex <= 0] = 0

    # ---------------------------------------------
    # 12. Write outputs to ENVI rasters (DLL + DLJ)
    # ---------------------------------------------
    # era string encodes the start and end dates.
    era = f"d{sd}{ed}"

    # Put outputs in the same folder as the start db8 (i.e. the compat
    # scene folder).
    base_dir = Path(start_db8).parent

    out_cls = stdProjFilename(str(base_dir / f"lztmre_{scene}_{era}_dllmz.img"))
    out_int = stdProjFilename(str(base_dir / f"lztmre_{scene}_{era}_dljmz.img"))

    # Make sure the folder exists.
    Path(out_cls).parent.mkdir(parents=True, exist_ok=True)

    # DLL: single-band change class raster.
    write_envi(out_cls, [changeclass], georef, dtype=gdal.GDT_Byte, nodata=0)

    # DLJ: 4-band interpretation raster:
    #   [spectral, sTest, combined, clearingProb]
    write_envi(
        out_int,
        [spectralStretched, sTestStretched, combinedStretched, clearingProb],
        georef,
        dtype=gdal.GDT_Byte,
        nodata=0,
    )

    # ---------------------------------------------
    # 13. Friendly console output
    # ---------------------------------------------
    if args.verbose:
        print(f"Baseline dates ({len(base_dates)}): {','.join(base_dates)}")
        print(f"Wrote: {out_cls}")
        print(f"Wrote: {out_int}")
    else:
        # In non-verbose mode, just print the paths (one per line).
        print(out_cls)
        print(out_int)

    return 0


if __name__ == '__main__':
    # When run as a script (not imported), execute main() and exit
    # with its return code.
    raise SystemExit(main())

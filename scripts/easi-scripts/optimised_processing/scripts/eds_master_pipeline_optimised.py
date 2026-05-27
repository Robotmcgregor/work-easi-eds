#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# MIT License

# Copyright (c) 2026 Robert McGregor

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ------------------------------------------------------------------------------


"""Optimised EDS processing pipeline (NDVI seasonal-window; datacube-native).

This file is the *main entrypoint* people run.

The script:
1) Picks a "best" start and end Landsat SR scene for your requested dates.
2) Builds a list of NDVI scenes in a seasonal window (baseline time-series).
3) Ensures NDVI scenes exist in S3 (builds them if missing).
4) Downloads NDVI scenes locally (so the legacy method can read them).
5) Builds SR composites (GA0) for the chosen start/end dates.
6) Runs the legacy seasonal-window change-detection method to produce DLL/DLJ.
7) Converts outputs to GeoTIFF COGs and uploads them to S3.
8) Creates masks + shapefiles for "strong" and "clear" detections.

Key idea: everything is written into a *run-scoped folder* so repeated runs don't
overwrite each other (see --run-tag/--run-id).

Local run layout:
    <work-dir>/<tile>/<run-tag>/
        ndvi_work/       # scratch space for building NDVI scenes
        ga1_stage/       # local downloaded NDVI COGs
        ga0_work/        # scratch space for SR composites
        legacy_outputs/  # DLL/DLJ outputs produced by the legacy method
        outputs_cog/     # converted COG outputs ready for upload
        maskvec_work/    # masks + vectors created from DLJ
        diagnostics/     # optional stats CSVs/JSONs/plots
        sr_raw_cog/      # optional export of raw SR composites

S3 layout:
    Scene-date outputs:
        {s3_prefix}/tiles/{tile}/{YYYY}/{YYYYMM}/...
    Final run outputs:
        {s3_prefix}/tiles/{tile}/outputs/{run_tag}/...
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import re
import shutil
from pathlib import Path
from typing import Optional

import pandas as pd

from tasks.task02_resolve_sr_dates import resolve_sr_start_end
from tasks.task03_ensure_seasonal_ndvi import build_seasonal_ndvi_plan, ensure_seasonal_ndvi_in_s3
from tasks.task04_build_ga0_sr_composite import build_ga0_sr_to_s3
from tasks.task05_run_legacy_method import run_legacy_ndvi_window
from tasks.task06_convert_and_upload_outputs import convert_outputs_to_cog_and_upload
from tasks.task07_stage_ga1_locally import stage_ga1_ndvi_locally
from tasks.task08_masks_and_vectors import make_masks_and_vectors
from lib.s3_io import upload_file_to_s3
from lib.dates import normalise_yyyymmdd
from lib.cog import ensure_pyarrow
from lib.s3_io import parse_s3_uri
from lib.run_log import (
    default_run_log_uri,
    finish_run_row,
    load_run_log,
    new_run_row,
    save_run_log,
)


def parse_args():
    ap.add_argument(
        '--max-tiles',
        type=int,
        default=None,
        help='In --run-all-tiles mode, only process the first N tiles (after offset). Useful for batching.',
    )
    ap.add_argument(
        '--tile-offset',
        type=int,
        default=0,
        help='In --run-all-tiles mode, skip the first OFFSET tiles (after resume logic). Useful for batching.',
    )

    """Parse command-line arguments.

    These flags are grouped roughly as:
    - What to process: tile, start/end date
    - Where data lives: S3 bucket/prefix and local work directory
    - Data quality controls: cloud-max
    - A/B testing knobs for the legacy method: SR scaling + baseline stats mode
    - Debugging outputs: --verbose, --diagnostics, --stop-after-dlj
    """
    ap = argparse.ArgumentParser('Optimised EDS processing (NDVI seasonal window)')
    ap.add_argument(
        '--run-all-tiles',
        action='store_true',
        help='Run the pipeline for all tiles in the shapefile (overrides --tile). Supports resume if interrupted.',
    )
    ap.add_argument(
        '--all-tiles-log',
        default='all_tiles_run_log.csv',
        help='Path to the persistent log file for --run-all-tiles mode (CSV).',
    )
    ap.add_argument(
        '--cleanup-work-dir',
        action='store_true',
        help='Delete the entire run folder in --work-dir after processing completes (use with caution!).',
    )

    ap.add_argument('--tile', required=True, help='e.g. p115r078')
    ap.add_argument('--start-date', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end-date', required=True, help='YYYY-MM-DD')

    ap.add_argument('--s3-bucket', required=True)
    ap.add_argument('--s3-prefix', required=True)

    ap.add_argument(
        '--run-log-uri',
        default=None,
        help=(
            'Master parquet file recording EDS runs (S3 or local path). '
            'If omitted, defaults to s3://<bucket>/<prefix>/runs/optimised_eds_runs.parquet'
        ),
    )
    ap.add_argument(
        '--run-manifest-uri',
        default=None,
        help=(
            'Optional parquet URI (S3 or local path) to write the run manifest (NDVI baseline plan + SR picks). '
            'If omitted, defaults under s3://<bucket>/<prefix>/runs/manifests/<tile>/<run_tag>_manifest.parquet'
        ),
    )

    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--tile-shp', default='/home/jovyan/assets/eds_lsat_grid_min_max.shp')

    ap.add_argument('--cloud-max', type=float, default=40.0)

    ap.add_argument('--sr-products', nargs='+', default=['ga_ls8c_ard_3', 'ga_ls9c_ard_3'])
    ap.add_argument('--ndvi-products', nargs='+', default=['ga_ls8c_ard_3', 'ga_ls9c_ard_3'])

    ap.add_argument('--target-epsg', type=int, default=0)
    ap.add_argument('--resolution', type=float, default=30.0)
    ap.add_argument('--chunk', type=int, default=2048)

    ap.add_argument('--lookback', type=int, default=10)

    ap.add_argument(
        '--export-vectors-to-work-dir',
        action='store_true',
        help=(
            "Copy vector outputs into a simple folder under --work-dir for easy download "
            "(e.g. <work-dir>/vectors/<tile>/<run-tag>/...). Useful when ArcGIS Cloud Storage "
            "Connections can't open/export .gpkg in-place."
        ),
    )

    ap.add_argument('--rebase', action='store_true', help='Overwrite existing derived products')
    ap.add_argument('--dry-run', action='store_true')

    ap.add_argument('--diagnostics', action='store_true')
    ap.add_argument('--verbose', action='store_true')

    ap.add_argument(
        '--dlj-troubleshoot',
        action='store_true',
        help='After DLJ is produced, print per-band pixel stats (and band descriptions).',
    )
    ap.add_argument(
        '--stop-after-dlj',
        action='store_true',
        help='Exit immediately after DLJ is produced (for debugging/inspection).',
    )

    run_group = ap.add_mutually_exclusive_group()
    run_group.add_argument(
        '--run-tag',
        default=None,
        help='Optional run tag for output folder (default: tile_d<start><end>)',
    )
    run_group.add_argument(
        '--run-id',
        default=None,
        help='Alias for --run-tag (e.g. run1, run2). Useful for separating repeated runs.',
    )

    ap.add_argument('--strong-threshold', type=int, default=60)
    ap.add_argument('--clear-threshold', type=int, default=80)
    ap.add_argument('--min-area-ha', type=float, default=10.0)

    # Legacy-method controls (for A/B comparisons)
    ap.add_argument(
        '--legacy-sr-scale',
        type=float,
        default=None,
        help=(
            'Pass-through to legacy method: MANUAL override for SR scaling. '
            'Divides SR bands by this factor before log1p() (e.g. 10000 for reflectance*10000). '
            'If omitted, legacy method auto-detects scaling unless --legacy-no-auto-sr-scale is set.'
        ),
    )
    ap.add_argument(
        '--legacy-no-auto-sr-scale',
        action='store_true',
        help=(
            'Pass-through to legacy method: disable SR scale auto-detection and FORCE no scaling (sr_scale_factor=1). '
            'Useful as a baseline/debug option.'
        ),
    )

    ap.add_argument(
        '--legacy-baseline-include-nodata',
        action='store_true',
        help=(
            'Pass-through to legacy method: use LEGACY baseline stats (include nodata zeros in baseline mean/std/slope). '
            'Default (recommended) ignores zeros (treats 0 as nodata).'
        ),
    )

    ap.add_argument(
        '--copy-to-home',
        action='store_true',
        help='Copy ga0 + outputs + masks + shapefiles to a folder under /home/jovyan for easy retrieval.',
    )
    ap.add_argument(
        '--home-out-dir',
        default='/home/jovyan/eds-outputs',
        help='Base folder for --copy-to-home outputs (default: /home/jovyan/eds-outputs).',
    )
    ap.add_argument(
        '--zip-home',
        action='store_true',
        help='Zip the copied home output folder after copying.',
    )

    ap.add_argument(
        '--export-sr-raw-cog',
        action='store_true',
        help='Copy the unmasked SR composites into a run-scoped sr_raw_cog folder.',
    )
    ap.add_argument(
        '--export-sr-raw-cog-dirname',
        default='sr_raw_cog',
        help='Subfolder under the run root for exported SR raw COGs (default: sr_raw_cog).',
    )

    return ap.parse_args()


def _default_run_manifest_uri(bucket: str, prefix: str, tile: str, run_tag: str) -> str:
    # Builds the default S3 path for saving the run manifest file, based on user input.
    prefix = prefix.strip('/')
    return f"s3://{bucket}/{prefix}/runs/manifests/{tile}/{run_tag}_manifest.parquet"


def _upload_run_diagnostics_to_s3(
    # Uploads all diagnostic files (like logs or plots) for a run to a special folder in S3.
    *,
    diagnostics_dir: Path,
    bucket: str,
    s3_prefix: str,
    tile: str,
    run_tag: str,
) -> list[str]:
    """Upload all diagnostic artefacts for a run to S3.

    Destination layout (kept separate from primary outputs):
      {s3_prefix}/diagnostics/tiles/{tile}/outputs/{run_tag}/...
    """
    diagnostics_dir = Path(diagnostics_dir)
    if not diagnostics_dir.exists():
        return []

    uploaded: list[str] = []
    base = f"{s3_prefix.rstrip('/')}/diagnostics/tiles/{tile}/outputs/{run_tag}"

    for p in sorted(diagnostics_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(diagnostics_dir).as_posix()
        key = f"{base}/{rel}"
        upload_file_to_s3(str(p), bucket=bucket, key=key)
        uploaded.append(f"s3://{bucket}/{key}")

    return uploaded


def _print_raster_stats(path: Path, label: str) -> None:
    # Prints out simple statistics about a raster image file, mainly for debugging or checking results.
    """Print lightweight stats for a raster (intended for DLJ/DLL debugging)."""
    try:
        import numpy as np  # type: ignore[import-not-found]
        import rasterio  # type: ignore[import-not-found]
    except Exception as e:
        print(f"[DLJ-DBG] Cannot import rasterio/numpy for stats: {e}")
        return

    path = Path(path)
    if not path.exists():
        print(f"[DLJ-DBG] Missing raster for stats: {path}")
        return

    with rasterio.open(path) as ds:
        print(f"[DLJ-DBG] {label}: {path}")
        print(f"[DLJ-DBG]  driver={ds.driver} size={ds.width}x{ds.height} count={ds.count} dtype={ds.dtypes}")
        print(f"[DLJ-DBG]  nodata={ds.nodata} crs={ds.crs}")
        try:
            print(f"[DLJ-DBG]  descriptions={ds.descriptions}")
        except Exception:
            pass

        for b in range(1, ds.count + 1):
            arr = ds.read(b)
            nodata = ds.nodata
            if nodata is None:
                # For these outputs, 0 is the implicit nodata.
                nodata = 0
            mask = arr != nodata
            total = arr.size
            valid = int(mask.sum())
            if valid == 0:
                print(f"[DLJ-DBG]  band{b}: valid=0/{total} (all nodata={nodata})")
                continue
            v = arr[mask].astype(np.float64)
            print(
                f"[DLJ-DBG]  band{b}: valid={valid}/{total} "
                f"min={v.min():.3f} max={v.max():.3f} mean={v.mean():.3f} std={v.std():.3f}"
            )
            # Quick signal: how much is just zeros?
            z = int((arr == 0).sum())
            print(f"[DLJ-DBG]   zeros={z}/{total}")


def _dlj_has_any_valid_pixels(path: Path) -> bool:
    # Checks if a raster image has any real (non-empty) data in it. Returns True if there is any valid data.
    """Return True if a raster has any non-nodata pixel in any band.

    For these products, nodata is typically encoded as 0.
    """
    try:
        import numpy as np  # type: ignore[import-not-found]
        import rasterio  # type: ignore[import-not-found]
    except Exception:
        # If we can't import, don't hard-fail the pipeline.
        return True

    path = Path(path)
    if not path.exists():
        return False

    with rasterio.open(path) as ds:
        nodata = ds.nodata
        if nodata is None:
            nodata = 0
        for b in range(1, ds.count + 1):
            arr = ds.read(b)
            if int(np.count_nonzero(arr != nodata)) > 0:
                return True
    return False



# --- Procedural replacement for RunPaths class ---
def make_run_paths(args, tile, run_tag):
    """
    Returns a dictionary with all the folder paths for this run.
    Each key is a folder name, value is a Path object.
    """
    run_root = Path(args.work_dir) / tile / run_tag
    return {
        "run_root": run_root,
        "ndvi_work": run_root / 'ndvi_work',
        "ga1_stage": run_root / 'ga1_stage',
        "ga0_work": run_root / 'ga0_work',
        "legacy_outputs": run_root / 'legacy_outputs',
        "outputs_cog": run_root / 'outputs_cog',
        "maskvec_work": run_root / 'maskvec_work',
        "diagnostics": run_root / 'diagnostics',
        "sr_raw_cog": run_root / args.export_sr_raw_cog_dirname,
    }

def ensure_directories(paths, include_sr_raw_cog=False):
    """
    Makes sure all the folders for this run exist on disk.
    """
    keys = [
        "run_root", "ndvi_work", "ga1_stage", "ga0_work", "legacy_outputs",
        "outputs_cog", "maskvec_work", "diagnostics"
    ]
    if include_sr_raw_cog:
        keys.append("sr_raw_cog")
    for key in keys:
        paths[key].mkdir(parents=True, exist_ok=True)


def _copy_run_artifact(src: Path, dst_dir: Path) -> Path:
    # Copies a file into a run's folder, used for saving extra outputs or exports.
    """Copy a file into a run folder (used for optional exports)."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return dst


def _norm_yyyymmdd(iso: str) -> str:
    # Changes a date from 'YYYY-MM-DD' to 'YYYYMMDD' format for internal use.
    """Convert YYYY-MM-DD into YYYYMMDD (the pipeline's internal date format)."""
    y, m, d = iso.split('-')
    return f'{y}{m}{d}'


def _extract_epsg(value) -> int | None:
    # Tries to pull out an EPSG code (a number that describes a map projection) from different types of input.
    """Try to pull an EPSG code out of a variety of values.

    This exists because some inputs come from shapefiles/metadata where CRS may be
    stored as an int, a string like "EPSG:32756", or embedded in WKT.
    """
    if value is None:
        return None

    if isinstance(value, int):
        return value

    s = str(value).strip()
    if not s:
        return None

    if s.isdigit():
        return int(s)

    m = re.search(r'EPSG[:= ]*(\d+)', s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))

    m = re.search(r'\b(\d{4,6})\b', s)
    if m:
        return int(m.group(1))

    return None


def derive_target_epsg_wgs84_utm_from_lonlat(lon: float, lat: float) -> int:
    # Figures out the correct UTM zone (a type of map projection) for a given longitude and latitude.
    """Given a lon/lat point, return the WGS84 UTM EPSG code for that location."""
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone


def resolve_output_epsg_from_row(row, cli_target_epsg: int) -> int:
    # Decides which map projection (EPSG code) to use for a scene, based on user input or the data itself.
    """Choose the output CRS (EPSG code) for a scene.

    Priority order:
    1) If the user provided --target-epsg, use it.
    2) Otherwise, derive WGS84 UTM from the scene bbox centre.
    3) If bbox is missing, try to fall back to any EPSG-like field present.
    """
    if cli_target_epsg and int(cli_target_epsg) > 0:
        return int(cli_target_epsg)

    def _row_get(r, key, default=None):
        try:
            if hasattr(r, '__contains__') and key in r:
                return r[key]
        except Exception:
            pass
        return getattr(r, key, default)

    lon_min = _row_get(row, 'lon_min')
    lon_max = _row_get(row, 'lon_max')
    lat_min = _row_get(row, 'lat_min')
    lat_max = _row_get(row, 'lat_max')

    if None not in (lon_min, lon_max, lat_min, lat_max):
        assert lon_min is not None and lon_max is not None
        assert lat_min is not None and lat_max is not None
        centre_lon = (float(lon_min) + float(lon_max)) / 2.0
        centre_lat = (float(lat_min) + float(lat_max)) / 2.0
        return derive_target_epsg_wgs84_utm_from_lonlat(centre_lon, centre_lat)

    for attr in ['target_epsg', 'native_epsg', 'epsg', 'crs_epsg', 'crs']:
        epsg = _extract_epsg(_row_get(row, attr))
        if epsg:
            return epsg

    raise ValueError('Could not resolve target EPSG from row')


def main():
    # This is the main function that runs the entire pipeline for one tile and one start/end date pair.
    # It coordinates all the steps: picking images, building plans, running processing, saving results, and logging.
    """Run the pipeline end-to-end for one tile and one start/end date pair."""
    args = parse_args()
    tile = args.tile.lower().strip()

    sd = _norm_yyyymmdd(args.start_date)
    ed = _norm_yyyymmdd(args.end_date)
    run_tag = args.run_tag or args.run_id or f'{tile}_d{sd}{ed}'

    # Create all run folder paths as a dictionary
    paths = make_run_paths(args, tile, run_tag)
    ensure_directories(paths, include_sr_raw_cog=bool(args.export_sr_raw_cog))

    print(f'[INFO] Local run root: {paths["run_root"]}')
    print(f"[INFO] Run outputs S3 prefix: {args.s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}")

    run_log_uri = args.run_log_uri or default_run_log_uri(args.s3_bucket, args.s3_prefix)
    run_log_cache_dir = Path(args.work_dir) / tile / 'run_logs'

    run_manifest_uri = args.run_manifest_uri or _default_run_manifest_uri(
        args.s3_bucket, args.s3_prefix, tile, run_tag
    )

    # best-effort: load/append a "running" row early
    try:
        args = parse_args()

        if args.run_all_tiles:
            import geopandas as gpd
            import csv
            import traceback
            from datetime import datetime

            # Read all tile IDs from the shapefile
            gdf = gpd.read_file(args.tile_shp)
            tile_col = None
            for c in gdf.columns:
                if c.lower() in ('tile', 'tile_id', 'tileid', 'name', 'id'):
                    tile_col = c
                    break
            if tile_col is None:
                raise ValueError('Could not find tile ID column in shapefile')
            all_tiles = [str(t).lower().strip() for t in gdf[tile_col].unique()]

            # Load or create the persistent log
            log_path = Path(args.all_tiles_log)
            log = {}
            if log_path.exists():
                with open(log_path, 'r', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        log[row['tile']] = row

            # Only process tiles not marked as success
            to_run = [t for t in all_tiles if t not in log or log[t].get('status') != 'success']
            # Apply offset and max-tiles slicing
            offset = args.tile_offset or 0
            max_tiles = args.max_tiles if args.max_tiles is not None else None
            if offset > 0:
                to_run = to_run[offset:]
            if max_tiles is not None:
                to_run = to_run[:max_tiles]
            print(f"[BATCH] {len(to_run)} of {len(all_tiles)} tiles to process (resume mode, offset={offset}, max_tiles={max_tiles})")

            for tile in to_run:
                print(f"[BATCH] Processing tile: {tile}")
                status = 'unknown'
                error = ''
                start_time = datetime.now().isoformat()
                try:
                    # Patch args for this tile
                    args_tile = argparse.Namespace(**vars(args))
                    args_tile.tile = tile
                    # Call main logic for a single tile (recursive, but disables --run-all-tiles)
                    args_tile.run_all_tiles = False
                    # Use the same start/end dates as provided
                    # Call the main logic (single-tile mode)
                    # Use a function call to main_single_tile(args_tile), or inline the logic here
                    # For simplicity, call main() recursively with patched args
                    # But to avoid infinite recursion, factor out the single-tile logic
                    run_single_tile(args_tile)
                    status = 'success'
                except Exception as e:
                    status = 'failed'
                    error = f"{e}\n{traceback.format_exc()}"
                    print(f"[BATCH][ERROR] Tile {tile} failed: {e}")
                end_time = datetime.now().isoformat()
                # Update log
                log[tile] = {
                    'tile': tile,
                    'status': status,
                    'start_time': start_time,
                    'end_time': end_time,
                    'error': error,
                }
                # Write log after each tile
                with open(log_path, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['tile', 'status', 'start_time', 'end_time', 'error'])
                    writer.writeheader()
                    for row in log.values():
                        writer.writerow(row)
            print(f"[BATCH] All tiles processed. Log written to {log_path}")
            return

        # --- Single-tile logic below (factored out for batch mode) ---
        main_single_tile(args)


        target_epsg = int(sr.end_row['target_epsg'])
        # ...existing code from main() for a single tile...
        tile = args.tile.lower().strip()
        sd = _norm_yyyymmdd(args.start_date)
        ed = _norm_yyyymmdd(args.end_date)
        run_tag = args.run_tag or args.run_id or f'{tile}_d{sd}{ed}'
        paths = make_run_paths(args, tile, run_tag)
        ensure_directories(paths, include_sr_raw_cog=bool(args.export_sr_raw_cog))
        print(f'[INFO] Local run root: {paths["run_root"]}')
        print(f"[INFO] Run outputs S3 prefix: {args.s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}")
        run_log_uri = args.run_log_uri or default_run_log_uri(args.s3_bucket, args.s3_prefix)
        run_log_cache_dir = Path(args.work_dir) / tile / 'run_logs'
        run_manifest_uri = args.run_manifest_uri or _default_run_manifest_uri(
            args.s3_bucket, args.s3_prefix, tile, run_tag
        )
        try:
            run_log_df = load_run_log(run_log_uri, run_log_cache_dir)
        except Exception as e:
            print(f"[WARN] Could not load EDS run log from {run_log_uri!r}: {e}")
            run_log_df = pd.DataFrame()
        run_row = new_run_row(
            tile=tile,
            run_tag=run_tag,
            requested_start_yyyymmdd=sd,
            requested_end_yyyymmdd=ed,
            effective_start_yyyymmdd=sd,
            effective_end_yyyymmdd=ed,
            lookback_years=int(args.lookback),
            cloud_max=float(args.cloud_max),
            ndvi_products=[str(p) for p in (args.ndvi_products or [])],
            sr_products=[str(p) for p in (args.sr_products or [])],
            target_epsg=int(args.target_epsg),
            resolution=float(args.resolution),
            chunk=int(args.chunk),
            strong_threshold=int(args.strong_threshold),
            clear_threshold=int(args.clear_threshold),
            min_area_ha=float(args.min_area_ha),
            dry_run=bool(args.dry_run),
            rebase=bool(args.rebase),
            run_manifest_uri=run_manifest_uri,
            s3_bucket=args.s3_bucket,
            s3_prefix=args.s3_prefix,
        )
        run_id = run_row['run_id']
        try:
            if run_log_df is None or run_log_df.empty:
                run_log_df = pd.DataFrame([run_row])
            else:
                run_log_df = pd.concat(
                    [run_log_df, pd.DataFrame([run_row])],
                    ignore_index=True
                )
            save_run_log(run_log_df, run_log_uri, run_log_cache_dir)
        except Exception as e:
            print(f"[WARN] Could not write running EDS run-log row: {e}")
        error_message: Optional[str] = None
        final_status = 'success'
        # ...existing code from main() for a single tile continues here...
        # Copy/paste the rest of the main() logic here, or refactor as needed.
        # For brevity, you can move the rest of the main() code here.
        # ...existing code...
        platform = str(sr.end_row['platform']).lower().strip()  # e.g. 'sl8'
        platform_prefix = f"{platform}olre"
        cog_dll_name = Path(
            f"{platform_prefix}_{tile}_d{eff_sd}{eff_ed}_dll_e{target_epsg}.tif"
        )
        cog_dlj_name = Path(
            f"{platform_prefix}_{tile}_d{eff_sd}{eff_ed}_dlj_e{target_epsg}.tif"
        )
        print(f"[INFO] COG DLL target name: {cog_dll_name.name}")
        print(f"[INFO] COG DLJ target name: {cog_dlj_name.name}")

        if bool(args.dlj_troubleshoot) or bool(args.stop_after_dlj):
            print("\n[DLJ-DBG] Legacy method outputs produced; dumping stats (legacy filenames)")
            print(f"[DLJ-DBG]  legacy DLL name: {Path(outputs.dll_img).name}")
            print(f"[DLJ-DBG]  legacy DLJ name: {Path(outputs.dlj_img).name}")
            _print_raster_stats(Path(outputs.dll_img), label="DLL legacy")
            _print_raster_stats(Path(outputs.dlj_img), label="DLJ legacy")
            print("[DLJ-DBG] End legacy stats\n")

            if bool(args.stop_after_dlj):
                raise SystemExit("dlj failure")

        # ------------------------------------------------------------------
        # STEP 7: Convert outputs to Cloud Optimised GeoTIFFs (COGs) and upload.
        # COGs are easier to use in GIS tools and faster to read from cloud storage.
        # ------------------------------------------------------------------
        converted = convert_outputs_to_cog_and_upload(
            dll_src_img=outputs.dll_img,
            dlj_src_img=outputs.dlj_img,
            dll_final_name=cog_dll_name,
            dlj_final_name=cog_dlj_name,
            bucket=args.s3_bucket,
            prefix=args.s3_prefix,
            tile=tile,
            run_tag=run_tag,
            work_dir=paths["outputs_cog"],
        )

        if bool(args.dlj_troubleshoot):
            print("\n[DLJ-DBG] Converted COG outputs produced; dumping stats (final filenames)")
            print(f"[DLJ-DBG]  expected COG DLL name: {cog_dll_name.name}")
            print(f"[DLJ-DBG]  expected COG DLJ name: {cog_dlj_name.name}")
            print(f"[DLJ-DBG]  actual   COG DLL name: {Path(converted.dllmz_cog_local).name}")
            print(f"[DLJ-DBG]  actual   COG DLJ name: {Path(converted.dljmz_cog_local).name}")
            _print_raster_stats(Path(converted.dllmz_cog_local), label="DLL COG final")
            _print_raster_stats(Path(converted.dljmz_cog_local), label="DLJ COG final")
            print("[DLJ-DBG] End COG stats\n")

        dljmz_cog_local = Path(converted.dljmz_cog_local)

        for u in converted.uploaded:
            print('[OK]', u.s3_uri)

        # ------------------------------------------------------------------
        # STEP 8: Create masks + shapefiles.
        # These are the final outputs.
        # ------------------------------------------------------------------
        mv = make_masks_and_vectors(
            dljmz_cog_local=dljmz_cog_local,
            bucket=args.s3_bucket,
            s3_prefix=args.s3_prefix,
            tile=tile,
            run_tag=run_tag,
            strong_threshold=int(args.strong_threshold),
            clear_threshold=int(args.clear_threshold),
            min_area_ha=float(args.min_area_ha),
            work_dir=paths["maskvec_work"],
            rebase=bool(args.rebase),
            dry_run=bool(args.dry_run),
        )

        print(f'[OK] Strong mask -> s3://{args.s3_bucket}/{mv.strong_mask_s3}')
        print(f'[OK] Clear  mask -> s3://{args.s3_bucket}/{mv.clear_mask_s3}')
        print(f'[OK] Strong SHP  -> s3://{args.s3_bucket}/{mv.strong_shp_s3_prefix}/')
        print(f'[OK] Clear  SHP  -> s3://{args.s3_bucket}/{mv.clear_shp_s3_prefix}/')

        # Optional: also copy vectors to a top-level folder under --work-dir
        # so they are easy to download as local files.
        if bool(args.export_vectors_to_work_dir) and (not bool(args.dry_run)):
            try:
                import shutil

                src_vectors = paths["maskvec_work"] / 'vectors'
                dst_vectors = Path(args.work_dir) / 'vectors' / tile / run_tag

                if bool(args.rebase) and dst_vectors.exists():
                    shutil.rmtree(dst_vectors, ignore_errors=True)

                dst_vectors.mkdir(parents=True, exist_ok=True)

                for sub in ('strong', 'clear'):
                    src_sub = src_vectors / sub
                    if not src_sub.exists():
                        continue
                    shutil.copytree(src_sub, dst_vectors / sub, dirs_exist_ok=True)

                print(f"[OK] Local vectors copied -> {dst_vectors}")
            except Exception as e:
                print(f"[WARN] Failed to export vectors to --work-dir: {e}")

        # ------------------------------------------------------------------
        # STEP 8b: Upload any diagnostics artefacts to S3 (separate prefix).
        # This keeps primary outputs under .../tiles/{tile}/outputs/{run_tag}/
        # while storing diagnostics under .../diagnostics/tiles/{tile}/outputs/{run_tag}/
        # ------------------------------------------------------------------
        if bool(args.diagnostics) and (not bool(args.dry_run)):
            uploaded_diags = _upload_run_diagnostics_to_s3(
                diagnostics_dir=paths["diagnostics"],
                bucket=args.s3_bucket,
                s3_prefix=args.s3_prefix,
                tile=tile,
                run_tag=run_tag,
            )
            if uploaded_diags:
                print(f"[OK] Uploaded {len(uploaded_diags)} diagnostics artefacts to S3")
                print(f"[OK] Diagnostics S3 prefix: s3://{args.s3_bucket}/{args.s3_prefix.rstrip('/')}/diagnostics/tiles/{tile}/outputs/{run_tag}/")

        if bool(args.copy_to_home):
            from tasks.task09_copy_run_to_home import copy_run_to_home

            legacy_files = [Path(outputs.dll_img), Path(outputs.dlj_img)]
            for p in list(legacy_files):
                hdr = p.with_suffix('.hdr')
                if hdr.exists():
                    legacy_files.append(hdr)

            cog_files = [
                Path(converted.dllmz_cog_local),
                Path(converted.dljmz_cog_local),
            ]
            mask_files = [Path(mv.strong_mask_local), Path(mv.clear_mask_local)]
            vector_dirs = [
                paths["maskvec_work"] / 'vectors' / 'strong',
                paths["maskvec_work"] / 'vectors' / 'clear',
            ]

            home_copy = copy_run_to_home(
                run_tag=run_tag,
                home_out_dir=Path(args.home_out_dir),
                ga0_start_raw_local=Path(ga0_start.local_raw_path),
                ga0_end_raw_local=Path(ga0_end.local_raw_path),
                ga0_start_local=Path(ga0_start.local_clr_path),
                ga0_end_local=Path(ga0_end.local_clr_path),
                legacy_outputs=legacy_files,
                cog_outputs=cog_files,
                mask_outputs=mask_files,
                vector_dirs=vector_dirs,
                zip_after=bool(args.zip_home),
                dry_run=bool(args.dry_run),
            )

            if bool(args.dlj_troubleshoot) and (not bool(args.dry_run)):
                # Re-open the *home-copied* DLJ products and dump stats
                try:
                    copied_tifs = [ 
                        p for p in home_copy.copied
                        if p.suffix.lower() in {'.tif', '.tiff'}
                        and p.parent.name in {'legacy_outputs', 'cog_outputs'}
                        and 'dlj' in p.name.lower()
                    ]
                    if copied_tifs:
                        print("\n[DLJ-DBG] Home-copied DLJ products; dumping stats + checks")
                        any_fail = False
                        for p in copied_tifs:
                            _print_raster_stats(Path(p), label=f"HOME {p.parent.name} {p.name}")
                            ok = _dlj_has_any_valid_pixels(Path(p))
                            print(f"[DLJ-CHECK] {p.name}: {'PASS' if ok else 'FAIL (all nodata/zeros)'}")
                            any_fail = any_fail or (not ok)
                        print("[DLJ-DBG] End home DLJ checks\n")

                        if any_fail:
                            raise SystemExit("dlj failure")
                except Exception as e:
                    print(f"[WARN] Failed to read stats for home-copied COGs: {e}")

        print('[DONE] Optimised EDS processing complete.')

    except BaseException as e:
        final_status = 'failed'
        error_message = str(e)
        raise

    finally:
        # best-effort: finalize the run row
        try:
            finished_row = finish_run_row(
                run_row,
                status=final_status,
                error_message=error_message,
            )

            if run_log_df is None or run_log_df.empty:
                run_log_df = pd.DataFrame([finished_row])
            else:
                m = run_log_df['run_id'].astype(str) == str(run_id)
                if m.any():
                    for k, v in finished_row.items():
                        run_log_df.loc[m, k] = v
                else:
                    run_log_df = pd.concat([run_log_df, pd.DataFrame([finished_row])], ignore_index=True)

            save_run_log(run_log_df, run_log_uri, run_log_cache_dir)
        except Exception as e:
            print(f"[WARN] Could not finalize EDS run log: {e}")

        # Cleanup run folder if requested and not a dry run
        try:
            if getattr(args, 'cleanup_work_dir', False) and not getattr(args, 'dry_run', False):
                run_root = paths["run_root"]
                print(f"[CLEANUP] Deleting run folder: {run_root}")
                shutil.rmtree(run_root, ignore_errors=True)
                print(f"[CLEANUP] Run folder deleted.")
        except Exception as e:
            print(f"[WARN] Cleanup of run folder failed: {e}")


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
from __future__ import annotations

"""Optimised EDS processing pipeline (NDVI seasonal-window; datacube-native).

This file is the *main entrypoint* people run.

In plain English, it:
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
    """Parse command-line arguments.

    These flags are grouped roughly as:
    - What to process: tile, start/end date
    - Where data lives: S3 bucket/prefix and local work directory
    - Data quality controls: cloud-max
    - A/B testing knobs for the legacy method: SR scaling + baseline stats mode
    - Debugging outputs: --verbose, --diagnostics, --stop-after-dlj
    """
    ap = argparse.ArgumentParser('Optimised EDS processing (NDVI seasonal window)')

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
    prefix = prefix.strip('/')
    return f"s3://{bucket}/{prefix}/runs/manifests/{tile}/{run_tag}_manifest.parquet"


def _upload_run_diagnostics_to_s3(
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


@dataclass(frozen=True)
class RunPaths:
    """All folders used for a single run.

    A *run* is identified by tile + run_tag.
    Keeping run folders separate makes it easy to:
    - run the same tile multiple times without overwriting outputs
    - compare different settings (e.g. SR scaling) side-by-side
    """
    run_root: Path
    ndvi_work: Path
    ga1_stage: Path
    ga0_work: Path
    legacy_outputs: Path
    outputs_cog: Path
    maskvec_work: Path
    diagnostics: Path
    sr_raw_cog: Path

    @classmethod
    def from_args(cls, args, tile: str, run_tag: str) -> 'RunPaths':
        run_root = Path(args.work_dir) / tile / run_tag
        return cls(
            run_root=run_root,
            ndvi_work=run_root / 'ndvi_work',
            ga1_stage=run_root / 'ga1_stage',
            ga0_work=run_root / 'ga0_work',
            legacy_outputs=run_root / 'legacy_outputs',
            outputs_cog=run_root / 'outputs_cog',
            maskvec_work=run_root / 'maskvec_work',
            diagnostics=run_root / 'diagnostics',
            sr_raw_cog=run_root / args.export_sr_raw_cog_dirname,
        )

    def ensure_directories(self, include_sr_raw_cog: bool = False) -> None:
        directories = [
            self.run_root,
            self.ndvi_work,
            self.ga1_stage,
            self.ga0_work,
            self.legacy_outputs,
            self.outputs_cog,
            self.maskvec_work,
            self.diagnostics,
        ]
        if include_sr_raw_cog:
            directories.append(self.sr_raw_cog)

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def _copy_run_artifact(src: Path, dst_dir: Path) -> Path:
    """Copy a file into a run folder (used for optional exports)."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return dst


def _norm_yyyymmdd(iso: str) -> str:
    """Convert YYYY-MM-DD into YYYYMMDD (the pipeline's internal date format)."""
    y, m, d = iso.split('-')
    return f'{y}{m}{d}'


def _extract_epsg(value) -> int | None:
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
    """Given a lon/lat point, return the WGS84 UTM EPSG code for that location."""
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone


def resolve_output_epsg_from_row(row, cli_target_epsg: int) -> int:
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
    """Run the pipeline end-to-end for one tile and one start/end date pair."""
    args = parse_args()
    tile = args.tile.lower().strip()

    sd = _norm_yyyymmdd(args.start_date)
    ed = _norm_yyyymmdd(args.end_date)
    run_tag = args.run_tag or args.run_id or f'{tile}_d{sd}{ed}'

    paths = RunPaths.from_args(args, tile=tile, run_tag=run_tag)
    paths.ensure_directories(include_sr_raw_cog=bool(args.export_sr_raw_cog))

    print(f'[INFO] Local run root: {paths.run_root}')
    print(f"[INFO] Run outputs S3 prefix: {args.s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}")

    run_log_uri = args.run_log_uri or default_run_log_uri(args.s3_bucket, args.s3_prefix)
    run_log_cache_dir = Path(args.work_dir) / tile / 'run_logs'

    run_manifest_uri = args.run_manifest_uri or _default_run_manifest_uri(
        args.s3_bucket, args.s3_prefix, tile, run_tag
    )

    # best-effort: load/append a "running" row early
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
            run_log_df = pd.concat([run_log_df, pd.DataFrame([run_row])], ignore_index=True)
        save_run_log(run_log_df, run_log_uri, run_log_cache_dir)
    except Exception as e:
        print(f"[WARN] Could not write running EDS run-log row: {e}")

    error_message: Optional[str] = None
    final_status = 'success'

    # ------------------------------------------------------------------
    # STEP 1: Pick the best SR start/end scenes.
    # We may not get the exact dates requested: the resolver picks the closest
    # acceptable (low cloud) scene around your requested start/end.
    # ------------------------------------------------------------------
    try:
        sr = resolve_sr_start_end(
            tile=tile,
            tile_shp=args.tile_shp,
            products=args.sr_products,
            cloud_max=float(args.cloud_max),
            start_date=args.start_date,
            end_date=args.end_date,
        )

        sr_start_epsg = resolve_output_epsg_from_row(sr.start_row, args.target_epsg)
        sr_end_epsg = resolve_output_epsg_from_row(sr.end_row, args.target_epsg)

        sr.start_row['target_epsg'] = int(sr_start_epsg)
        sr.end_row['target_epsg'] = int(sr_end_epsg)

        print(f'[INFO] Forced SR start target_epsg: {sr_start_epsg}')
        print(f'[INFO] Forced SR end   target_epsg: {sr_end_epsg}')

        eff_sd = normalise_yyyymmdd(sr.start_row.date)
        eff_ed = normalise_yyyymmdd(sr.end_row.date)

        # update effective window in the run row
        run_row['effective_start_yyyymmdd'] = eff_sd
        run_row['effective_end_yyyymmdd'] = eff_ed

        print(f"[INFO] Effective SR start: {eff_sd} (product={sr.start_row['product']}, cloud={float(sr.start_row['cloud']):.2f})")
        print(f"[INFO] Effective SR end:   {eff_ed} (product={sr.end_row['product']}, cloud={float(sr.end_row['cloud']):.2f})")

        # ------------------------------------------------------------------
        # STEP 2: Build the seasonal NDVI baseline plan.
        # This is the list of NDVI scenes we want to use as the baseline time-series.
        # ------------------------------------------------------------------
        plan = build_seasonal_ndvi_plan(
            tile=tile,
            tile_shp=args.tile_shp,
            products=args.ndvi_products,
            cloud_max=float(args.cloud_max),
            start_yyyymmdd=eff_sd,
            end_yyyymmdd=eff_ed,
            lookback_years=int(args.lookback),
            target_epsg=int(args.target_epsg),
        )

        # Write a run-scoped manifest parquet (baseline plan + SR picks).
        # This is the authoritative manifest for the EDS run.
        try:
            ensure_pyarrow()
            manifest_df = plan.required_rows.copy()
            manifest_df['run_id'] = str(run_id)
            manifest_df['run_tag'] = str(run_tag)
            manifest_df['requested_start_yyyymmdd'] = str(sd)
            manifest_df['requested_end_yyyymmdd'] = str(ed)
            manifest_df['effective_sr_start_yyyymmdd'] = str(eff_sd)
            manifest_df['effective_sr_end_yyyymmdd'] = str(eff_ed)
            manifest_df['seasonal_window_start_mmdd'] = str(plan.window.window_start_mmdd)
            manifest_df['seasonal_window_end_mmdd'] = str(plan.window.window_end_mmdd)
            manifest_df['sr_start_product'] = str(sr.start_row['product'])
            manifest_df['sr_end_product'] = str(sr.end_row['product'])
            manifest_df['sr_start_platform'] = str(sr.start_row['platform'])
            manifest_df['sr_end_platform'] = str(sr.end_row['platform'])
            manifest_df['sr_start_cloud'] = float(sr.start_row['cloud'])
            manifest_df['sr_end_cloud'] = float(sr.end_row['cloud'])

            local_manifest = paths.run_root / 'run_manifest.parquet'
            manifest_df.to_parquet(str(local_manifest), index=False)

            if str(run_manifest_uri).startswith('s3://'):
                b, k = parse_s3_uri(str(run_manifest_uri))
                upload_file_to_s3(str(local_manifest), bucket=b, key=k)
                print(f"[OK] Run manifest uploaded -> s3://{b}/{k}")
            else:
                Path(str(run_manifest_uri)).parent.mkdir(parents=True, exist_ok=True)
                Path(str(local_manifest)).replace(str(run_manifest_uri))
                print(f"[OK] Run manifest written -> {run_manifest_uri}")
        except Exception as e:
            print(f"[WARN] Could not write run manifest parquet: {e}")

        if len(plan.required_rows) > 0:
            plan.required_rows['target_epsg'] = plan.required_rows.apply(
                lambda r: derive_target_epsg_wgs84_utm_from_lonlat(
                    (float(r['lon_min']) + float(r['lon_max'])) / 2.0,
                    (float(r['lat_min']) + float(r['lat_max'])) / 2.0,
                ) if not (args.target_epsg and int(args.target_epsg) > 0)
                else int(args.target_epsg),
                axis=1,
            )

        print('[DEBUG] NDVI plan target_epsg sample:')
        print(plan.required_rows[['date', 'platform', 'target_epsg']].head())
        print(f'[INFO] Seasonal window: {plan.window.window_start_mmdd} -> {plan.window.window_end_mmdd} (months {plan.window.months_hint()})')
        print(f'[INFO] NDVI scenes in seasonal plan: {len(plan.required_rows)}')

        # ------------------------------------------------------------------
        # STEP 3: Ensure required NDVI scenes exist in S3.
        # If a required NDVI scene is missing (or --rebase is set), it is computed.
        # ------------------------------------------------------------------
        ensure_seasonal_ndvi_in_s3(
            plan=plan,
            tile=tile,
            bucket=args.s3_bucket,
            prefix=args.s3_prefix,
            work_dir=paths.ndvi_work,
            cloud_max=float(args.cloud_max),
            resolution=float(args.resolution),
            rebase=bool(args.rebase),
            dry_run=bool(args.dry_run),
            dask_chunk=int(args.chunk),
        )

        required_dates = []
        for r in plan.required_rows.itertuples(index=False):
            required_dates.append((normalise_yyyymmdd(r.date), str(r.platform), int(str(r.target_epsg))))

        if args.dry_run:
            print('[DRY] Skipping ga1 NDVI staging (download).')
            print('[DRY] Skipping ga0 SR build.')
            print('[DRY] Skipping legacy method run + output conversion.')
            final_status = 'dry_run'
            return

        # ------------------------------------------------------------------
        # STEP 4: Download (stage) NDVI scenes locally.
        # The legacy method expects local file paths.
        # ------------------------------------------------------------------
        ga1_dir = stage_ga1_ndvi_locally(
            bucket=args.s3_bucket,
            prefix=args.s3_prefix,
            tile=tile,
            required_dates=required_dates,
            work_dir=paths.ga1_stage,
            dry_run=bool(args.dry_run),
        )

        # ------------------------------------------------------------------
        # STEP 5: Build SR composites (GA0) for start and end.
        # These are 6-band stacks used by the legacy spectral index.
        # ------------------------------------------------------------------
        ga0_start = build_ga0_sr_to_s3(
            tile=tile,
            date=eff_sd,
            platform=str(sr.start_row['platform']),
            product=str(sr.start_row['product']),
            lon_min=float(sr.start_row['lon_min']),
            lat_min=float(sr.start_row['lat_min']),
            lon_max=float(sr.start_row['lon_max']),
            lat_max=float(sr.start_row['lat_max']),
            target_epsg=int(sr.start_row['target_epsg']),
            cloud_max=float(args.cloud_max),
            bucket=args.s3_bucket,
            s3_prefix=args.s3_prefix,
            work_dir=paths.ga0_work,
            resolution=float(args.resolution),
            dask_chunk=int(args.chunk),
            rebase=bool(args.rebase),
            dry_run=bool(args.dry_run),
        )

        ga0_end = build_ga0_sr_to_s3(
            tile=tile,
            date=eff_ed,
            platform=str(sr.end_row['platform']),
            product=str(sr.end_row['product']),
            lon_min=float(sr.end_row['lon_min']),
            lat_min=float(sr.end_row['lat_min']),
            lon_max=float(sr.end_row['lon_max']),
            lat_max=float(sr.end_row['lat_max']),
            target_epsg=int(sr.end_row['target_epsg']),
            cloud_max=float(args.cloud_max),
            bucket=args.s3_bucket,
            s3_prefix=args.s3_prefix,
            work_dir=paths.ga0_work,
            resolution=float(args.resolution),
            dask_chunk=int(args.chunk),
            rebase=bool(args.rebase),
            dry_run=bool(args.dry_run),
        )

        print('ga0_start.local_clr_path:', ga0_start.local_clr_path)
        print('ga0_start exists:', Path(ga0_start.local_clr_path).exists())
        print('ga0_end.local_clr_path:', ga0_end.local_clr_path)
        print('ga0_end exists:', Path(ga0_end.local_clr_path).exists())

        if args.export_sr_raw_cog:
            exported_start = _copy_run_artifact(Path(ga0_start.local_raw_path), paths.sr_raw_cog)
            exported_end = _copy_run_artifact(Path(ga0_end.local_raw_path), paths.sr_raw_cog)
            print(f'[SR-RAW-COG] start -> {exported_start}')
            print(f'[SR-RAW-COG] end   -> {exported_end}')

        print(f'[INFO] Using start db8 masked stack: {ga0_start.local_clr_path}')
        print(f'[INFO] Using end   db8 masked stack: {ga0_end.local_clr_path}')

        # ------------------------------------------------------------------
        # STEP 6: Run the legacy seasonal-window change detection method.
        # This produces:
        # - DLL: change "class" raster (integers like 10, 34..39)
        # - DLJ: interpretation raster (multiple bands including clearing probability)
        # ------------------------------------------------------------------
        outputs = run_legacy_ndvi_window(
            methods_dir=Path(__file__).parent / 'methods',
            scene=tile,
            start_date=eff_sd,
            end_date=eff_ed,
            ga1_glob=str(ga1_dir / '*.tif'),
            start_ga0=str(ga0_start.local_clr_path),
            end_ga0=str(ga0_end.local_clr_path),
            window_start_mmdd=plan.window.window_start_mmdd,
            window_end_mmdd=plan.window.window_end_mmdd,
            lookback=int(args.lookback),
            diagnostics=bool(args.diagnostics),
            verbose=bool(args.verbose),
            vi_tag='vi-ndvi',
            sr_scale=args.legacy_sr_scale,
            no_auto_sr_scale=bool(args.legacy_no_auto_sr_scale),
            baseline_include_nodata=bool(args.legacy_baseline_include_nodata),
            output_dir=paths.legacy_outputs,
            diagnostics_dir=paths.diagnostics,
        )

        print(f"[INFO] Legacy outputs dir: {paths.legacy_outputs}")
        print(f"[INFO] Legacy DLL (change class): {outputs.dll_img}")
        print(f"[INFO] Legacy DLJ (interpretation): {outputs.dlj_img}")

        # COG outputs use platform-prefixed naming so ArcGIS + downstream tooling can
        # relate them back to the GA0 platform (e.g. sl8/sl9).
        target_epsg = int(sr.end_row['target_epsg'])
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
            work_dir=paths.outputs_cog,
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
        # These are the outputs most people use for area summaries and QA.
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
            work_dir=paths.maskvec_work,
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

                src_vectors = paths.maskvec_work / 'vectors'
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
                diagnostics_dir=paths.diagnostics,
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
                paths.maskvec_work / 'vectors' / 'strong',
                paths.maskvec_work / 'vectors' / 'clear',
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
                # Re-open the *home-copied* DLJ products and dump stats so ArcGIS users
                # can trust the artefacts they download.
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


if __name__ == '__main__':
    main()
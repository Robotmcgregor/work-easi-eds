#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import re
import shutil
from pathlib import Path

from tasks.task02_resolve_sr_dates import resolve_sr_start_end
from tasks.task03_ensure_seasonal_ndvi import build_seasonal_ndvi_plan, ensure_seasonal_ndvi_in_s3
from tasks.task04_build_ga0_sr_composite import build_ga0_sr_to_s3
from tasks.task05_run_legacy_method import run_legacy_ndvi_window
from tasks.task06_convert_and_upload_outputs import convert_outputs_to_cog_and_upload
from tasks.task07_stage_ga1_locally import stage_ga1_ndvi_locally
from tasks.task08_masks_and_vectors import make_masks_and_vectors


"""Optimised EDS processing pipeline (NDVI seasonal-window; datacube-native).

This pipeline keeps the existing scientific workflow but writes all local and S3
artifacts into a single run-scoped layout.

Local run layout:
  <work-dir>/<tile>/<run-tag>/
    ndvi_work/
    ga1_stage/
    ga0_work/
    legacy_outputs/
    outputs_cog/
    maskvec_work/
    diagnostics/
    sr_raw_cog/          # optional

S3 layout:
  Scene-date outputs:
    {s3_prefix}/tiles/{tile}/{YYYY}/{YYYYMMDD}/...
  Final run outputs:
    {s3_prefix}/tiles/{tile}/outputs/{run_tag}/...
"""


def parse_args():
    ap = argparse.ArgumentParser('Optimised EDS processing (NDVI seasonal window)')

    ap.add_argument('--tile', required=True, help='e.g. p115r078')
    ap.add_argument('--start-date', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end-date', required=True, help='YYYY-MM-DD')

    ap.add_argument('--s3-bucket', required=True)
    ap.add_argument('--s3-prefix', required=True)

    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--tile-shp', default='/home/jovyan/assets/eds_lsat_grid_min_max.shp')

    ap.add_argument('--cloud-max', type=float, default=40.0)

    ap.add_argument('--sr-products', nargs='+', default=['ga_ls8c_ard_3', 'ga_ls9c_ard_3'])
    ap.add_argument('--ndvi-products', nargs='+', default=['ga_ls8c_ard_3', 'ga_ls9c_ard_3'])

    ap.add_argument('--target-epsg', type=int, default=0)
    ap.add_argument('--resolution', type=float, default=30.0)
    ap.add_argument('--chunk', type=int, default=2048)

    ap.add_argument('--lookback', type=int, default=10)

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

    ap.add_argument('--run-tag', default=None, help='Optional run tag for output folder (default: tile_d<start><end>)')

    ap.add_argument('--strong-threshold', type=int, default=60)
    ap.add_argument('--clear-threshold', type=int, default=80)
    ap.add_argument('--min-area-ha', type=float, default=10.0)

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


@dataclass(frozen=True)
class RunPaths:
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
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return dst


def _norm_yyyymmdd(iso: str) -> str:
    y, m, d = iso.split('-')
    return f'{y}{m}{d}'


def _extract_epsg(value) -> int | None:
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
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone


def resolve_output_epsg_from_row(row, cli_target_epsg: int) -> int:
    """
    Priority:
      1. explicit CLI override
      2. derive WGS84 UTM from bbox centre
      3. fallback to existing EPSG-like fields if bbox missing
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
    args = parse_args()
    tile = args.tile.lower().strip()

    sd = _norm_yyyymmdd(args.start_date)
    ed = _norm_yyyymmdd(args.end_date)
    run_tag = args.run_tag or f'{tile}_d{sd}{ed}'

    paths = RunPaths.from_args(args, tile=tile, run_tag=run_tag)
    paths.ensure_directories(include_sr_raw_cog=bool(args.export_sr_raw_cog))

    print(f'[INFO] Local run root: {paths.run_root}')
    print(f"[INFO] Run outputs S3 prefix: {args.s3_prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}")

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

    eff_sd = str(sr.start_row.date)
    eff_ed = str(sr.end_row.date)

    print(f"[INFO] Effective SR start: {eff_sd} (product={sr.start_row['product']}, cloud={float(sr.start_row['cloud']):.2f})")
    print(f"[INFO] Effective SR end:   {eff_ed} (product={sr.end_row['product']}, cloud={float(sr.end_row['cloud']):.2f})")

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
        required_dates.append((str(r.date), str(r.platform), int(str(r.target_epsg))))

    if args.dry_run:
        print('[DRY] Skipping ga1 NDVI staging (download).')
        print('[DRY] Skipping ga0 SR build.')
        print('[DRY] Skipping legacy method run + output conversion.')
        return

    ga1_dir = stage_ga1_ndvi_locally(
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        tile=tile,
        required_dates=required_dates,
        work_dir=paths.ga1_stage,
        dry_run=bool(args.dry_run),
    )

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
        output_dir=paths.legacy_outputs,
        diagnostics_dir=paths.diagnostics,
    )

    print(f"[INFO] Legacy outputs dir: {paths.legacy_outputs}")
    print(f"[INFO] Legacy DLL (change class): {outputs.dll_img}")
    print(f"[INFO] Legacy DLJ (interpretation): {outputs.dlj_img}")

    # COG outputs use the documented naming convention so downstream tools and users
    # can locate/identify products consistently.
    vi_tag = 'vi-ndvi'
    target_epsg = int(sr.end_row['target_epsg'])
    cog_dll_name = Path(f"lztmre_{tile}_d{eff_sd}{eff_ed}_{vi_tag}_dllmz_e{target_epsg}.tif")
    cog_dlj_name = Path(f"lztmre_{tile}_d{eff_sd}{eff_ed}_{vi_tag}_dljmz_e{target_epsg}.tif")
    print(f"[INFO] COG DLL target name: {cog_dll_name.name}")
    print(f"[INFO] COG DLJ target name: {cog_dlj_name.name}")

    if bool(args.dlj_troubleshoot) or bool(args.stop_after_dlj):
        print("\n[DLJ-DBG] Legacy method outputs produced; dumping stats")
        _print_raster_stats(Path(outputs.dll_img), label="DLL")
        _print_raster_stats(Path(outputs.dlj_img), label="DLJ")
        print("[DLJ-DBG] End stats\n")

        if bool(args.stop_after_dlj):
            raise SystemExit("dlj failure")

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
        print("\n[DLJ-DBG] Converted COG outputs; dumping stats")
        _print_raster_stats(Path(converted.dllmz_cog_local), label="DLL COG")
        _print_raster_stats(Path(converted.dljmz_cog_local), label="DLJ COG")
        print("[DLJ-DBG] End COG stats\n")

    dljmz_cog_local = Path(converted.dljmz_cog_local)

    for u in converted.uploaded:
        print('[OK]', u.s3_uri)

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

        copy_run_to_home(
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

    print('[DONE] Optimised EDS processing complete.')


if __name__ == '__main__':
    main()
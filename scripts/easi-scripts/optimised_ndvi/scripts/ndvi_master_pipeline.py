#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import math
from datetime import date as _date, datetime
import subprocess
import sys
from typing import Optional

import pandas as pd

from tasks.task01_inventory_s3 import inventory_existing_outputs
from tasks.task02_build_scene_manifest import load_or_build_manifest
from tasks.task03_process_scene_ndvi import process_scene_to_s3
from lib.s3_io import s3_key_exists
from lib.run_log import (
    default_run_log_uri,
    finish_run_row,
    last_success_end_date,
    load_run_log,
    new_run_row,
    save_run_log,
)

"""
Example prompt:

python /home/jovyan/work-easi-eds/scripts/easi-scripts/optimised_ndvi/scripts/ndvi_master_pipeline.py \
  --tile p089r084 \
  --s3-bucket dcceew-eds-data \
  --s3-prefix "AROAZ6PFZYT4B4C7MNRHV:robotmcgregor/eds/optimised" \
  --work-dir /home/jovyan/scratch/eds-work-optimised \
  --cloud-max 40 \
  --start-date 2013-01-01 \
  --end-date 2026-22-17 \
  --limit 1
"""
def parse_args():
    ap = argparse.ArgumentParser("Optimised NDVI pipeline (datacube-native, COG->S3)")

    ap.add_argument("--tile", required=True, help="e.g. p089r084")

    ap.add_argument("--s3-bucket", required=True, help="e.g. dcceew-eds-data")
    ap.add_argument("--s3-prefix", required=True, help="e.g. ARO...:robotmcgregor/eds/optimised")

    ap.add_argument("--work-dir", required=True, help="Local work dir (avoid /scratch if not permitted)")

    ap.add_argument("--tile-shp", default="/home/jovyan/assets/eds_lsat_grid_min_max.shp",

                    help="Tile grid shapefile used to derive bbox/geom for tile")

    ap.add_argument(
        "--run-log-uri",
        default=None,
        help=(
            "Master parquet file recording tile runs (S3 or local path). "
            "If omitted, defaults to s3://<bucket>/<prefix>/runs/optimised_ndvi_runs.parquet"
        ),
    )

    ap.add_argument("--start-date", default=None, help="YYYY-MM-DD (optional)")
    ap.add_argument("--end-date", default=None, help="YYYY-MM-DD (optional)")

    ap.add_argument("--products", nargs="+", default=["ga_ls8c_ard_3", "ga_ls9c_ard_3"],
                    help="Datacube product names for LS8/LS9 ARD")

    ap.add_argument("--cloud-max", type=float, default=40.0,
                    help="Max cloud cover percent. Implemented as MIN CLEAR PCT = 100 - cloud_max (using oa_fmask==1)")

    ap.add_argument("--target-epsg", type=int, default=0,
                    help="Override output EPSG (e.g. 28352). If 0, derive GDA94 MGA zone EPSG:283xx from tile centroid.")

    ap.add_argument("--resolution", type=float, default=30.0, help="Output pixel size in metres (default 30)")

    ap.add_argument("--rebase", action="store_true",
                    help="Overwrite existing outputs (NDVI and ffmask). Default: resume/skip if exists.")

    ap.add_argument("--limit", type=int, default=0, help="Process only first N scenes (0 = no limit)")
    ap.add_argument("--dry-run", action="store_true")

    ap.add_argument(
        "--lookback",
        type=int,
        default=10,
        help=(
            "When chaining to EDS (--run-eds-after): years of baseline lookback (default 10). "
            "Ignored by the NDVI stage."
        ),
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Verbose logging. When chaining to EDS (--run-eds-after), forwards --verbose to EDS."
        ),
    )
    ap.add_argument(
        "--copy-to-home",
        action="store_true",
        help=(
            "When chaining to EDS (--run-eds-after), forwards --copy-to-home to EDS (copies outputs under /home/jovyan)."
        ),
    )

    # Dask chunking (keeps it cheap)
    ap.add_argument("--chunk", type=int, default=2048, help="Dask chunk size for x/y (default 2048)")

    ap.add_argument(
        "--run-eds-after",
        action="store_true",
        help=(
            "After NDVI completes, run the optimised EDS pipeline "
            "(scripts/easi-scripts/optimised_processing/scripts/eds_master_pipeline_optimised.py) "
            "for the same tile/window."
        ),
    )
    ap.add_argument(
        "--eds-script",
        default=None,
        help=(
            "Optional path to the EDS entrypoint script to run when --run-eds-after is set. "
            "If omitted, uses the repo default under scripts/easi-scripts/optimised_processing/scripts/."
        ),
    )

    return ap.parse_args()

import re


def normalise_yyyymmdd(value) -> str:
    """Return an 8-digit YYYYMMDD string from common date representations.

    Handles:
    - int/np.int64 like 20220101
    - datetime/date objects
    - strings like "20220101", "2022-01-01", "2022-01-01 00:00:00"
    """
    if value is None:
        raise ValueError("date is None")

    if isinstance(value, (datetime, _date)):
        return value.strftime("%Y%m%d")

    # ints (including numpy ints) -> zero-pad to 8 digits
    if isinstance(value, int):
        return f"{value:08d}"

    # numpy scalar ints aren't instances of int on some versions
    try:
        if hasattr(value, "dtype") and str(getattr(value, "dtype", "")).startswith("int"):
            return f"{int(value):08d}"
    except Exception:
        pass

    s = str(value).strip()
    if re.fullmatch(r"\d{8}", s):
        return s

    # common ISO-like forms
    m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})", s)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"

    # last resort: pull first 8 digits if present
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return digits[:8]

    raise ValueError(f"Could not normalise date to YYYYMMDD from: {value!r}")


def _normalise_cli_date(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    return normalise_yyyymmdd(d)


def _select_effective_window(
    *,
    tile: str,
    manifest_df: pd.DataFrame,
    cli_start: Optional[str],
    cli_end: Optional[str],
    run_log_df: pd.DataFrame,
) -> tuple[str, str]:
    """Choose (start_yyyymmdd, end_yyyymmdd) for this run.

    Rules:
    - If cli_start provided, use it.
      Else: resume from the next available scene date after the last successful run end date.
    - If cli_end provided, use it.
      Else: use the latest available scene date in the manifest.
    """
    if manifest_df.empty:
        raise RuntimeError("Manifest is empty; cannot select window")

    if "yyyymmdd" not in manifest_df.columns:
        raise RuntimeError("Manifest missing computed yyyymmdd column")

    available = sorted({str(v)[:8] for v in manifest_df["yyyymmdd"].dropna().tolist()})
    if not available:
        raise RuntimeError("No valid dates in manifest to select window")

    eff_end = _normalise_cli_date(cli_end) or available[-1]

    if cli_start:
        eff_start = _normalise_cli_date(cli_start)
        if eff_start is None:
            raise RuntimeError(f"Could not parse --start-date: {cli_start!r}")
        if eff_end < eff_start:
            raise RuntimeError(f"Invalid window: end({eff_end}) < start({eff_start})")
        return eff_start, eff_end

    last_end = last_success_end_date(run_log_df, tile)
    if not last_end:
        eff_start = available[0]
        if eff_end < eff_start:
            raise RuntimeError(f"Invalid window: end({eff_end}) < start({eff_start})")
        return eff_start, eff_end

    # next available date strictly after last_end
    for d in available:
        if d > last_end:
            if eff_end < d:
                raise RuntimeError(f"Invalid window: end({eff_end}) < start({d})")
            return d, eff_end

    # Up to date; caller can decide to exit.
    return eff_end, eff_end


def _filter_manifest_by_window(df: pd.DataFrame, start_yyyymmdd: str, end_yyyymmdd: str) -> pd.DataFrame:
    out = df.copy()
    out = out[(out["yyyymmdd"] >= start_yyyymmdd) & (out["yyyymmdd"] <= end_yyyymmdd)]
    out = out.sort_values(["yyyymmdd", "product"]).reset_index(drop=True)
    return out


def _yyyymmdd_to_iso(d: str) -> str:
    d = str(d)
    if len(d) != 8 or not d.isdigit():
        raise ValueError(f"Expected YYYYMMDD, got: {d!r}")
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def _default_eds_script_path() -> Path:
    # ndvi_master_pipeline.py is under: scripts/easi-scripts/optimised_ndvi/scripts/
    easi_scripts_dir = Path(__file__).resolve().parents[3]
    return easi_scripts_dir / "optimised_processing" / "scripts" / "eds_master_pipeline_optimised.py"


def _run_eds_pipeline(
    *,
    args,
    tile: str,
    eff_start_yyyymmdd: str,
    eff_end_yyyymmdd: str,
    base_work_dir: Path,
) -> None:
    eds_script = Path(args.eds_script) if args.eds_script else _default_eds_script_path()
    if not eds_script.exists():
        raise FileNotFoundError(
            f"EDS script not found at {eds_script}. "
            "Pass --eds-script to override."
        )

    start_iso = _yyyymmdd_to_iso(eff_start_yyyymmdd)
    end_iso = _yyyymmdd_to_iso(eff_end_yyyymmdd)

    cmd = [
        sys.executable,
        str(eds_script),
        "--tile",
        tile,
        "--start-date",
        start_iso,
        "--end-date",
        end_iso,
        "--s3-bucket",
        args.s3_bucket,
        "--s3-prefix",
        args.s3_prefix,
        "--work-dir",
        str(base_work_dir),
        "--tile-shp",
        args.tile_shp,
        "--cloud-max",
        str(args.cloud_max),
        "--ndvi-products",
        *list(args.products),
        "--target-epsg",
        str(args.target_epsg),
        "--resolution",
        str(args.resolution),
        "--chunk",
        str(args.chunk),
        "--lookback",
        str(int(args.lookback)),
    ]

    if args.rebase:
        cmd.append("--rebase")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("--verbose")
    if args.copy_to_home:
        cmd.append("--copy-to-home")

    print("[INFO] Running EDS pipeline after NDVI:")
    print("       " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def _extract_epsg(value) -> int | None:
    """
    Try to extract an EPSG code from values like:
      32656
      "32656"
      "EPSG:32656"
      "epsg:32656"
    Returns None if not found.
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

    m = re.search(r"EPSG[:= ]*(\d+)", s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))

    m = re.search(r"\b(\d{4,6})\b", s)
    if m:
        return int(m.group(1))

    return None



def derive_target_epsg_wgs84_utm_from_lonlat(lon: float, lat: float) -> int:
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    if lat >= 0:
        return 32600 + zone
    return 32700 + zone

def resolve_output_epsg(row, cli_target_epsg: int) -> int:
    if cli_target_epsg and int(cli_target_epsg) > 0:
        return int(cli_target_epsg)

    lon_min = getattr(row, "lon_min", None)
    lon_max = getattr(row, "lon_max", None)
    lat_min = getattr(row, "lat_min", None)
    lat_max = getattr(row, "lat_max", None)

    if None not in (lon_min, lon_max, lat_min, lat_max):
        centre_lon = (float(lon_min) + float(lon_max)) / 2.0
        centre_lat = (float(lat_min) + float(lat_max)) / 2.0
        return derive_target_epsg_wgs84_utm_from_lonlat(centre_lon, centre_lat)

    raise ValueError(
        f"Could not resolve output EPSG for row date={getattr(row, 'date', 'unknown')} "
        f"product={getattr(row, 'product', 'unknown')}"
    )

def main():
    args = parse_args()
    tile = args.tile.lower()

    base_work_dir = Path(args.work_dir)
    work_dir = base_work_dir / tile
    work_dir.mkdir(parents=True, exist_ok=True)

    run_log_uri = args.run_log_uri or default_run_log_uri(args.s3_bucket, args.s3_prefix)
    run_log_cache_dir = work_dir / "run_logs"

    # 1) inventory existing NDVI outputs (so resume is fast)
    existing = inventory_existing_outputs(
        bucket=args.s3_bucket,
        prefix=args.s3_prefix,
        tile=tile,
    )
    print(f"[INFO] Existing NDVI outputs found in S3: {len(existing)}")
    # print("target epsg: ", target_epsg)
    # import sys
    # sys.exit("brek run test target manifest...")

    # 2) build manifest (in-memory) from datacube
    manifest_df = load_or_build_manifest(
        tile=tile,
        tile_shp=args.tile_shp,
        products=args.products,
        cloud_max=args.cloud_max,
        # Load full manifest for auto-window logic; we apply date filtering after.
        start_date=None,
        end_date=None,
        target_epsg=args.target_epsg,
    )

    # Final output EPSG must be resolved AFTER manifest build.
    if args.target_epsg and int(args.target_epsg) > 0:
        manifest_df["target_epsg"] = int(args.target_epsg)
    else:
        def _resolve_row_epsg_series(r):
            centre_lon = (float(r["lon_min"]) + float(r["lon_max"])) / 2.0
            centre_lat = (float(r["lat_min"]) + float(r["lat_max"])) / 2.0
            return derive_target_epsg_wgs84_utm_from_lonlat(centre_lon, centre_lat)

        manifest_df["target_epsg"] = manifest_df.apply(_resolve_row_epsg_series, axis=1)

    if args.verbose:
        print("[DEBUG] manifest cols:", list(manifest_df.columns))
        print(manifest_df.head(1).to_dict("records"))

    # Compute normalised date string column used for window selection/filtering.
    manifest_df = manifest_df.copy()
    manifest_df["yyyymmdd"] = manifest_df["date"].apply(normalise_yyyymmdd)

    # Load run log (best-effort). If missing, we treat as first run.
    try:
        run_log_df = load_run_log(run_log_uri, run_log_cache_dir)
    except Exception as e:
        print(f"[WARN] Could not load run log from {run_log_uri!r}: {e}")
        run_log_df = pd.DataFrame()

    eff_start, eff_end = _select_effective_window(
        tile=tile,
        manifest_df=manifest_df,
        cli_start=args.start_date,
        cli_end=args.end_date,
        run_log_df=run_log_df,
    )

    # If auto-resume and already up to date, exit early (unless chaining to EDS).
    if (not args.start_date) and (not args.end_date) and (not args.run_eds_after):
        last_end = last_success_end_date(run_log_df, tile)
        if last_end and eff_start == eff_end and eff_end <= last_end:
            print(f"[DONE] Up to date: last_success_end={last_end}, latest_available={eff_end}")
            return

    print(f"[INFO] Effective window: {eff_start} -> {eff_end}")

    manifest_df = _filter_manifest_by_window(manifest_df, eff_start, eff_end)

    print(f"[INFO] Manifest scenes in window: {len(manifest_df)}")

    # import sys
    # sys.exit("Forced stop after manifest")

    if args.limit and args.limit > 0:
        manifest_df = manifest_df.head(args.limit).reset_index(drop=True)
        print(f"[INFO] Limit enabled: {len(manifest_df)} scenes")

    # 3) run logging + process each scene
    run_row = new_run_row(
        tile=tile,
        start_yyyymmdd=eff_start,
        end_yyyymmdd=eff_end,
        dry_run=bool(args.dry_run),
        rebase=bool(args.rebase),
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
    )
    run_id = run_row["run_id"]

    scenes_total = int(len(manifest_df))
    scenes_processed = 0
    scenes_skipped_existing = 0
    scenes_failed = 0

    # Append "running" row immediately (best-effort)
    try:
        if run_log_df is None or run_log_df.empty:
            run_log_df = pd.DataFrame([run_row])
        else:
            run_log_df = pd.concat([run_log_df, pd.DataFrame([run_row])], ignore_index=True)
        save_run_log(run_log_df, run_log_uri, run_log_cache_dir)
    except Exception as e:
        print(f"[WARN] Could not write running run-log row: {e}")

    error_message: Optional[str] = None
    final_status = "success"

    try:
        for row in manifest_df.itertuples(index=False):
            yyyymmdd = normalise_yyyymmdd(row.date)
            product = str(row.product)
            platform = str(row.platform)
            target_epsg = resolve_output_epsg(row, args.target_epsg)

            # output keys
            yyyymm = yyyymmdd[:6]
            out_dir = f"{args.s3_prefix}/tiles/{tile}/{yyyymmdd[:4]}/{yyyymm}"
            ndvi_key = f"{out_dir}/sl{platform[1:]}olre_{tile}_{yyyymmdd}_ga1-clr_e{target_epsg}.tif"
            fmk_key = f"{out_dir}/sl{platform[1:]}olre_{tile}_{yyyymmdd}_ga3_e{target_epsg}.tif"

            if not args.rebase:
                if s3_key_exists(args.s3_bucket, ndvi_key) and s3_key_exists(args.s3_bucket, fmk_key):
                    print(f"[SKIP] Exists: s3://{args.s3_bucket}/{ndvi_key}")
                    scenes_skipped_existing += 1
                    continue

            if args.dry_run:
                print(f"[DRY] Would process {tile} {platform} {yyyymmdd} product={product} -> {ndvi_key}")
                continue

            process_scene_to_s3(
                tile=tile,
                date=yyyymmdd,
                platform=platform,
                product=product,
                lon_min=float(row.lon_min),
                lat_min=float(row.lat_min),
                lon_max=float(row.lon_max),
                lat_max=float(row.lat_max),
                target_epsg=int(row.target_epsg),
                cloud_max=float(args.cloud_max),
                bucket=args.s3_bucket,
                ndvi_key=ndvi_key,
                ffmask_key=fmk_key,
                work_dir=work_dir,
                resolution=float(args.resolution),
                rebase=bool(args.rebase),
            )
            scenes_processed += 1

    except Exception as e:
        final_status = "failed"
        scenes_failed += 1
        error_message = str(e)
        raise

    finally:
        # Update the run row in the log (best-effort)
        try:
            finished_row = finish_run_row(
                run_row,
                status=("dry_run" if args.dry_run else final_status),
                scenes_total=scenes_total,
                scenes_processed=scenes_processed,
                scenes_skipped_existing=scenes_skipped_existing,
                scenes_failed=scenes_failed,
                error_message=error_message,
            )

            if run_log_df is None or run_log_df.empty:
                run_log_df = pd.DataFrame([finished_row])
            else:
                # Replace the row with matching run_id.
                m = run_log_df["run_id"].astype(str) == str(run_id)
                if m.any():
                    for k, v in finished_row.items():
                        run_log_df.loc[m, k] = v
                else:
                    run_log_df = pd.concat([run_log_df, pd.DataFrame([finished_row])], ignore_index=True)

            save_run_log(run_log_df, run_log_uri, run_log_cache_dir)
        except Exception as e:
            print(f"[WARN] Could not finalize run log: {e}")


    print("[DONE] NDVI pipeline finished.")

    if args.run_eds_after:
        if eff_start == eff_end:
            print(f"[INFO] Skipping EDS: window is a single date ({eff_start}).")
            return
        _run_eds_pipeline(
            args=args,
            tile=tile,
            eff_start_yyyymmdd=eff_start,
            eff_end_yyyymmdd=eff_end,
            base_work_dir=base_work_dir,
        )


if __name__ == "__main__":
    main()

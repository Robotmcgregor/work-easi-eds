#!/usr/bin/env python
"""
Run the original legacy change detection script using a seasonal window and data available
in the compat filesystem, without modifying legacy methodology.

What this does:
- Select start/end dates for a given scene and year within a seasonal window (MMDD range).
- Optionally ensure SR composites (and FMASK) are downloaded for those dates from S3/DEA.
- Build db8 stacks for those two dates using slats_compat_builder.
- Assemble a seasonal baseline timeseries date list (one date per year within the window, up to lookback years)
  from available dc4 files and pass it to the legacy script via --timeseriesdates.
- Invoke the legacy script edsadhoc_timeserieschange_d.py with the start/end db8 and the timeseries dates list.

Inputs:
  --scene pXXXrYYY
  --year YYYY (e.g., 2025)
  --window-start MMDD (e.g., 0701)
  --window-end   MMDD (e.g., 1031)
  --lookback N (default 10)
  --ensure-sr (optional) ensure SR composites for the two target dates using ensure_sr_from_s3_or_ga.py
  --sr-dest D:\\data\\lsat (optional, where ensure_sr downloads SR)

Assumptions:
- dc4 files are already present under data/compat/files/<scene>/ with names like lztmre_<scene>_<YYYYMMDD>_dc4mz.img
- rsc.utils.masks shim provides masks (empty masks acceptable) and metadb shim is configured
- You have conda env and GDAL installed (same as legacy script requirements)
"""
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
from typing import List, Tuple, Dict

import sys
THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rsc.utils.metadb import stdProjFilename


def parse_date_from_name(p: str) -> str:
    base = os.path.basename(p)
    import re
    m = re.search(r"(19|20)\d{6}", base)
    if not m:
        raise ValueError(f"No YYYYMMDD in {base}")
    return m.group(0)


def in_window(yyyymmdd: str, start_mmdd: str, end_mmdd: str) -> bool:
    m = int(yyyymmdd[4:6]); d = int(yyyymmdd[6:8])
    sm = int(start_mmdd[:2]); sd = int(start_mmdd[2:])
    em = int(end_mmdd[:2]); ed = int(end_mmdd[2:])
    if (sm, sd) <= (em, ed):
        return (m, d) >= (sm, sd) and (m, d) <= (em, ed)
    else:
        return (m, d) >= (sm, sd) or (m, d) <= (em, ed)


def scene_to_tile(scene: str) -> str:
    # Convert p089r080 -> 089_080
    s = scene.lower().strip()
    if not (s.startswith('p') and 'r' in s):
        raise ValueError("scene must look like pXXXrYYY")
    pp = s[1:4]; rr = s[5:8]
    return f"{pp}_{rr}"


def find_dc4_for_scene(scene: str) -> List[str]:
    base = Path(stdProjFilename(f"lztmre_{scene}_00000000_dc4mz.img")).parent
    hits = sorted(glob.glob(str(base / f"lztmre_{scene}_*_dc4mz.img")))
    return hits


def pick_start_end(dc4_files: List[str], year: int, start_mmdd: str, end_mmdd: str) -> Tuple[str, str]:
    # Choose earliest and latest dc4 date within window and year
    candidates = []
    for f in dc4_files:
        d = parse_date_from_name(f)
        if int(d[:4]) != year:
            continue
        if in_window(d, start_mmdd, end_mmdd):
            candidates.append(d)
    if not candidates:
        raise SystemExit(f"No dc4 images found in {year} within window {start_mmdd}-{end_mmdd}")
    candidates = sorted(candidates)
    return candidates[0], candidates[-1]


def baseline_dates(dc4_files: List[str], end_year: int, start_cutoff: str, start_mmdd: str, end_mmdd: str, lookback: int) -> List[str]:
    # For each year in [end_year-lookback+1, end_year], choose the date nearest to end_mmdd within the window, and <= start_cutoff
    # using available dc4 dates only.
    from collections import defaultdict
    by_year: Dict[int, List[str]] = defaultdict(list)
    for f in dc4_files:
        d = parse_date_from_name(f)
        y = int(d[:4])
        if y < end_year - lookback + 1 or y > end_year:
            continue
        if d > start_cutoff:
            continue
        if in_window(d, start_mmdd, end_mmdd):
            by_year[y].append(d)
    # pick nearest in MMDD to end_mmdd
    tm = int(end_mmdd[:2]); td = int(end_mmdd[2:])
    def md_dist(d: str) -> int:
        m = int(d[4:6]); dd = int(d[6:8])
        return abs((m - tm) * 31 + (dd - td))
    chosen: List[str] = []
    for y in sorted(by_year.keys()):
        lst = by_year[y]
        if lst:
            chosen.append(sorted(lst, key=md_dist)[0])
    return sorted(chosen)


def build_db8_for_dates(scene: str, sr_root: Path, start_date: str, end_date: str) -> Tuple[str, str]:
    # Locate directories for dates and call slats_compat_builder with --sr-dir and --sr-date
    # Directories are expected like D:\data\lsat\089_080\YYYY\YYYYMM
    tile = scene_to_tile(scene)
    sd_dir = sr_root / tile / start_date[:4] / start_date[:6]
    ed_dir = sr_root / tile / end_date[:4] / end_date[:6]
    if not sd_dir.exists():
        raise SystemExit(f"SR directory missing for start date: {sd_dir}. Run with --ensure-sr to fetch it.")
    if not ed_dir.exists():
        raise SystemExit(f"SR directory missing for end date: {ed_dir}. Run with --ensure-sr to fetch it.")
    # Call builder as a module
    import subprocess, sys as _sys
    cmd = [
        _sys.executable, str(THIS_DIR / 'slats_compat_builder.py'),
        '--tile', scene,
        '--sr-date', start_date, '--sr-dir', str(sd_dir),
        '--sr-date', end_date,   '--sr-dir', str(ed_dir),
    ]
    # Allow partial builds: if fewer than 4 per-band files exist, attempt composite discovery inside nested date folders
    # This fallback is handled by slats_compat_builder already; here just log existing contents for debugging.
    print('[DEBUG] Start SR dir contents sample:', list(sd_dir.glob('*.tif'))[:6])
    print('[DEBUG] End SR dir contents sample:', list(ed_dir.glob('*.tif'))[:6])
    print('Building db8 with:', ' '.join(cmd))
    subprocess.check_call(cmd)
    # Return expected output paths
    s_db8 = stdProjFilename(f"lztmre_{scene}_{start_date}_db8mz.img")
    e_db8 = stdProjFilename(f"lztmre_{scene}_{end_date}_db8mz.img")
    return s_db8, e_db8


def maybe_ensure_sr(scene: str, date: str, sr_root: Path, ensure: bool) -> None:
    if not ensure:
        return
    tile = scene_to_tile(scene)
    # Run ensure_sr_from_s3_or_ga.py
    import subprocess, sys as _sys
    cmd = [
        _sys.executable, str(THIS_DIR / 'ensure_sr_from_s3_or_ga.py'),
        '--tile', tile, '--date', date, '--dest', str(sr_root),
    ]
    print('Ensuring SR+FM:', ' '.join(cmd))
    subprocess.call(cmd)


def run_legacy(start_db8: str, end_db8: str, dates_list: List[str], omit_cloud_masks: bool=False) -> Tuple[str, str]:
    import subprocess, sys as _sys
    cmd = [
        _sys.executable, str(THIS_DIR / 'edsadhoc_timeserieschange_d.py'),
        '--startdateimage', start_db8,
        '--enddateimage', end_db8,
        '--timeseriesdates', ','.join(dates_list),
    ]
    if omit_cloud_masks:
        cmd.append('--omitcloudmasks')
    print('Running legacy change detection:', ' '.join(cmd))
    subprocess.check_call(cmd)
    # Output filenames are determined by legacy script; infer from start_db8 path
    import re
    m = re.search(r"lztmre_(p\d{3}r\d{3})_(\d{8})_db8mz\.img", os.path.basename(start_db8), re.IGNORECASE)
    scene = m.group(1)
    start = m.group(2); end = parse_date_from_name(end_db8)
    era = f"d{start}{end}"
    change = stdProjFilename(f"lztmre_{scene}_{era}_dllmz.img")
    interp = stdProjFilename(f"lztmre_{scene}_{era}_dljmz.img")
    return change, interp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Seasonal-window runner for legacy change detection")
    ap.add_argument('--scene', required=True)
    ap.add_argument('--year', type=int, required=True)
    ap.add_argument('--window-start', required=True, help='MMDD e.g., 0701')
    ap.add_argument('--window-end', required=True, help='MMDD e.g., 1031')
    ap.add_argument('--lookback', type=int, default=10)
    ap.add_argument('--ensure-sr', action='store_true', help='Fetch SR+FMASK for start/end dates before building db8')
    ap.add_argument('--sr-dest', default=r'D:\data\lsat')
    ap.add_argument('--omit-cloud-masks', action='store_true')
    args = ap.parse_args(argv)

    # Discover dc4
    dc4_files = find_dc4_for_scene(args.scene)
    if not dc4_files:
        raise SystemExit(f"No dc4 files found for scene {args.scene}")

    start_date, end_date = pick_start_end(dc4_files, args.year, args.window_start, args.window_end)
    print(f"Window start/end dates: {start_date} -> {end_date}")

    # Build seasonal baseline dates list
    base_dates = baseline_dates(dc4_files, args.year, start_date, args.window_start, args.window_end, args.lookback)
    if len(base_dates) < 2:
        print("[WARN] Baseline has <2 dates; legacy will still run but trend robustness is low.")
    print("Baseline dates:", ','.join(base_dates))

    # Ensure SR composites and build db8
    sr_root = Path(args.sr_dest)
    for d in [start_date, end_date]:
        maybe_ensure_sr(args.scene, d, sr_root, ensure=args.ensure_sr)
    s_db8, e_db8 = build_db8_for_dates(args.scene, sr_root, start_date, end_date)
    print("Start db8:", s_db8)
    print("End   db8:", e_db8)

    # Run legacy
    change, interp = run_legacy(s_db8, e_db8, base_dates, omit_cloud_masks=args.omit_cloud_masks)
    print("Outputs:", change)
    print("         ", interp)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

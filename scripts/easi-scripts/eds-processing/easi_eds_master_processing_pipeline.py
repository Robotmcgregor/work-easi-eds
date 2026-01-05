#!/usr/bin/env python
"""
Master processing pipeline (EDS) to execute the legacy SLATS-style workflow AFTER data acquisition.

This orchestrates the end-to-end creation of change rasters and polygons using already-downloaded
SR (surface reflectance) and FC (fractional cover) inputs, mirroring the SLATS legacy method while
being self-contained and environment-portable.

Replaces earlier prototype ads_master_processing_pipeline.py (typo). This version uses the proper
interface to slats_compat_builder.py (expects --sr-dir and optional --sr-date) and exposes explicit
arguments for SR start/end directories.

Steps chained (see docs/EDS_MASTER_PIPELINES.md for a broader overview):
    1. Build compat (db8 + dc4) -> slats_compat_builder.py
    2. Legacy seasonal change method -> easi_eds_legacy_method_window.py
    3. Style dll/dlj -> easi_style_dll_dlj.py
    4. Polygonize merged thresholds -> easi_polygonize_merged_thresholds.py
    5. Post-process (dissolve + skinny filter) -> vector_postprocess.py
    6. FC coverage + masks -> fc_coverage_extent.py
    7. Clip cleaned polygons (strict + ratio masks) -> clip_vectors.py

Key additions:
    - --sr-dir-start / --sr-dir-end: required explicit SR band directories or composite file paths.
    - --fc-only-clr / --fc-prefer-clr: propagate to compat builder for FC selection logic.
    - --span-years: sets legacy lookback (capped by --lookback-cap).
    - --fc-glob: optional override for FC input pattern (defaults to *fc3ms*.tif or *fcm*.tif recursive under fc-root).
    - --python-exe: enforce running subprocesses in a GDAL-enabled interpreter (recommended on Windows).
    - --sr-only-clr: restrict SR composites to *_nbart6m*_clr.tif (or *_srb?_clr.tif) where available.

Usage example (PowerShell):
    python scripts/eds_master_processing_pipeline.py `
            --tile 094_076 `
            --start-date 20230720 `
            --end-date 20240831 `
            --span-years 2 `
            --sr-dir-start D:\data\lsat\094\076\20230720 `
            --sr-dir-end   D:\data\lsat\094\076\20240831 `
            --sr-root D:\data\lsat `
            --fc-root D:\data\lsat `
            --out-root data\compat\files `
            --season-window 0701 1031 `
            --fc-only-clr `
            --ratio-presence 0.95 0.90 `
            --min-ha 1 `
            --skinny-pixels 3

Add --dry-run to inspect the planned subprocess commands.

## Run on EASI
# 1) Confirm system python has GDAL
/usr/bin/python3 -c "from osgeo import gdal; import sys; print('OK:', sys.executable, 'GDAL', gdal.VersionInfo())"

# 2) Confirm SR composites exist for your dates (adjust tile if needed)
SCENE="p089r078"
ls -lh /home/jovyan/scratch/eds/tiles/${SCENE}/sr/2023/202307/*20230720*.tif
ls -lh /home/jovyan/scratch/eds/tiles/${SCENE}/sr/2024/202408/*20240831*.tif

# 3) Confirm FC exists
ls -lh /home/jovyan/scratch/eds/tiles/${SCENE}/fc | head


GDALPY="/usr/bin/python3"
PIPE="/home/jovyan/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py"
OUT="/home/jovyan/work-easi-eds/data/compat/files"

$GDALPY "$PIPE" \
  --tile 089_078 \
  --start-date 20230720 \
  --end-date 20240831 \
  --sr-root /home/jovyan/scratch/eds/tiles \
  --fc-root /home/jovyan/scratch/eds/tiles \
  --out-root "$OUT" \
  --timeseries-source fc \
  --fc-only-clr \
  --python-exe "$GDALPY"


/usr/bin/python3 /home/jovyan/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py \
  --tile 089_078 \
  --start-date 20230720 \
  --end-date 20240831 \
  --sr-root /home/jovyan/scratch/eds/tiles \
  --fc-root /home/jovyan/scratch/eds/tiles \
  --out-root /home/jovyan/work-easi-eds/data/compat/files \
  --timeseries-source fc \
  --fc-only-clr \
  --python-exe /usr/bin/python3 \
  --force-compat

/usr/bin/python3 /home/jovyan/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py \
  --tile 089_084 \
  --start-date 20230728 \
  --end-date 20240831 \
  --sr-root /home/jovyan/scratch/eds/tiles \
  --fc-root /home/jovyan/scratch/eds/tiles \
  --timeseries-source fc \
  --force-clr \
  --python-exe /usr/bin/python3

    ...

#Latest - nothing is working though.....
/usr/bin/python3 /home/jovyan/work-easi-eds/scripts/easi-scripts/eds-processing/easi_eds_master_processing_pipeline.py \
  --tile 089_084 \
  --start-date 20230125 \
  --end-date 20231024 \
  --sr-root /home/jovyan/scratch/eds/tiles \
  --fc-root /home/jovyan/scratch/eds/tiles \
  --timeseries-source fc \
  --force-clr \
  --force-compat \
  --python-exe /usr/bin/python3

"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple
import glob
import re
from datetime import datetime
import sys
import glob
import os
import re
from datetime import datetime
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_THRESHOLDS = [34, 35, 36, 37, 38, 39]


def run_cmd(cmd: List[str], dry_run: bool, step: str, results: dict) -> None:
    """
    Run an external command-line program as one "step" in the processing pipeline.

    This is a small helper that:
      - prints which step is running and the exact command,
      - optionally *does not actually run it* if dry_run=True (for testing),
      - records the outcome (success/failure, time taken, last bit of output)
        into a 'results' dictionary so we can save it as JSON later.

    Typical use:
        run_cmd(
            ["python", "eds_legacy_change.py", "--scene", "p104r072", ...],
            dry_run=False,
            step="legacy_change_detection",
            results=run_log,
        )

    Where:
        cmd      = the command to run, split into a list (program + arguments)
        dry_run  = if True, just show what would be run but don’t execute it
        step     = short name for this stage in the pipeline (for logging)
        results  = shared dictionary where each step appends its summary
    """

    # Print a friendly header so it’s clear which part of the pipeline we’re in.
    print(f"\n[STEP] {step}")
    print("Command:", " ".join(cmd))

    # If we're in "dry run" mode, we only show the command and skip execution.
    # This is useful when testing the pipeline or showing someone what would happen.
    if dry_run:
        print("(dry-run) Skipped execution")
        return

    # Record the start time so we can measure how long the command takes.
    t0 = time.time()

    # Actually run the command as a subprocess:
    #   - capture_output=True: we keep whatever it prints (stdout + stderr)
    #   - text=True: decode output as text instead of raw bytes
    # proc = subprocess.run(cmd, capture_output=True, text=True)
    proc = subprocess.run(cmd, text=True)


    # Calculate how many seconds the command took.
    dt = time.time() - t0

    # Make sure there is a 'steps' list in the results dict, then append a summary
    # of this step. This structure is easy to convert to JSON later.
    results.setdefault("steps", []).append(
        {
            "step": step,  # name of this pipeline step
            "command": cmd,  # full command we ran
            "returncode": proc.returncode,  # 0 means success, anything else = error
            "duration_sec": dt,  # how long it took, in seconds
            # We only keep the *last* 4000 characters of stdout/stderr.
            # This keeps the log manageable but still shows recent messages.
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],

        }
    )

    # If the command failed (non-zero return code), show all its output
    # on the screen and stop the whole pipeline with a clear error.
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
        raise SystemExit(f"Step failed: {step}")


    # Otherwise, report that it finished successfully and how long it took.
    else:
        print(f"Completed in {dt:.1f}s")


# def derive_scene(tile: str) -> str:
#     """Convert a PPP_RRR tile (e.g., 094_076) to scene code (e.g., p094r076)."""
#     if '_' not in tile or len(tile) != 7:
#         raise ValueError("Tile must be PPP_RRR e.g. 094_076")
#     p, r = tile.split('_')
#     return f"p{p}r{r}"
def derive_scene(tile: str) -> str:
    """
    Turn a tile ID written as 'PPP_RRR' into a scene code 'pPPPrRRR'.

    Example:
        "094_076"  ->  "p094r076"

    Why?
        - Some parts of the pipeline refer to tiles as PPP_RRR
          (PATH_ROW style, with an underscore).
        - Other tools expect the "scene code" format: pPPPrRRR
          (lowercase 'p' and 'r', no underscore).
        - This helper keeps that conversion in one place so it’s consistent.
    """

    # Basic safety check:
    #   - there must be an underscore
    #   - the total length must be exactly 7 characters, e.g. "094_076"
    if "_" not in tile or len(tile) != 7:
        raise ValueError("Tile must be PPP_RRR e.g. '094_076'")

    # Split "PPP_RRR" into:
    #   p = "PPP" (path)
    #   r = "RRR" (row)
    p, r = tile.split("_")

    # Build and return the scene code "pPPPrRRR".
    return f"p{p}r{r}"



DATE_RX_YYYYMMDD = re.compile(r"(19|20)\d{2}[01]\d[0-3]\d")
DATE_RX_YYYY_MM_DD = re.compile(r"(19|20)\d{2}-[01]\d-[0-3]\d")

def extract_date(path: str) -> str | None:
    """Extract date as YYYYMMDD from basename; supports YYYYMMDD and YYYY-MM-DD."""
    name = os.path.basename(path)
    m = DATE_RX_YYYYMMDD.search(name)
    if m:
        return m.group(0)
    m = DATE_RX_YYYY_MM_DD.search(name)
    if m:
        return m.group(0).replace("-", "")
    return None

def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def build_patterns(
    base_root: str,
    scene: str,
    tile_arg: str,
    subdir: str,
    family_patterns: list[str],
) -> list[str]:
    """
    Build glob patterns for:
      <root>/<scene>/<subdir>/**/<pat>
      <root>/<tile>/<subdir>/**/<pat>
      <root>/<tile split>/<subdir>/**/<pat>
    """
    scene_dir = os.path.join(base_root, scene, subdir)
    underscore_dir = os.path.join(base_root, tile_arg, subdir)
    split_dir = os.path.join(base_root, tile_arg.replace("_", "/"), subdir)

    patterns = []
    for base in (scene_dir, underscore_dir, split_dir):
        for pat in family_patterns:
            patterns.append(os.path.join(base, "**", pat))
    return dedupe_keep_order(patterns)

def expand_patterns(
    patterns: list[str],
    label: str,
    limit: int = 30
) -> list[str]:
    """
    Expand a list of glob patterns into actual file paths, with
    verbose debug output showing exactly what matched.

    This function is intended for DEBUGGING ONLY:
      - it does not filter files
      - it does not select by date
      - it does not change processing logic

    It is used to make glob behaviour visible and auditable.
    """

    print(f"\n[DEBUG] Expanding {label} patterns to actual file matches...\n")

    # Accumulate all matches from all patterns (may include duplicates)
    all_matches: list[str] = []

    for pat in patterns:
        # Expand this glob pattern into actual file paths.
        # recursive=True allows '**' patterns to work.
        matches = sorted(glob.glob(pat, recursive=True))

        # Append to the running list (duplicates handled later).
        all_matches.extend(matches)

        # Debug output for this pattern
        print(f"[DEBUG] pattern: {pat}")
        print(f"[DEBUG]   matches: {len(matches)}")

        # Show only the first `limit` files to avoid flooding stdout.
        for fp in matches[:limit]:
            print(f"    {fp}")

        # Indicate if there are more matches than we printed.
        if len(matches) > limit:
            print(f"    ... ({len(matches) - limit} more)")

        print("")

    # Remove duplicates while preserving the original match order.
    # This matters when multiple patterns overlap.
    files = dedupe_keep_order(all_matches)

    print(f"[DEBUG] Total matched {label} files (deduped): {len(files)}")

    # Return the final list of unique file paths.
    return files


def print_date_summary(
    files: list[str],
    start_yyyymmdd: str | None,
    end_yyyymmdd: str | None,
    label: str
):
    """
    Print a debug summary of files, showing:
      - which files have a parsable YYYYMMDD date
      - which do not
      - whether each dated file falls within an optional date range

    This is a READ-ONLY diagnostic helper:
      - it does NOT filter or modify the file list
      - it only prints information for debugging
    """
    print(
        "[LOGIC] This is a READ-ONLY diagnostic helper:\n"
        "  - it does NOT filter or modify the file list\n"
        "  - it only prints information for debugging"
    )


    def in_range(d: str) -> bool:
        """
        Return True if date string d (YYYYMMDD) falls within
        [start_yyyymmdd, end_yyyymmdd], inclusive.

        If start or end is None, everything is considered in range.
        """
        if not start_yyyymmdd or not end_yyyymmdd:
            return True

        try:
            dd = datetime.strptime(d, "%Y%m%d").date()
            ss = datetime.strptime(start_yyyymmdd, "%Y%m%d").date()
            ee = datetime.strptime(end_yyyymmdd, "%Y%m%d").date()
            return ss <= dd <= ee
        except Exception:
            # Any parsing failure → treat as out-of-range
            return False

    # Files where a date could be parsed → (date, filepath)
    dated = []

    # Files where no date could be parsed
    undated = []

    for fp in files:
        d = extract_date(fp)  # expected to return YYYYMMDD or None
        if d:
            dated.append((d, fp))
        else:
            undated.append(fp)

    # High-level counts
    print(f"[DEBUG] {label} files with parsed dates: {len(dated)}")
    print(f"[DEBUG] {label} files without parsed dates: {len(undated)}")

    # Keep only files that are inside the requested date range
    in_range_items = [(d, fp) for (d, fp) in dated if in_range(d)]
    out_range_count = len(dated) - len(in_range_items)

    print(f"[DEBUG] {label} files IN-RANGE: {len(in_range_items)}")
    print(f"[DEBUG] {label} files OUT-OF-RANGE: {out_range_count}")

    # Print up to the first 50 IN-RANGE files (sorted by date)
    for d, fp in sorted(in_range_items)[:50]:
        print(f"  {d} [IN-RANGE]  {fp}")

    if len(in_range_items) > 50:
        print(f"  ... ({len(in_range_items) - 50} more IN-RANGE files)")


    # Show undated files separately (these are often bugs or surprises)
    if undated:
        print(f"\n[DEBUG] Undated {label} files (first 50):")
        for fp in undated[:50]:
            print(f"  {fp}")
        if len(undated) > 50:
            print(f"  ... ({len(undated) - 50} more undated files)")

    import sys
    sys.exit(f"[DEBUG] print_date_summary force closed")

import glob
import re

_SR_DATE_RX = re.compile(r"(19|20)\d{2}[01]\d[0-3]\d")  # YYYYMMDD in basename

def _sr_date_from_path(fp: str) -> str | None:
    m = _SR_DATE_RX.search(os.path.basename(fp))
    return m.group(0) if m else None

def _find_sr_timeseries_files(sr_root: str, scene: str, only_clr: bool) -> list[str]:
    """
    Your real on-disk layout:
      <sr_root>/<scene>/sr/YYYY/YYYYMM/ls89sr_<scene>_<YYYYMMDD>_nbart6m*_clr.tif
    """
    base = os.path.join(sr_root, scene, "sr")
    if only_clr:
        pat = f"ls89sr_{scene}_*_nbart6m*_clr.tif"
    else:
        pat = f"ls89sr_{scene}_*_nbart6m*.tif"
    return sorted(glob.glob(os.path.join(base, "**", pat), recursive=True))


def _resolve_sr_input(
    hint: str,
    date_tag: str,
    tile: str,
    sr_root: str | None,
    fc_root: str | None,
    sr_only_clr: bool = False,
) -> Tuple[str, str]:
    """
    Work out which Surface Reflectance (SR) composite file to use for a given
    tile and target date, and return:

        (path_to_chosen_file, date_of_that_file)

    This function is deliberately tolerant of different directory layouts and
    filename patterns. It implements a series of search strategies, from
    "most specific" to "broad fallback".

    Inputs:
        hint       - either:
                       * a file path (e.g. an explicit *_nbart6m*.tif), or
                       * a directory to search in, or
                       * a free-form string that may not exist
        date_tag   - target date as 'YYYYMMDD' string (e.g. '20200611')
        tile       - tile code as 'PPP_RRR' (e.g. '104_072')
        sr_root    - root folder where SR composites live (EASI-style layout)
        fc_root    - optional alternative root to also search (e.g. FC root)
        sr_only_clr
                   - if True: only consider SR files that are already cloud-masked
                               (suffix *_clr.tif). If False: allow both clr and raw.

    Returns:
        (sr_path, sr_date)
           sr_path = absolute path to the chosen SR composite file
           sr_date = extracted date 'YYYYMMDD' from its name (or target if unknown)

    If nothing suitable is found, the function exits the program with a
    clear error message via SystemExit.
    """
    import glob
    import re
    from datetime import datetime as _dt

    # ----------------------------------------
    # 0. Basic tile → scene conversion
    # ----------------------------------------
    # Tile must be 'PPP_RRR', e.g. "104_072".
    if "_" not in tile:
        raise ValueError("Tile must be PPP_RRR e.g. 104_072")
    p, r = tile.split("_")

    # Scene code is 'pPPPrRRR', e.g. "p104r072".
    scene = f"p{p}r{r}".lower()

    # ----------------------------------------
    # Helper: extract date from filename
    # ----------------------------------------
    def extract_date_from_name(name: str) -> str | None:
        """
        Pull out the first 8-digit date that starts with 19 or 20
        (e.g. 20200611) from a filename. Returns None if not found.
        """
        m = re.search(r"(19|20)\d{6}", name)
        return m.group(0) if m else None

    # ----------------------------------------
    # Helper: pick nearest file by date
    # ----------------------------------------
    def pick_nearest(paths: List[str], target: str) -> Tuple[str, str]:
        """
        Given a list of candidate file paths and a target date (YYYYMMDD),
        choose the file whose embedded date is closest in time to target.

        If there is a tie, the later date (larger YYYYMMDD) wins.

        Returns:
            (chosen_path, chosen_date)
        """
        tgt = _dt.strptime(target, "%Y%m%d").date()
        best = None  # (path, date_str)
        best_key = None  # (abs_day_difference, -int(date_str))

        for pth in paths:
            d = extract_date_from_name(Path(pth).name)
            if not d:
                continue
            dd = _dt.strptime(d, "%Y%m%d").date()
            # key = (distance in days, negative date) so that:
            #   - smaller distance is better
            #   - for the same distance, larger date (more recent) wins
            key = (abs((dd - tgt).days), -int(d))
            if best_key is None or key < best_key:
                best_key = key
                best = (pth, d)

        if best:
            return best

        # Fallback: if none have parseable dates, just use the first path and
        # pretend its date is either extracted or the target date.
        return paths[0], (extract_date_from_name(Path(paths[0]).name) or target)

    # ----------------------------------------
    # 1. Define filename patterns (clr-only vs clr+non-clr)
    # ----------------------------------------
    # These patterns are matched against filenames inside the relevant folders.
    # They allow for DEA-style nbart6m composites and older srb6/srb7 stacks.
    if sr_only_clr:
        # When we only want cloud-masked outputs.
        exact_patterns = [
            f"*{date_tag}*nbart6m*_clr.tif",
            f"*{date_tag}*srb7_clr.tif",
            f"*{date_tag}*srb6_clr.tif",
        ]
        any_patterns = [
            "*nbart6m*_clr.tif",
            "*srb7_clr.tif",
            "*srb6_clr.tif",
        ]
    else:
        # When we allow both clr and non-clr versions.
        exact_patterns = [
            f"*{date_tag}*nbart6m*_clr.tif",
            f"*{date_tag}*nbart6m*.tif",
            f"*{date_tag}*srb7_clr.tif",
            f"*{date_tag}*srb7.tif",
            f"*{date_tag}*srb6_clr.tif",
            f"*{date_tag}*srb6.tif",
        ]
        any_patterns = [
            "*nbart6m*_clr.tif",
            "*nbart6m*.tif",
            "*srb7_clr.tif",
            "*srb7.tif",
            "*srb6_clr.tif",
            "*srb6.tif",
        ]

    # ----------------------------------------
    # 2. First strategy: trust the 'hint' if it exists
    # ----------------------------------------
    # The hint might be a direct file path or a directory to search.
    p_hint = Path(hint)
    if p_hint.exists():
        # Case 1: hint is a file -> just use it.
        if p_hint.is_file():
            d = extract_date_from_name(p_hint.name) or date_tag
            return str(p_hint), d

        # Case 2: hint is a directory -> look inside it for matching patterns.
        exact: List[str] = []
        for pat in exact_patterns:
            exact.extend(glob.glob(str(p_hint / pat)))

        # Keep only those that contain the scene code in the filename.
        exact = [c for c in exact if scene in Path(c).name.lower()]
        if exact:
            return pick_nearest(exact, date_tag)

        # If no exact date match, try any SR composite in that directory.
        anyc: List[str] = []
        for pat in any_patterns:
            anyc.extend(glob.glob(str(p_hint / pat)))
        anyc = [c for c in anyc if scene in Path(c).name.lower()]
        if anyc:
            return pick_nearest(anyc, date_tag)

    # ----------------------------------------
    # 3. Second strategy: search under SR/FC roots using EASI-like layout
    # ----------------------------------------
    # Combine SR and FC roots (ignoring None).
    roots = [r for r in (sr_root, fc_root) if r]

    # Break up the target date into year and year+month folder names.
    yyyy = date_tag[:4]
    yyyymm = date_tag[:6]

    cands: List[str] = []

    for base in roots:
        base = Path(base)

        # We support a few possible layouts:
        #   1) base / p104r072 / sr / YYYY / YYYYMM  (scene directory)
        #   2) base / 104_072 / sr / YYYY / YYYYMM  (tile with underscore)
        #   3) base / 104 / 072 / sr / YYYY / YYYYMM (separate path/row dirs)
        easi_dir = base / scene / "sr" / yyyy / yyyymm
        underscore_dir = base / tile / "sr" / yyyy / yyyymm
        split_dir = base / p / r / "sr" / yyyy / yyyymm

        # Search these candidate directories for exact date patterns first.
        for ddir in (easi_dir, underscore_dir, split_dir):
            for pat in exact_patterns:
                cands.extend(glob.glob(str(ddir / pat)))

    # Filter by scene code in filename.
    cands = [c for c in cands if scene in Path(c).name.lower()]
    if cands:
        # If we found anything, pick the date closest to date_tag.
        return pick_nearest(sorted(set(cands)), date_tag)

    # ----------------------------------------
    # 4. Third strategy: any SR composite in the same month folders
    # ----------------------------------------
    any_month: List[str] = []

    for base in roots:
        base = Path(base)
        easi_dir = base / scene / "sr" / yyyy / yyyymm
        underscore_dir = base / tile / "sr" / yyyy / yyyymm
        split_dir = base / p / r / "sr" / yyyy / yyyymm

        for ddir in (easi_dir, underscore_dir, split_dir):
            for pat in any_patterns:
                any_month.extend(glob.glob(str(ddir / pat)))

    any_month = [c for c in any_month if scene in Path(c).name.lower()]
    if any_month:
        return pick_nearest(sorted(set(any_month)), date_tag)

    # ----------------------------------------
    # 5. Fourth strategy: recursive search under roots (scene/sr/**)
    # ----------------------------------------
    # Try recursive glob under 'base/scene/sr/**/pattern' for exact patterns.
    broad: List[str] = []
    for base in roots:
        base = Path(base)
        for pat in exact_patterns:
            broad.extend(
                glob.glob(str(base / scene / "sr" / "**" / pat), recursive=True)
            )
        if broad:
            break  # stop at first root that yields something

    broad = [c for c in broad if scene in Path(c).name.lower()]
    if broad:
        return pick_nearest(sorted(set(broad)), date_tag)

    # ----------------------------------------
    # 6. Final strategy: any SR composite under scene/sr/** (recursive)
    # ----------------------------------------
    any_all: List[str] = []
    for base in roots:
        base = Path(base)
        for pat in any_patterns:
            any_all.extend(
                glob.glob(str(base / scene / "sr" / "**" / pat), recursive=True)
            )
        if any_all:
            break  # stop when we get some hits from a root

    any_all = [c for c in any_all if scene in Path(c).name.lower()]
    if any_all:
        return pick_nearest(sorted(set(any_all)), date_tag)

    # ----------------------------------------
    # 7. If everything failed: stop with a clear error message
    # ----------------------------------------
    if sr_only_clr:
        raise SystemExit(
            "\n".join(
                [
                    f"[ERR] sr_only_clr=True but no *_clr SR composite found for {tile} date {date_tag}.",
                    " You confirmed masking exists—so this usually means:",
                    "   - the SR *_clr.tif files are not in the expected folders, or",
                    "   - the filename pattern differs (e.g. *_nbart6m*_clr.tif).",
                    f" Searched roots: {roots or 'N/A'}",
                ]
            )
        )


def main():
    """
    EDS master processing pipeline (high-level orchestrator).

    This script:
      1. Figures out which tile and dates we’re working on.
      2. Builds “compat” products if needed:
           - db8 = multi-band surface reflectance stacks (start & end dates)
           - dc4 = FPC time-series stack
      3. Runs the legacy change detection method to produce:
           - DLL = change classes (clearing vs no-clearing)
           - DLJ = interpretation layers (spectral, sTest, combined, clearing probability)
      4. Styles the rasters (palettes/band names) for easier viewing.
      5. Polygonises clearing classes into vector polygons.
      6. Cleans the vector outputs (dissolve, remove skinny artefacts).
      7. Computes FC coverage masks (consistent footprint / ratio presence).
      8. Optionally clips vectors to coverage masks and packages everything as a ZIP.

    The goal is: run one command per tile and get *all* the compatible
    EDS outputs in a predictable folder structure.
    """

    # ----------------------------------------------------------------------
    # 1. Parse command-line arguments for the whole pipeline
    # ----------------------------------------------------------------------
    # Each argument corresponds to a control “knob”:
    #   - what tile, dates, baselines to use
    #   - where SR/FC data live
    #   - where outputs will be written
    #   - how aggressive to be with thresholds, coverage, etc.
    ap = argparse.ArgumentParser(description="EDS master processing pipeline")

    ap.add_argument("--tile", required=True)
    ap.add_argument("--start-date", required=True, help="YYYYMMDD start")
    ap.add_argument("--end-date", required=True, help="YYYYMMDD end")
    ap.add_argument(
        "--span-years", type=int, default=10, help="Years of FC baseline to look back"
    )
    ap.add_argument(
        "--sr-dir-start",
        required=False,
        help="Directory or composite file for start SR date "
        "(contains *_B2*.tif etc. OR *_srb6/7.tif)",
    )
    ap.add_argument(
        "--sr-dir-end",
        required=False,
        help="Directory or composite file for end SR date",
    )
    ap.add_argument(
        "--sr-root", required=False, help="Root of SR storage (informational)"
    )
    ap.add_argument(
        "--fc-root", required=False, help="Root of FC storage (informational)"
    )
    ap.add_argument(
        "--fc-glob", help="Override glob for FC inputs (recursive patterns allowed)"
    )
    ap.add_argument("--out-root", default="data/compat/files", help="Base output root")
    ap.add_argument(
        "--season-window",
        nargs=2,
        metavar=("MMDD_START", "MMDD_END"),
        help="Override seasonal window for baseline (MMDD MMDD)",
    )
    ap.add_argument("--thresholds", nargs="*", type=int, default=DEFAULT_THRESHOLDS)
    ap.add_argument(
        "--min-ha", type=float, default=1.0, help="Minimum polygon size in hectares"
    )
    ap.add_argument(
        "--skinny-pixels",
        type=int,
        default=3,
        help="Remove “skinny” artefacts narrower than this many pixels",
    )
    ap.add_argument(
        "--ratio-presence",
        nargs="*",
        type=float,
        help="Optional FC presence ratios for coverage masks",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands but do not actually run them",
    )
    ap.add_argument(
        "--omit-fpc-start-threshold",
        action="store_true",
        help="Disable fpcStart<108 => no-clearing rule in legacy method",
    )
    ap.add_argument(
        "--lookback-cap",
        type=int,
        default=10,
        help="Maximum years to look back for FC baseline",
    )
    ap.add_argument(
        "--save-per-input-masks",
        action="store_true",
        help="In FC coverage step, save individual input masks as well",
    )
    ap.add_argument(
        "--fc-only-clr",
        action="store_true",
        help="Forward to compat builder: use only *_fc3ms_clr.tif",
    )
    ap.add_argument(
        "--sr-only-clr",
        action="store_true",
        help="Restrict SR composites to *_nbart6m*_clr.tif or *_srb?_clr.tif where available",
    )
    ap.add_argument(
        "--collect-logs",
        action="store_true",
        help="After processing, scan out-root for *_dllmz_log.json and write consolidated summaries",
    )
    ap.add_argument(
        "--fc-prefer-clr",
        action="store_true",
        help="Forward prefer-clr behaviour (otherwise default prefer)",
    )

    # FC→FPC conversion controls (used when compat builder needs to derive FPC from FC)
    ap.add_argument(
        "--fc-convert-to-fpc",
        action="store_true",
        help="Convert FC green to FPC in compat build (dc4) using "
        "FPC=100*(1-exp(-k*FC^n))",
    )
    ap.add_argument(
        "--fc-k",
        type=float,
        default=0.000435,
        help="k parameter for FC->FPC conversion (default 0.000435)",
    )
    ap.add_argument(
        "--fc-n",
        type=float,
        default=1.909,
        help="n parameter for FC->FPC conversion (default 1.909)",
    )
    ap.add_argument(
        "--fc-nodata",
        type=float,
        help="Override nodata value for FC inputs; "
        "defaults to band nodata if present",
    )

    # Runtime environment and packaging options
    ap.add_argument(
        "--python-exe",
        help="Override Python executable for subprocess steps "
        "(use GDAL-enabled env)",
    )
    ap.add_argument(
        "--force-compat",
        action="store_true",
        help="Force rebuilding compat products even if db8/dc4 already exist",
    )
    ap.add_argument(
        "--package-dest", help="If set, zip scene outputs to this directory at the end"
    )

    ap.add_argument(
        "--timeseries-source",
        choices=["fc", "fpc", "sr", "ndvi"],
        default="fc",
        help=(
            "Source for time-series stack: "
            "'fc' (FPC-based dc4 from FC inputs, legacy SLATS style, default) "
            "or 'sr' (SR-only time-series – uses SR-based compat + legacy scripts)."
        ),
        
    )
    ap.add_argument(
        "--force-clr",
        action="store_true",
        help="Force use of *_clr inputs for both SR and FC (recommended for production)",
    )



    args = ap.parse_args()

    # Normalise CLR flags: --force-clr means "use masked (_clr) inputs wherever possible"
    if getattr(args, "force_clr", False):
        for name, value in {
            "fc_only_clr": True,
            "fc_prefer_clr": True,
            "sr_only_clr": True,
        }.items():
            if hasattr(args, name):
                setattr(args, name, value)

    # ----------------------------------------------------------------------
    # Adjust output root to include timeseries source (fc / sr / ndvi)
    # ----------------------------------------------------------------------
    import os
    if args.timeseries_source:
        args.out_root = os.path.join(
            args.out_root,
            args.timeseries_source.lower()
        )

    # Ensure the directory exists
    os.makedirs(args.out_root, exist_ok=True)

    print(f"[DEBUG] Using output root: {args.out_root}")



    # ----------------------------------------------------------------------
    # 2. Basic setup: scene code and output folder
    # ----------------------------------------------------------------------
    # Convert a tile written as PPP_RRR (e.g. 104_072) into the scene code
    # used in filenames, e.g. "p104r072".
    scene = derive_scene(args.tile)

    # All compat outputs for this tile/scene live under:
    #   <out-root>/pPPPrRRR
    compat_dir = Path(args.out_root) / scene
    compat_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------------
    # Initialise results early so we can record inputs as we discover them
    # ----------------------------------------------------------------------
    results = {
        "inputs": {"sr": {}, "fc": {}},
        "outputs": {},
        "steps": [],
    }

    # ----------------------------------------------------------------------
    # 3. Build FC or SR input patterns
    # ----------------------------------------------------------------------
    start_date = getattr(args, "start_date", None) or getattr(args, "start_db8", None)
    end_date   = getattr(args, "end_date", None)   or getattr(args, "end_db8", None)
    print("start date: ", start_date)
    print("end date: ", end_date)
    print("=" * 100)

    # Ensure these always exist (prevents UnboundLocalError later)
    fc_patterns: list[str] = []
    sr_patterns: list[str] = []
    fc_files: list[str] = []
    sr_files: list[str] = []

    # Ensure results inputs dict exists
    results.setdefault("inputs", {})
    results["inputs"].setdefault("fc", {})
    results["inputs"].setdefault("sr", {})

    if args.timeseries_source in ("fc", "fpc"):
        print(f"running on FC-derived data ({args.timeseries_source})")

        base_root = args.fc_root or ""
        fc_glob = getattr(args, "fc_glob", None)

        if fc_glob:
            fc_patterns = [fc_glob]
        else:
            family = [
                "*galsfc3_*_fcm*_clr.tif" if args.fc_only_clr else "*galsfc3_*_fcm*.tif"
            ]
            fc_patterns = build_patterns(base_root, scene, args.tile, "fc", family)

        print(f"[DEBUG] fc_patterns ({len(fc_patterns)}):")
        for p in fc_patterns:
            print(" ", p)

        fc_files = expand_patterns(fc_patterns, "FC", limit=30)

        src = args.timeseries_source  # "fc" or "fpc"

        results["inputs"].setdefault(src, {})
        results["inputs"][src]["patterns"] = list(map(str, fc_patterns))
        results["inputs"][src]["matched_files"] = sorted(map(str, fc_files))
        results["inputs"][src]["matched_count"] = len(fc_files)


        if len(fc_files) == 0:
            raise SystemExit(
                "[ERR] FC mode selected but no FC files matched your patterns. "
                "Fix the glob patterns or check --fc-root/--tile."
            )

    elif args.timeseries_source in ("sr", "ndvi"):
        print("running on SR data")
        base_root = args.sr_root or ""
        sr_glob = getattr(args, "sr_glob", None)

        if sr_glob:
            sr_patterns = [sr_glob]
        else:
            # Match your real SR filenames (nbart6m6_*_clr.tif)
            # Use nbart6m* if you want this to be future-proof.
            family = [
                "*ls89sr_*_nbart6m6_clr.tif" if args.sr_only_clr else "*ls89sr_*_nbart6m6*.tif",
                # alternative safer version:
                # "*ls89sr_*_nbart6m*_clr.tif" if args.sr_only_clr else "*ls89sr_*_nbart6m*.tif",
            ]
            sr_patterns = build_patterns(base_root, scene, args.tile, "sr", family)

        print(f"[DEBUG] sr_patterns ({len(sr_patterns)}):")
        for p in sr_patterns:
            print(" ", p)

        sr_files = expand_patterns(sr_patterns, "SR", limit=30)

        src = args.timeseries_source  # "sr" or "ndvi"

        results["inputs"].setdefault(src, {})
        results["inputs"][src]["patterns"] = list(map(str, sr_patterns))
        results["inputs"][src]["matched_files"] = sorted(map(str, sr_files))
        results["inputs"][src]["matched_count"] = len(sr_files)


        if len(sr_files) == 0:
            raise SystemExit(
                "[ERR] SR/NDVI mode selected but no SR files matched your patterns. "
                "Fix the glob patterns or check --sr-root/--tile, and confirm nbart6m6 naming."
            )

    else:
        raise ValueError(f"Unknown timeseries_source: {args.timeseries_source}")


    # import sys
    # sys.exit("forced end sys")

    # ----------------------------------------------------------------------
    # 4. Resolve SR inputs (start and end composites)
    # ----------------------------------------------------------------------
    # We may be given a direct path (file or directory), or just a root.
    # _resolve_sr_input encapsulates the “find nearest composite by date”
    # logic and returns both the chosen path and its effective date.
    hint_start = args.sr_dir_start or (args.sr_root or args.fc_root or ".")
    hint_end = args.sr_dir_end or (args.sr_root or args.fc_root or ".")

    sr_start_path, eff_start = _resolve_sr_input(
        hint_start,
        args.start_date,
        args.tile,
        args.sr_root,
        args.fc_root,
        sr_only_clr=args.sr_only_clr,
    )
    sr_end_path, eff_end = _resolve_sr_input(
        hint_end,
        args.end_date,
        args.tile,
        args.sr_root,
        args.fc_root,
        sr_only_clr=args.sr_only_clr,
    )

    print("[DEBUG] SR start resolved:", sr_start_path)
    print("[DEBUG] SR end resolved:  ", sr_end_path)
    print("[DEBUG] sr_only_clr:", args.sr_only_clr)

    # Add to json output
    results["inputs"]["sr"] = {
        "sr_only_clr": bool(args.sr_only_clr),
        "start": {"requested_date": args.start_date, "effective_date": eff_start, "path": str(sr_start_path)},
        "end":   {"requested_date": args.end_date,   "effective_date": eff_end,   "path": str(sr_end_path)},
    }



    # import sys
    # sys.exit("troubleshooting")

    # ----------------------------------------------------------------------
    # 5. Derive seasonal window (MMDD range) for time-series baseline
    #    (applies to FC, FPC, and NDVI)

    # ----------------------------------------------------------------------
    # The seasonal window controls which FC/FPC dates are used to build
    # the baseline time-series (e.g. within ±2 months around start/end).
    from datetime import datetime
    import calendar

    def _shift_months(dt: datetime, delta_months: int) -> datetime:
        """
        Shift a date by +/- delta_months, clamping the day to the valid range.

        This is used to move the start/end dates backward/forward by a fixed
        number of months while staying in a valid calendar day.
        """
        orig = dt.strftime("%Y-%m-%d")

        month_index = dt.year * 12 + (dt.month - 1) + delta_months
        year = month_index // 12
        month = month_index % 12 + 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(dt.day, last_day)

        shifted = f"{year:04d}-{month:02d}-{day:02d}"

        print(
            f"[DEBUG] shift months: "
            f"original={orig}, "
            f"delta_months={delta_months:+d}, "
            f"shifted={shifted}"
        )

        return datetime(year, month, day)


    if args.season_window:
        # User explicitly specified MMDD_START, MMDD_END → honour it.
        win_start, win_end = args.season_window
        print(
            f"[DEBUG] - explicet seasonal window win start: {win_start} win end: {win_end}"
        )
    else:
        # Otherwise, build a default window around the effective SR dates:
        #   - 2 months before effective start
        #   - 2 months after effective end
        sd_dt = datetime.strptime(eff_start, "%Y%m%d")
        ed_dt = datetime.strptime(eff_end, "%Y%m%d")
        ws_dt = _shift_months(sd_dt, -2)  # 2 months before start
        we_dt = _shift_months(ed_dt, +2)  # 2 months after end
        win_start = f"{ws_dt.month:02d}{ws_dt.day:02d}"
        win_end = f"{we_dt.month:02d}{we_dt.day:02d}"

        print(
            f"[DEBUG] - default 2 months seasonality win start: {win_start}, and win end {win_end}"
        )

    # Legacy FC lookback years (bounded by lookback_cap)
    lookback = min(args.span_years, args.lookback_cap)
    print(f"[DEBUG] lookback: {lookback}")

    # import sys
    # sys.exit("forced stop section 5")

    # ----------------------------------------------------------------------
    # 6. Initialise results log (JSON-friendly)
    # ----------------------------------------------------------------------
    # Purpose:
    #   Build a run-manifest (provenance log) describing what the pipeline was asked
    #   to do, what it actually used (effective dates/paths), and where outputs will
    #   be written. This does NOT change processing; it's for audit/reproducibility.
    #
    # Notes:
    #   - requested_* are what the user asked for on the CLI
    #   - effective_* are what the resolver actually chose (can differ if nearest-date logic kicks in)
    #   - outputs is populated progressively by later steps
    import os
    import json
    import socket
    from datetime import datetime
    from datetime import datetime, timezone

    def write_manifest(tag: str = ""):
        try:
            out_root = getattr(args, "out_root", None) or "."
            os.makedirs(out_root, exist_ok=True)
            out_path = os.path.join(
                out_root,
                f"eds_master_results_{args.tile}_{args.timeseries_source}_d{args.start_date}_{args.end_date}.json",
            )
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, sort_keys=True)
            print(f"[DEBUG] Wrote results manifest{tag}: {out_path}")
        except Exception as e:
            print(f"[WARN] Could not write results manifest{tag}: {e}")


    results.update({
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hostname": socket.gethostname(),
        "cwd": os.getcwd(),

        "tile": args.tile,
        "scene": scene,
        "timeseries_source": args.timeseries_source,

        "requested_start_date": args.start_date,
        "requested_end_date": args.end_date,

        "effective_start_date": eff_start,
        "effective_end_date": eff_end,

        "sr_inputs": {
            "sr_only_clr": bool(args.sr_only_clr),
            "sr_root": args.sr_root,
            "fc_root_fallback": args.fc_root,
            "hint_start": hint_start,
            "hint_end": hint_end,
            "start_path": sr_start_path,
            "end_path": sr_end_path,
        },


        "fc_inputs": {
            "fc_only_clr": bool(getattr(args, "fc_only_clr", False)),
            "fc_root": getattr(args, "fc_root", None),
            "fc_glob": getattr(args, "fc_glob", None),
        },


        "seasonal_window": {
            "explicit": bool(getattr(args, "season_window", None)),
            "window_start_mmdd": win_start,
            "window_end_mmdd": win_end,
            "span_years_requested": args.span_years,
            "lookback_cap": args.lookback_cap,
            "lookback_used": lookback,
        },

        "outputs_root": args.out_root,
    })


    # Optional: write the manifest now (handy during debugging when you sys.exit early)
    # Writes into out_root so it’s easy to find alongside products/logs.
    try:
        os.makedirs(args.out_root, exist_ok=True)
        out_path = os.path.join(
            args.out_root,
            f"eds_master_results_{args.tile}_{args.timeseries_source}_d{args.start_date}_{args.end_date}.json",
        )
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"[DEBUG] Wrote results manifest: {out_path}")
    except Exception as e:
        print(f"[WARN] Could not write results manifest: {e}")


    write_manifest(" (after section 6)")

    # import sys
    # sys.exit("forced stop section 6")

    # ----------------------------------------------------------------------
    # 7 Step 1: Build compat products (db8 & dc4) if needed
    # ----------------------------------------------------------------------
    pyexe = args.python_exe or sys.executable
    import glob as _glob

    dc4_tag = {
    "fc": "dc4fc",
    "fpc": "dc4fpc",
    "ndvi": "dc4ndvi",
    }.get(args.timeseries_source, "dc4mz")


    # Always define expected outputs (these must exist as variables even if we skip build)
    db8_start = compat_dir / f"lztmre_{scene}_{eff_start}_db8mz.img"
    db8_end   = compat_dir / f"lztmre_{scene}_{eff_end}_db8mz.img"
    dc4_glob = str(compat_dir / f"lztmre_{scene}_*_{dc4_tag}.img")



    # Look for existing dc4 stack members
    dc4_existing = _glob.glob(dc4_glob)

    # Decide whether we need to (re)build compat products
    need_compat = args.force_compat or (
        (not db8_start.exists())
        or (not db8_end.exists())
        or (len(dc4_existing) < 2)
    )

    if need_compat:
        # Compat builder script
        if args.timeseries_source in ("fc", "fpc"):

            compat_script = Path(__file__).resolve().parent / "easi_slats_compat_builder_fc.py"
        elif args.timeseries_source in ("sr", "ndvi"):
            compat_script = Path(__file__).resolve().parent / "easi_slats_compat_builder_sr_ndvi.py"
        else:
            raise ValueError(f"Unknown timeseries_source: {args.timeseries_source}")

        if args.timeseries_source in ("fc", "fpc"):

            cmd_compat = [
                pyexe,
                str(compat_script),
                "--tile", scene,
                "--out-root", str(compat_dir.parent),
                "--sr-dir", sr_start_path,
                "--sr-dir", sr_end_path,
                "--sr-date", eff_start,
                "--sr-date", eff_end,
            ]

            # NEW: ensure dc4 name is explicit (dc4fc / dc4fpc)
            cmd_compat.extend(["--dc4-tag", dc4_tag])

            for pat in fc_patterns:
                cmd_compat.extend(["--fc", pat])

            if args.fc_only_clr:
                cmd_compat.append("--fc-only-clr")
            if args.fc_prefer_clr:
                cmd_compat.append("--fc-prefer-clr")

            # NEW: FPC conversion is controlled by timeseries_source, not a separate flag
            if args.timeseries_source == "fpc":
                cmd_compat.append("--fc-convert-to-fpc")
                cmd_compat.extend(["--fc-k", str(args.fc_k), "--fc-n", str(args.fc_n)])
                if args.fc_nodata is not None:
                    cmd_compat.extend(["--fc-nodata", str(args.fc_nodata)])

            results.setdefault("inputs", {}).setdefault("compat_build", {})
            results["inputs"]["compat_build"]["mode"] = args.timeseries_source
            results["inputs"]["compat_build"]["dc4_tag"] = dc4_tag
            results["inputs"]["compat_build"]["sr_start"] = {"date": eff_start, "path": str(sr_start_path)}
            results["inputs"]["compat_build"]["sr_end"]   = {"date": eff_end,   "path": str(sr_end_path)}
            results["inputs"]["compat_build"]["fc_patterns"] = list(map(str, fc_patterns))

            run_cmd(cmd_compat, args.dry_run, "build_compat", results)



        elif args.timeseries_source == "ndvi":

            print("Working on NDVI (SR baseline) ---" * 20)

            sr_root = args.sr_root
            sr_only_clr = getattr(args, "sr_only_clr", False) or getattr(args, "force_clr", False)

            # Find all SR composites for this scene
            sr_files = _find_sr_timeseries_files(sr_root, scene, only_clr=sr_only_clr)

            # Baseline years for legacy method:
            # include (start_year - lookback) .. effective_end, filtered to seasonal window.
            start_year = int(eff_start[:4])
            baseline_start_year = start_year - lookback
            baseline_start_date = f"{baseline_start_year}0101"
            baseline_end_date = eff_end  # don't build beyond effective end

            def _in_season_window(yyyymmdd: str, win_start_mmdd: str, win_end_mmdd: str) -> bool:
                """Return True if YYYYMMDD falls within the seasonal MMDD window (handles wrap-around)."""
                mmdd = yyyymmdd[4:]
                if win_start_mmdd <= win_end_mmdd:
                    return win_start_mmdd <= mmdd <= win_end_mmdd
                return (mmdd >= win_start_mmdd) or (mmdd <= win_end_mmdd)

            # Select baseline SR items
            sr_items: list[tuple[str, str]] = []
            for fp in sr_files:
                d = _sr_date_from_path(fp)
                if not d:
                    continue
                if baseline_start_date <= d <= baseline_end_date and _in_season_window(d, win_start, win_end):
                    sr_items.append((d, fp))

            sr_items.sort(key=lambda x: x[0])

            print(f"[DEBUG] SR files found total: {len(sr_files)}")
            print(
                f"[DEBUG] SR files in baseline span {baseline_start_date}..{baseline_end_date} "
                f"AND window {win_start}..{win_end}: {len(sr_items)}"
            )
            for d, fp in sr_items[:10]:
                print(f"  {d}  {fp}")
            if len(sr_items) > 10:
                print(f"  ... ({len(sr_items) - 10} more)")

            if len(sr_items) < 2:
                raise RuntimeError(
                    f"NDVI baseline build needs a time series, but only found {len(sr_items)} SR files "
                    f"in baseline span {baseline_start_date}..{baseline_end_date} and season window {win_start}..{win_end} "
                    f"(sr_only_clr={sr_only_clr})."
                )

            # Record inputs
            results.setdefault("inputs", {}).setdefault("compat_build", {})
            results["inputs"]["compat_build"].update({
                "mode": "ndvi",
                "sr_only_clr": bool(sr_only_clr),
                "baseline_start_date": baseline_start_date,
                "baseline_end_date": baseline_end_date,
                "season_window_start": win_start,
                "season_window_end": win_end,
                "sr_items_used": [{"date": d, "path": str(fp)} for d, fp in sr_items],
            })

            # ------------------------------------------------------------
            # Phase A: build ONLY db8 for effective start/end (2 files)
            # ------------------------------------------------------------
            cmd_db8 = [
                pyexe,
                str(compat_script),           # easi_slats_compat_builder_sr_ndvi.py
                "--tile", scene,
                "--out-root", str(compat_dir.parent),
                "--db8-only",
                "--sr-dir", sr_start_path,
                "--sr-date", eff_start,
                "--sr-dir", sr_end_path,
                "--sr-date", eff_end,
            ]
            run_cmd(cmd_db8, args.dry_run, "build_db8_start_end", results)

            # ------------------------------------------------------------
            # Phase B: build ONLY dc4 for baseline dates (no db8 per date)
            # ------------------------------------------------------------
            for d, fp in sr_items:
                cmd_dc4 = [
                    pyexe,
                    str(compat_script),
                    "--tile", scene,
                    "--out-root", str(compat_dir.parent),
                    "--dc4-only",
                    "--sr-dir", fp,
                    "--sr-date", d,
                ]
                run_cmd(cmd_dc4, args.dry_run, f"build_dc4_{d}", results)

            # Sanity: confirm dc4 exists where legacy step will look
            # dc4_existing = _glob.glob(str(compat_dir / f"lztmre_{scene}_*_dc4mz.img"))
            dc4_existing = _glob.glob(str(compat_dir / f"lztmre_{scene}_*_{dc4_tag}.img"))

            print(f"[DEBUG] Produced dc4mz.img count: {len(dc4_existing)}")
            for p in sorted(dc4_existing)[:10]:
                print("  ", p)
            if len(dc4_existing) > 10:
                print(f"  ... ({len(dc4_existing) - 10} more)")



    else:
        print("\n[STEP] build_compat")
        print("Existing compat products detected; skipping build (use --force-compat to rebuild)")


    # Record compat outputs (these are what downstream steps will use)
    results.setdefault("outputs", {}).setdefault("compat", {})
    results["outputs"]["compat"].update({
        "db8_start": str(db8_start),
        "db8_end": str(db8_end),
        "dc4_glob": str(dc4_glob),
        "dc4_existing": [str(p) for p in sorted(_glob.glob(str(compat_dir / f"lztmre_{scene}_*_dc4mz.img")))],
    })

    write_manifest(" (after section 7)")

    import sys
    sys.exit("forced stop section 7")

    # ----------------------------------------------------------------------
    # 8. Step 2: Legacy change detection (DLL / DLJ)
    # ----------------------------------------------------------------------
    # This step runs the *legacy EDS change detection algorithm*.
    #
    # It combines:
    #   - db8 start composite (spectral stack at start date)
    #   - db8 end composite   (spectral stack at end date)
    #   - dc4 time-series stack (baseline history)
    #
    # and produces:
    #   - DLL: clearing classification raster
    #   - DLJ: interpretation / confidence raster
    #
    # The algorithm uses a *seasonal window* and *lookback period*
    # to decide which historical observations form the baseline.

    # Pattern describing where dc4 stack members live
    # (one dc4 image per historical date)
    dc4_glob = str(compat_dir / f"lztmre_{scene}_*_dc4mz.img")

    # ----------------------------------------------------------------------
    # Select which legacy script to use based on data source
    # ----------------------------------------------------------------------
    # FC mode → FPC/FC-specific logic
    # SR/NDVI mode → spectral reflectance / NDVI logic
    if args.timeseries_source in ("fc", "fpc"):
        legacy_script = Path(__file__).resolve().parent / "easi_eds_legacy_method_window_fc.py"
    elif args.timeseries_source == "ndvi":
        legacy_script = Path(__file__).resolve().parent / "easi_eds_legacy_method_window_sr_ndvi.py"
    else:
        raise ValueError(f"Unknown timeseries_source: {args.timeseries_source}")

    # ----------------------------------------------------------------------
    # Build the command that runs the legacy method
    # ----------------------------------------------------------------------
    # This passes *all resolved parameters* explicitly so the run
    # is fully reproducible and auditable.
    cmd_legacy = [
        pyexe,                      # Python executable (GDAL Python env)
        str(legacy_script),         # Legacy change detection script
        "--scene", scene,           # WRS path/row (scene)
        "--start-date", eff_start,  # Effective start SR date
        "--end-date", eff_end,      # Effective end SR date
        "--window-start", win_start,# Seasonal window start (MMDD)
        "--window-end", win_end,    # Seasonal window end (MMDD)
        "--lookback", str(lookback),# Number of years used for baseline
        "--start-db8", str(db8_start),  # Start db8 composite
        "--end-db8", str(db8_end),      # End db8 composite
        "--dc4-glob", dc4_glob,         # All baseline dc4 members
        "--verbose",                    # Extra logging from legacy script
    ]

    # Optional FC-specific flag:
    # If enabled, the algorithm does NOT enforce a minimum FPC
    # at the start date (used for certain forest/non-forest logic)
    if args.timeseries_source == "fc" and args.omit_fpc_start_threshold:
        cmd_legacy.append("--omit-fpc-start-threshold")

    # ----------------------------------------------------------------------
    # Execute the legacy method
    # ----------------------------------------------------------------------
    # run_cmd():
    #   - executes the command (unless --dry-run)
    #   - captures stdout/stderr
    #   - records timing + command into results["steps"]
    print(f"args.dry_run: {args.dry_run}")
    # import sys
    # sys.exit("forced stop section 7 dry run")
    run_cmd(cmd_legacy, args.dry_run, "legacy_method", results)

    # ----------------------------------------------------------------------
    # Resolve DLL / DLJ outputs
    # ----------------------------------------------------------------------
    # Output filenames differ depending on:
    #   - older legacy naming
    #   - newer "vi-fpc" naming
    #
    # We check for both and pick whichever exists.

    # def _pick_existing(*candidates: Path) -> Path:
    #     """
    #     Return the first path that exists.
    #     If none exist (e.g. --dry-run), return the first candidate
    #     so downstream logic still has a predictable path.
    #     """
    #     for p in candidates:
    #         if p.exists():
    #             return p
    #     return candidates[0]
    def _pick_existing(*candidates: Path, label: str = "") -> Path:
        existing = [p for p in candidates if p.exists()]
        if existing:
            return existing[0]

        print(f"[ERR] Could not find expected {label} output. Tried:")
        for p in candidates:
            print("   -", p, "(exists=" + str(p.exists()) + ")")
        raise FileNotFoundError(f"Missing {label} output; legacy step may not have produced it.")

    # # Resolve the DLL (clearing classification) raster
    # dll = _pick_existing(
    #     compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_vi-fpc_dllmz.img",
    #     compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img",
    # )

    # # Resolve the DLJ (interpretation / confidence) raster
    # dlj = _pick_existing(
    #     compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_vi-fpc_dljmz.img",
    #     compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img",
    # )
    dll = _pick_existing(
        compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_vi-fpc_dllmz.img",
        compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img",
        label="DLL"
    )

    dlj = _pick_existing(
        compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_vi-fpc_dljmz.img",
        compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img",
        label="DLJ"
    )


    import sys
    sys.exit("forced stop section 8 - legacy")
    # ----------------------------------------------------------------------
    # 9. Step 3: Style outputs (apply palette & band names)
    # ----------------------------------------------------------------------
    # This makes the rasters easier to interpret visually in GIS tools.
    style_script = Path(__file__).resolve().parent / "easi_style_dll_dlj.py"

    cmd_style = [
        pyexe,
        str(style_script),
        "--dll",
        str(dll),
        "--dlj",
        str(dlj),
    ]
    run_cmd(cmd_style, args.dry_run, "style_outputs", results)
    # Record styling inputs/outputs (styling modifies metadata/palette; paths remain the same)
    results.setdefault("outputs", {}).setdefault("style_outputs", {})
    results["outputs"]["style_outputs"].update({
        "dll": str(dll),
        "dlj": str(dlj),
        "script": str(style_script),
        "dry_run": bool(args.dry_run),
    })


    # import sys
    # sys.exit("forced stop section 9")

    # ----------------------------------------------------------------------
    # 10. Step 4: Polygonise clearing thresholds
    # ----------------------------------------------------------------------
    # Convert clearing classes (≥ thresholds, usually 34..39) into polygons.
    shp_base = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha"
    shp_base.mkdir(parents=True, exist_ok=True)

    poly_script = (
        Path(__file__).resolve().parent / "easi_polygonize_merged_thresholds.py"
    )

    cmd_poly = [
        pyexe,
        str(poly_script),
        "--dll",
        str(dll),
        "--out-dir",
        str(shp_base),
        "--min-ha",
        str(args.min_ha),
        "--thresholds",
        *[str(t) for t in args.thresholds],
    ]

    # Record polygonisation parameters and output directory (provenance)
    results.setdefault("outputs", {}).setdefault("polygonize_thresholds", {})
    results["outputs"]["polygonize_thresholds"].update({
        "dll": str(dll),
        "out_dir": str(shp_base),
        "min_ha": float(args.min_ha),
        "thresholds": [int(t) for t in args.thresholds],
        "script": str(poly_script),
        "dry_run": bool(args.dry_run),
    })


    run_cmd(cmd_poly, args.dry_run, "polygonize_thresholds", results)

    # import sys
    # sys.exit("forced stop section 10")

    # ----------------------------------------------------------------------
    # 11. Step 5: Vector post-processing (clean up polygons)
    # ----------------------------------------------------------------------
    # This step refines the polygon outputs created in Step 10 by:
    #   - dissolving overlapping polygons
    #   - removing narrow / spurious artefacts ("spaghetti" polygons)
    #   - improving topology for GIS and reporting use
    #
    # It uses the original DLL raster to guide clean-up decisions.

    # Output directory for cleaned vector data
    shp_clean = (
        compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean"
    )

    # Script responsible for vector post-processing
    post_script = Path(__file__).resolve().parent / "easi_vector_postprocess.py"

    # Build the command for vector post-processing
    cmd_post = [
        pyexe,                    # Python executable (GDAL-enabled)
        str(post_script),
        "--input-dir",            # Input polygons from thresholding step
        str(shp_base),
        "--out-dir",              # Output directory for cleaned vectors
        str(shp_clean),
        "--dissolve",             # Merge overlapping polygons
        "--skinny-pixels",        # Remove narrow artefacts below this width
        str(args.skinny_pixels),
        "--from-raster",          # Reference raster to guide cleaning
        str(dll),
    ]

    # Execute vector post-processing
    # - In --dry-run mode, nothing is written
    # - Execution details are recorded in results["steps"]
    run_cmd(cmd_post, args.dry_run, "vector_postprocess", results)

    # ----------------------------------------------------------------------
    # Record vector post-processing outputs and parameters
    # ----------------------------------------------------------------------
    results.setdefault("outputs", {}).setdefault("vector_postprocess", {})
    results["outputs"]["vector_postprocess"].update({
        "input_dir": str(shp_base),
        "output_dir": str(shp_clean),
        "dll_reference": str(dll),
        "dissolve": True,
        "skinny_pixels": int(args.skinny_pixels),
        "script": str(post_script),
        "dry_run": bool(args.dry_run),
    })

    # ----------------------------------------------------------------------
    # Record produced vector files (if not dry-run)
    # ----------------------------------------------------------------------
    if not args.dry_run:
        exts = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".gpkg"}
        files = sorted(
            str(p) for p in shp_clean.rglob("*")
            if p.suffix.lower() in exts
        )
        results["outputs"]["vector_postprocess"]["files"] = files
    else:
        results["outputs"]["vector_postprocess"]["files"] = []

    # Write updated manifest including vector outputs
    write_manifest(" (after vector_postprocess)")
    import sys
    sys.exit("forced stop section 11")

    # ----------------------------------------------------------------------
    # 12. Step 6: FC coverage masks (extent / ratio presence)
    # ----------------------------------------------------------------------
    # Purpose:
    #   This step generates QA layers that summarise *where FC dc4 inputs exist*
    #   across the time-series. This is useful for:
    #     - spotting gaps in the baseline stack (missing dates)
    #     - identifying areas with poor coverage (e.g. clouds/no-data)
    #     - optionally calculating "ratio presence" masks (fraction of time present)
    #
    # It only applies to FC mode because the inputs are dc4 products derived from FC.

    fc_cov_dir = compat_dir / "fc_coverage"  # define regardless (for consistent logging)

    if args.timeseries_source == "fc":
        # Output folder for FC coverage products
        fc_cov_dir.mkdir(parents=True, exist_ok=True)

        # Script that computes coverage/extent from the dc4 stack members
        cov_script = Path(__file__).resolve().parent / "easi_fc_coverage_extent.py"

        # Build the command:
        #   --fc-dir   points at the folder containing dc4 stack members
        #   --pattern  selects which files are considered (here: *_dc4mz.img)
        #   --out-dir  where coverage outputs will be written
        cmd_cov = [
            pyexe,                 # Python executable (GDAL-enabled env)
            str(cov_script),
            "--fc-dir", str(compat_dir),
            "--scene", scene,
            "--pattern", "*_dc4mz.img",
            "--out-dir", str(fc_cov_dir),
        ]

        # Optional: compute ratio/presence products at given ratios
        # (e.g. 0.8 means "present in ≥80% of inputs")
        if args.ratio_presence:
            cmd_cov.append("--ratios")
            cmd_cov.extend(str(r) for r in args.ratio_presence)

        # Optional: also save per-input masks (one mask per dc4 input)
        # Useful for debugging which dates contribute coverage gaps
        if args.save_per_input_masks:
            cmd_cov.append("--save-per-input-masks")

        # Record intent/params (before running so it exists even if the script fails)
        results.setdefault("outputs", {}).setdefault("fc_coverage", {})
        results["outputs"]["fc_coverage"].update({
            "script": str(cov_script),
            "scene": scene,
            "fc_dir": str(compat_dir),
            "pattern": "*_dc4mz.img",
            "out_dir": str(fc_cov_dir),
            "ratio_presence": list(args.ratio_presence) if args.ratio_presence else [],
            "save_per_input_masks": bool(args.save_per_input_masks),
            "dry_run": bool(args.dry_run),
        })

        # Execute the FC coverage step
        # - In --dry-run mode nothing is written
        # - run details are recorded in results["steps"]
        run_cmd(cmd_cov, args.dry_run, "fc_coverage", results)

        # Record produced files (if not dry-run)
        if not args.dry_run:
            # Keep this broad — coverage script may output .img, .hdr, .tif, etc.
            cov_files = sorted(str(p) for p in fc_cov_dir.rglob("*") if p.is_file())
            results["outputs"]["fc_coverage"]["files"] = cov_files
        else:
            results["outputs"]["fc_coverage"]["files"] = []

        # Write manifest after this step so the coverage outputs are captured
        write_manifest(" (after fc_coverage)")

    else:
        # SR-only mode: FC coverage step is not applicable.
        print("\n[STEP] fc_coverage")
        print("Skipping FC coverage – timeseries_source!='fc'.")

        # Still record a structured "skipped" entry in results for provenance
        results.setdefault("outputs", {}).setdefault("fc_coverage", {})
        results["outputs"]["fc_coverage"].update({
            "skipped": True,
            "reason": "FC coverage is only applicable when timeseries_source='fc'",
            "timeseries_source": args.timeseries_source,
            "out_dir": str(fc_cov_dir),
        })

        # Write manifest so the skip is recorded too
        write_manifest(" (after fc_coverage skipped)")


    # # ----------------------------------------------------------------------
    # # 13. Step 7: Clip polygons to strict / ratio coverage (if available)
    # # ----------------------------------------------------------------------
    # clip_script = Path(__file__).resolve().parent / "easi_clip_vectors.py"

    # if args.timeseries_source == "fc":
    #     # Strict coverage polygon
    #     strict_shp = fc_cov_dir / f"{scene}_fc_consistent.shp"
    #     if strict_shp.exists():
    #         clipped_strict = (
    #             compat_dir
    #             / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_strict"
    #         )
    #         clipped_strict.mkdir(parents=True, exist_ok=True)
    #         cmd_clip_strict = [
    #             pyexe,
    #             str(clip_script),
    #             "--input-dir",
    #             str(shp_clean),
    #             "--clip",
    #             str(strict_shp),
    #             "--out-dir",
    #             str(clipped_strict),
    #         ]
    #         run_cmd(cmd_clip_strict, args.dry_run, "clip_strict", results)

    #     # Ratio coverage polygon/mask
    #     ratio_mask = fc_cov_dir / f"{scene}_fc_consistent_mask.shp"
    #     if ratio_mask.exists():
    #         clipped_ratio = (
    #             compat_dir
    #             / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_ratio"
    #         )
    #         clipped_ratio.mkdir(parents=True, exist_ok=True)
    #         cmd_clip_ratio = [
    #             pyexe,
    #             str(clip_script),
    #             "--input-dir",
    #             str(shp_clean),
    #             "--clip",
    #             str(ratio_mask),
    #             "--out-dir",
    #             str(clipped_ratio),
    #         ]
    #         run_cmd(cmd_clip_ratio, args.dry_run, "clip_ratio", results)
    # else:
    #     print("\n[STEP] clip_vectors")
    #     print("Skipping FC-based clipping – timeseries_source='sr'.")

    # ----------------------------------------------------------------------
    # 13. Step 7: Clip cleaned polygons to FC coverage (strict / ratio) if available
    # ----------------------------------------------------------------------
    # Purpose:
    #   FC coverage (Step 12) can produce “consistent coverage” polygons that define
    #   where the time-series baseline is reliably present (i.e. not dominated by no-data).
    #
    # This step clips the cleaned clearing polygons (Step 11) to those coverage extents:
    #   - Strict coverage polygon: areas consistently observed (most conservative)
    #   - Ratio coverage polygon: areas meeting a configurable presence ratio (less strict)
    #
    # This is only applicable in FC mode, because the coverage products are derived
    # from FC baseline stacks.

    clip_script = Path(__file__).resolve().parent / "easi_clip_vectors.py"

    # Prepare results container for this step (even if we skip)
    results.setdefault("outputs", {}).setdefault("clip_vectors", {})
    results["outputs"]["clip_vectors"].update({
        "script": str(clip_script),
        "timeseries_source": args.timeseries_source,
        "input_dir": str(shp_clean),          # cleaned polygons from Step 11
        "coverage_dir": str(fc_cov_dir),      # coverage products from Step 12
        "dry_run": bool(args.dry_run),
        "strict": {"attempted": False, "skipped": False},
        "ratio":  {"attempted": False, "skipped": False},
    })

    if args.timeseries_source == "fc":

        # ------------------------------------------------------------------
        # Strict coverage clip (most conservative)
        # ------------------------------------------------------------------
        strict_shp = fc_cov_dir / f"{scene}_fc_consistent.shp"
        results["outputs"]["clip_vectors"]["strict"]["clip_layer"] = str(strict_shp)

        if strict_shp.exists():
            clipped_strict = (
                compat_dir
                / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_strict"
            )
            clipped_strict.mkdir(parents=True, exist_ok=True)

            cmd_clip_strict = [
                pyexe,
                str(clip_script),
                "--input-dir", str(shp_clean),
                "--clip", str(strict_shp),
                "--out-dir", str(clipped_strict),
            ]

            results["outputs"]["clip_vectors"]["strict"].update({
                "attempted": True,
                "out_dir": str(clipped_strict),
                "cmd": list(map(str, cmd_clip_strict)),  # optional but great for provenance
            })

            run_cmd(cmd_clip_strict, args.dry_run, "clip_strict", results)

            # Record produced files (if not dry-run)
            if not args.dry_run:
                exts = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".gpkg"}
                files = sorted(
                    str(p) for p in clipped_strict.rglob("*")
                    if p.suffix.lower() in exts
                )
                results["outputs"]["clip_vectors"]["strict"]["files"] = files
            else:
                results["outputs"]["clip_vectors"]["strict"]["files"] = []

        else:
            # Strict layer not found → record as skipped so it’s obvious in JSON
            results["outputs"]["clip_vectors"]["strict"].update({
                "skipped": True,
                "reason": "Strict coverage shapefile not found",
            })

        # ------------------------------------------------------------------
        # Ratio coverage clip (presence ratio-based)
        # ------------------------------------------------------------------
        ratio_shp = fc_cov_dir / f"{scene}_fc_consistent_mask.shp"
        results["outputs"]["clip_vectors"]["ratio"]["clip_layer"] = str(ratio_shp)

        if ratio_shp.exists():
            clipped_ratio = (
                compat_dir
                / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_ratio"
            )
            clipped_ratio.mkdir(parents=True, exist_ok=True)

            cmd_clip_ratio = [
                pyexe,
                str(clip_script),
                "--input-dir", str(shp_clean),
                "--clip", str(ratio_shp),
                "--out-dir", str(clipped_ratio),
            ]

            results["outputs"]["clip_vectors"]["ratio"].update({
                "attempted": True,
                "out_dir": str(clipped_ratio),
                "cmd": list(map(str, cmd_clip_ratio)),
            })

            run_cmd(cmd_clip_ratio, args.dry_run, "clip_ratio", results)

            # Record produced files (if not dry-run)
            if not args.dry_run:
                exts = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".gpkg"}
                files = sorted(
                    str(p) for p in clipped_ratio.rglob("*")
                    if p.suffix.lower() in exts
                )
                results["outputs"]["clip_vectors"]["ratio"]["files"] = files
            else:
                results["outputs"]["clip_vectors"]["ratio"]["files"] = []

        else:
            results["outputs"]["clip_vectors"]["ratio"].update({
                "skipped": True,
                "reason": "Ratio coverage shapefile not found",
            })

    else:
        # SR/NDVI mode: no FC coverage polygons exist to clip against
        print("\n[STEP] clip_vectors")
        print("Skipping FC-based clipping – timeseries_source!='fc'.")

        results["outputs"]["clip_vectors"].update({
            "skipped": True,
            "reason": "FC-based clipping only applies when timeseries_source='fc'",
        })

    # Write manifest after Step 13 so clipped outputs/skips are recorded
    write_manifest(" (after clip_vectors)")

    # # ----------------------------------------------------------------------
    # # 14. Step 8: Optional packaging to ZIP
    # # ----------------------------------------------------------------------
    # # This step bundles everything under compat_dir into a single ZIP file
    # # (one per scene/date range) for easier transfer or archiving.
    # if args.package_dest:
    #     pkg_script = Path(__file__).resolve().parent / "easi_package_eds_outputs.py"
    #     cmd_pkg = [
    #         pyexe,
    #         str(pkg_script),
    #         "--compat-dir",
    #         str(compat_dir),
    #         "--scene",
    #         scene,
    #         "--start-date",
    #         eff_start,
    #         "--end-date",
    #         eff_end,
    #         "--dest-dir",
    #         args.package_dest,
    #     ]
    #     run_cmd(cmd_pkg, args.dry_run, "package_outputs", results)


    # ----------------------------------------------------------------------
    # 14. Step 8: Optional packaging to ZIP
    # ----------------------------------------------------------------------
    # Purpose:
    #   Bundle all outputs produced under compat_dir into a single ZIP archive.
    #   This is useful for:
    #     - transferring results off-system
    #     - archiving a complete EDS run
    #     - handing outputs to downstream systems or users
    #
    # The ZIP is created per scene + date range and includes:
    #   - compat products (db8 / dc4)
    #   - DLL / DLJ rasters
    #   - styled outputs
    #   - polygonised + cleaned vectors
    #   - coverage and clipped products (if present)

    results.setdefault("outputs", {}).setdefault("package_outputs", {})

    if args.package_dest:
        pkg_script = Path(__file__).resolve().parent / "easi_package_eds_outputs.py"

        # Expected ZIP filename (used for provenance; actual script determines final name)
        expected_zip = Path(args.package_dest) / f"{scene}_d{eff_start}_{eff_end}.zip"

        # Build packaging command
        cmd_pkg = [
            pyexe,                       # Python executable
            str(pkg_script),             # Packaging script
            "--compat-dir", str(compat_dir),
            "--scene", scene,
            "--start-date", eff_start,
            "--end-date", eff_end,
            "--dest-dir", args.package_dest,
        ]

        # Record intent + parameters BEFORE execution
        results["outputs"]["package_outputs"].update({
            "script": str(pkg_script),
            "compat_dir": str(compat_dir),
            "scene": scene,
            "start_date": eff_start,
            "end_date": eff_end,
            "dest_dir": str(args.package_dest),
            "expected_zip": str(expected_zip),
            "dry_run": bool(args.dry_run),
            "attempted": True,
        })

        # Execute packaging step
        # - In --dry-run mode, ZIP is not created
        # - Execution details recorded in results["steps"]
        run_cmd(cmd_pkg, args.dry_run, "package_outputs", results)

        # Record produced ZIP (if not dry-run)
        if not args.dry_run and expected_zip.exists():
            results["outputs"]["package_outputs"].update({
                "created": True,
                "zip_file": str(expected_zip),
            })
        else:
            results["outputs"]["package_outputs"].update({
                "created": False,
                "zip_file": str(expected_zip),
            })

    else:
        # Packaging not requested → explicitly record skip
        results["outputs"]["package_outputs"].update({
            "skipped": True,
            "reason": "No --package-dest provided",
            "attempted": False,
        })

    # Write manifest after packaging so final artefact is recorded
    write_manifest(" (after package_outputs)")


    # ----------------------------------------------------------------------
    # 15. Final summary
    # ----------------------------------------------------------------------
    results["outputs"] = {
        "dll": str(dll),
        "dlj": str(dlj),
        "threshold_polygons_dir": str(shp_base),
        "clean_polygons_dir": str(shp_clean),
        "fc_coverage_dir": str(fc_cov_dir),
    }


    print("\n=== EDS MASTER PIPELINE COMPLETE ===")
    print(json.dumps(results, indent=2))

    # Optional: collect per-run JSON logs into summary JSON/CSV under out-root/reports
    if args.collect_logs:
        try:
            pyexe = args.python_exe or sys.executable
            reports_dir = Path(args.out_root) / "reports"
            collector = Path(__file__).resolve().parent / "easi_collect_run_logs.py"
            cmd_collect = [
                pyexe,
                str(collector),
                "--root",
                str(Path(args.out_root)),
                "--out",
                str(reports_dir),
            ]
            run_cmd(cmd_collect, args.dry_run, "collect_run_logs", results)
        except Exception as e:
            print(f"[WARN] Log collection failed: {e}")


if __name__ == "__main__":
    main()

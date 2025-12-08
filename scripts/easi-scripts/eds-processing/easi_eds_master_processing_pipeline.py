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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_THRESHOLDS = [34, 35, 36, 37, 38, 39]


# def run_cmd(cmd: List[str], dry_run: bool, step: str, results: dict) -> None:
#     """Execute a subprocess command, with optional dry-run and JSON-serializable logging.

#     We capture only the tail of stdout/stderr (last 4000 chars) to keep the results
#     dictionary compact while still providing useful context for debugging.
#     """
#     print(f"\n[STEP] {step}")
#     print("Command:", " ".join(cmd))
#     if dry_run:
#         print("(dry-run) Skipped execution")
#         return
#     t0 = time.time()
#     proc = subprocess.run(cmd, capture_output=True, text=True)
#     dt = time.time() - t0
#     results.setdefault('steps', []).append({
#         'step': step,
#         'command': cmd,
#         'returncode': proc.returncode,
#         'duration_sec': dt,
#         'stdout': proc.stdout[-4000:],
#         'stderr': proc.stderr[-4000:],
#     })
#     if proc.returncode != 0:
#         print(proc.stdout)
#         print(proc.stderr)
#         raise SystemExit(f"Step failed: {step}")
#     else:
#         print(f"Completed in {dt:.1f}s")


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
    proc = subprocess.run(cmd, capture_output=True, text=True)

    # Calculate how many seconds the command took.
    dt = time.time() - t0

    # Make sure there is a 'steps' list in the results dict, then append a summary
    # of this step. This structure is easy to convert to JSON later.
    results.setdefault('steps', []).append({
        'step': step,                    # name of this pipeline step
        'command': cmd,                  # full command we ran
        'returncode': proc.returncode,   # 0 means success, anything else = error
        'duration_sec': dt,              # how long it took, in seconds

        # We only keep the *last* 4000 characters of stdout/stderr.
        # This keeps the log manageable but still shows recent messages.
        'stdout': proc.stdout[-4000:],
        'stderr': proc.stderr[-4000:],
    })

    # If the command failed (non-zero return code), show all its output
    # on the screen and stop the whole pipeline with a clear error.
    if proc.returncode != 0:
        print(proc.stdout)
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
    if '_' not in tile or len(tile) != 7:
        raise ValueError("Tile must be PPP_RRR e.g. '094_076'")

    # Split "PPP_RRR" into:
    #   p = "PPP" (path)
    #   r = "RRR" (row)
    p, r = tile.split('_')

    # Build and return the scene code "pPPPrRRR".
    return f"p{p}r{r}"


# def _resolve_sr_input(
#     hint: str,
#     date_tag: str,
#     tile: str,
#     sr_root: str | None,
#     fc_root: str | None,
#     sr_only_clr: bool = False,
# ) -> Tuple[str, str]:
#     """Resolve SR composite input and date for a given tile/date.

#     EASI layout example:
#         /home/jovyan/scratch/eds/tiles/p104r072/sr/2020/202006/ls89sr_p104r072_20200611_nbart6m3.tif

#     We therefore need to search for scene 'pPPPrRRR' under `sr_root` and look in `sr/YYYY/YYYMM`.
#     """
#     import glob, re
#     from datetime import datetime as _dt

#     # Tile e.g. "104_072" -> p="104", r="072", scene="p104r072"
#     if '_' not in tile:
#         raise ValueError("Tile must be PPP_RRR e.g. 104_072")
#     p, r = tile.split('_')
#     scene = f"p{p}r{r}".lower()

#     def extract_date_from_name(name: str) -> str | None:
#         m = re.search(r"(19|20)\d{6}", name)
#         return m.group(0) if m else None

#     def pick_nearest(paths: List[str], target: str) -> Tuple[str, str]:
#         tgt = _dt.strptime(target, "%Y%m%d").date()
#         best = None
#         best_key = None
#         for pth in paths:
#             d = extract_date_from_name(Path(pth).name)
#             if not d:
#                 continue
#             dd = _dt.strptime(d, "%Y%m%d").date()
#             key = (abs((dd - tgt).days), -int(d))
#             if best_key is None or key < best_key:
#                 best_key = key
#                 best = (pth, d)
#         if best:
#             return best
#         # Fallback: just use first and pretend date_tag
#         return paths[0], (extract_date_from_name(Path(paths[0]).name) or target)

#     # Patterns for EASI + legacy SR
#     if sr_only_clr:
#         exact_patterns = [
#             f"*{date_tag}*nbart6m*_clr.tif",
#             f"*{date_tag}*srb7_clr.tif",
#             f"*{date_tag}*srb6_clr.tif",
#         ]
#         any_patterns = [
#             "*nbart6m*_clr.tif",
#             "*srb7_clr.tif",
#             "*srb6_clr.tif",
#         ]
#     else:
#         exact_patterns = [
#             f"*{date_tag}*nbart6m*_clr.tif",
#             f"*{date_tag}*nbart6m*.tif",
#             f"*{date_tag}*srb7_clr.tif",
#             f"*{date_tag}*srb7.tif",
#             f"*{date_tag}*srb6_clr.tif",
#             f"*{date_tag}*srb6.tif",
#         ]
#         any_patterns = [
#             "*nbart6m*_clr.tif",
#             "*nbart6m*.tif",
#             "*srb7_clr.tif",
#             "*srb7.tif",
#             "*srb6_clr.tif",
#             "*srb6.tif",
#         ]

#     # 1) If `hint` is an existing file/dir, try there first
#     p_hint = Path(hint)
#     if p_hint.exists():
#         if p_hint.is_file():
#             d = extract_date_from_name(p_hint.name) or date_tag
#             return str(p_hint), d
#         # Directory: look directly inside this directory
#         exact = []
#         for pat in exact_patterns:
#             exact.extend(glob.glob(str(p_hint / pat)))
#         exact = [c for c in exact if scene in Path(c).name.lower()]
#         if exact:
#             return pick_nearest(exact, date_tag)

#         anyc = []
#         for pat in any_patterns:
#             anyc.extend(glob.glob(str(p_hint / pat)))
#         anyc = [c for c in anyc if scene in Path(c).name.lower()]
#         if anyc:
#             return pick_nearest(anyc, date_tag)

#     # 2) Search under roots using EASI layout
#     roots = [r for r in (sr_root, fc_root) if r]
#     yyyy, yyyymm = date_tag[:4], date_tag[:6]
#     cands: List[str] = []

#     for base in roots:
#         base = Path(base)
#         # EASI layout: tiles/p104r072/sr/2020/202006
#         easi_dir = base / scene / "sr" / yyyy / yyyymm
#         # Also allow slightly different layouts just in case:
#         underscore_dir = base / tile / "sr" / yyyy / yyyymm
#         split_dir = base / p / r / "sr" / yyyy / yyyymm

#         for ddir in (easi_dir, underscore_dir, split_dir):
#             for pat in exact_patterns:
#                 cands.extend(glob.glob(str(ddir / pat)))
#     cands = [c for c in cands if scene in Path(c).name.lower()]
#     if cands:
#         return pick_nearest(sorted(set(cands)), date_tag)

#     # Try any SR composite in those month folders
#     any_month: List[str] = []
#     for base in roots:
#         base = Path(base)
#         easi_dir = base / scene / "sr" / yyyy / yyyymm
#         underscore_dir = base / tile / "sr" / yyyy / yyyymm
#         split_dir = base / p / r / "sr" / yyyy / yyyymm
#         for ddir in (easi_dir, underscore_dir, split_dir):
#             for pat in any_patterns:
#                 any_month.extend(glob.glob(str(ddir / pat)))

#     any_month = [c for c in any_month if scene in Path(c).name.lower()]
#     if any_month:
#         return pick_nearest(sorted(set(any_month)), date_tag)

#     # 3) Broad recursive fallback under roots
#     broad: List[str] = []
#     for base in roots:
#         base = Path(base)
#         for pat in exact_patterns:
#             broad.extend(glob.glob(str(base / scene / "sr" / "**" / pat), recursive=True))
#         if broad:
#             break
#     broad = [c for c in broad if scene in Path(c).name.lower()]
#     if broad:
#         return pick_nearest(sorted(set(broad)), date_tag)

#     # Final fallback: any SR composite under scene/sr
#     any_all: List[str] = []
#     for base in roots:
#         base = Path(base)
#         for pat in any_patterns:
#             any_all.extend(glob.glob(str(base / scene / "sr" / "**" / pat), recursive=True))
#         if any_all:
#             break
#     any_all = [c for c in any_all if scene in Path(c).name.lower()]
#     if any_all:
#         return pick_nearest(sorted(set(any_all)), date_tag)

#     # If all strategies failed, abort with a helpful message
#     raise SystemExit(
#         "\n".join([
#             f"[ERR] Could not resolve SR input for {tile} date {date_tag}.",
#             " Hint: provide --sr-dir-start/--sr-dir-end as either a directory with bands or an *_nbart6m*.tif / *_srb7.tif path.",
#             f" Searched roots: {roots or 'N/A'}"
#         ])
#     )

# from pathlib import Path
# from typing import List, Tuple

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
    if '_' not in tile:
        raise ValueError("Tile must be PPP_RRR e.g. 104_072")
    p, r = tile.split('_')

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
        best = None      # (path, date_str)
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
        easi_dir      = base / scene / "sr" / yyyy / yyyymm
        underscore_dir = base / tile  / "sr" / yyyy / yyyymm
        split_dir      = base / p / r / "sr" / yyyy / yyyymm

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
        easi_dir      = base / scene / "sr" / yyyy / yyyymm
        underscore_dir = base / tile  / "sr" / yyyy / yyyymm
        split_dir      = base / p / r / "sr" / yyyy / yyyymm

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
            broad.extend(glob.glob(str(base / scene / "sr" / "**" / pat), recursive=True))
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
            any_all.extend(glob.glob(str(base / scene / "sr" / "**" / pat), recursive=True))
        if any_all:
            break  # stop when we get some hits from a root

    any_all = [c for c in any_all if scene in Path(c).name.lower()]
    if any_all:
        return pick_nearest(sorted(set(any_all)), date_tag)

    # ----------------------------------------
    # 7. If everything failed: stop with a clear error message
    # ----------------------------------------
    raise SystemExit(
        "\n".join([
            f"[ERR] Could not resolve SR input for {tile} date {date_tag}.",
            " Hint: provide --sr-dir-start/--sr-dir-end as either:",
            "   - a directory containing SR bands, or",
            "   - a direct *_nbart6m*.tif / *_srb7.tif path.",
            f" Searched roots: {roots or 'N/A'}",
        ])
    )


# def main():
#     # Parse arguments for the orchestration. We keep defaults conservative
#     # and expose knobs that map onto the individual called scripts.
#     ap = argparse.ArgumentParser(description="EDS master processing pipeline")
#     ap.add_argument('--tile', required=True)
#     ap.add_argument('--start-date', required=True, help='YYYYMMDD start')
#     ap.add_argument('--end-date', required=True, help='YYYYMMDD end')
#     ap.add_argument('--span-years', type=int, default=2, help='Years of FC baseline to look back')
#     ap.add_argument('--sr-dir-start', required=False, help='Directory or composite file for start SR date (contains *_B2*.tif etc. OR *_srb6/7.tif)')
#     ap.add_argument('--sr-dir-end', required=False, help='Directory or composite file for end SR date')
#     ap.add_argument('--sr-root', required=False, help='Root of SR storage (informational)')
#     ap.add_argument('--fc-root', required=False, help='Root of FC storage (informational)')
#     ap.add_argument('--fc-glob', help='Override glob for FC inputs (recursive patterns allowed)')
#     ap.add_argument('--out-root', default='data/compat/files', help='Base output root')
#     ap.add_argument('--season-window', nargs=2, metavar=('MMDD_START','MMDD_END'))
#     ap.add_argument('--thresholds', nargs='*', type=int, default=DEFAULT_THRESHOLDS)
#     ap.add_argument('--min-ha', type=float, default=1.0)
#     ap.add_argument('--skinny-pixels', type=int, default=3)
#     ap.add_argument('--ratio-presence', nargs='*', type=float)
#     ap.add_argument('--dry-run', action='store_true')
#     ap.add_argument('--omit-fpc-start-threshold', action='store_true')
#     ap.add_argument('--lookback-cap', type=int, default=10)
#     ap.add_argument('--save-per-input-masks', action='store_true')
#     ap.add_argument('--fc-only-clr', action='store_true', help='Forward to compat builder: use only *_fc3ms_clr.tif')
#     ap.add_argument('--sr-only-clr', action='store_true', help='Restrict SR composites to *_nbart6m*_clr.tif or *_srb?_clr.tif where available')
#     ap.add_argument('--fc-prefer-clr', action='store_true', help='Forward prefer-clr behaviour (otherwise default prefer)')
#     # FC->FPC conversion passthrough to compat builder
#     ap.add_argument('--fc-convert-to-fpc', action='store_true', help='Convert FC green to FPC in compat build (dc4) using FPC=100*(1-exp(-k*FC^n))')
#     ap.add_argument('--fc-k', type=float, default=0.000435, help='k parameter for FC->FPC conversion (default 0.000435)')
#     ap.add_argument('--fc-n', type=float, default=1.909, help='n parameter for FC->FPC conversion (default 1.909)')
#     ap.add_argument('--fc-nodata', type=float, help='Override nodata value for FC inputs; defaults to band nodata if present')
#     ap.add_argument('--python-exe', help='Override Python executable for subprocess steps (use GDAL-enabled env)')
#     ap.add_argument('--force-compat', action='store_true', help='Force rebuilding compat products even if db8/dc4 already exist')
#     ap.add_argument('--package-dest', help='If set, zip scene outputs to this directory at the end')

#     args = ap.parse_args()

#     # Convert PPP_RRR to scene code used in filenames (pPPPrRRR)
#     scene = derive_scene(args.tile)
#     compat_dir = Path(args.out_root) / scene
#     compat_dir.mkdir(parents=True, exist_ok=True)

#     # FC input patterns: support both underscore and split directory layouts.
#     # By default we search recursively for legacy *fc3ms*.tif and new EASI *fcm*.tif
#     # (or only *_clr variants if requested).
#     fc_patterns: List[str] = []
#     if args.fc_glob:
#         fc_patterns.append(args.fc_glob)
#     else:
#         base_root = args.fc_root or ''
#         # EASI layout: /tiles/p104r072/fc/...
#         scene_dir = os.path.join(base_root, scene, "fc")
#         # Legacy-ish layouts (if you ever have them)
#         underscore_dir = os.path.join(base_root, args.tile, "fc")              # /tiles/104_072/fc
#         split_dir = os.path.join(base_root, args.tile.replace("_", "/"), "fc") # /tiles/104/072/fc

#         legacy_pattern = "*fc3ms_clr.tif" if args.fc_only_clr else "*fc3ms*.tif"
#         easi_pattern = "*fcm*_clr.tif" if args.fc_only_clr else "*fcm*.tif"

#         for base in (scene_dir, underscore_dir, split_dir):
#             for pat in (legacy_pattern, easi_pattern):
#                 fc_patterns.append(os.path.join(base, "**", pat))

#     # De-duplicate while preserving order
#     seen_fc = set()
#     fc_patterns = [p for p in fc_patterns if not (p in seen_fc or seen_fc.add(p))]
#     print(f"[DEBUG] fc_patterns: {fc_patterns}")

#     # Resolve SR inputs (composite file or directory). If exact dates are missing,
#     # we determine effective start/end by nearest available composites.
#     hint_start = args.sr_dir_start or (args.sr_root or args.fc_root or '.')
#     hint_end = args.sr_dir_end or (args.sr_root or args.fc_root or '.')

#     sr_start_path, eff_start = _resolve_sr_input(
#         hint_start,
#         args.start_date,
#         args.tile,
#         args.sr_root,
#         args.fc_root,
#         sr_only_clr=args.sr_only_clr,
#     )
#     sr_end_path, eff_end = _resolve_sr_input(
#         hint_end,
#         args.end_date,
#         args.tile,
#         args.sr_root,
#         args.fc_root,
#         sr_only_clr=args.sr_only_clr,
#     )

#     # ---- NEW: compute seasonal window for FC baseline (±2 months either side) ----
#     from datetime import datetime
#     import calendar

#     def _shift_months(dt: datetime, delta_months: int) -> datetime:
#         """Shift a date by +/- delta_months, clamping the day to the valid range."""
#         month_index = dt.year * 12 + (dt.month - 1) + delta_months
#         year = month_index // 12
#         month = month_index % 12 + 1
#         last_day = calendar.monthrange(year, month)[1]
#         day = min(dt.day, last_day)
#         print(f"[DEGUG] shift months- {year}-{month}-{day}")
#         return datetime(year, month, day)

#     if args.season_window:
#         # If user explicitly gave a window, honour it
#         win_start, win_end = args.season_window
#         print(f"[DEBUG] - explicet seasonal window win start: {win_end} win end: {win_end}")
#     else:
#         # Otherwise use effective SR dates and expand ±2 months
#         sd_dt = datetime.strptime(eff_start, "%Y%m%d")
#         ed_dt = datetime.strptime(eff_end, "%Y%m%d")
#         ws_dt = _shift_months(sd_dt, -2)  # 2 months before start
#         we_dt = _shift_months(ed_dt, +2)  # 2 months after end
#         win_start = f"{ws_dt.month:02d}{ws_dt.day:02d}"
#         win_end   = f"{we_dt.month:02d}{we_dt.day:02d}"
#         print(f"[DEBUG] - default 2 months seasonality win start: {win_start}, and win end {win_end}")

#     # Legacy FC lookback years (still capped)
#     lookback = min(args.span_years, args.lookback_cap)
#     print(f"[DEBUG] lookback: {lookback}")



#     results = {
#         'tile': args.tile,
#         'scene': scene,
#         'requested_start_date': args.start_date,
#         'requested_end_date': args.end_date,
#         'effective_start_date': eff_start,
#         'effective_end_date': eff_end,
#         'window_start': win_start,
#         'window_end': win_end,
#         'span_years': args.span_years,
#         'lookback_used': lookback,
#         'outputs': {}
#     }

#     # 1. Compat build (skip if products already present unless forced)
#     pyexe = args.python_exe or sys.executable
#     db8_start_expected = compat_dir / f"lztmre_{scene}_{eff_start}_db8mz.img"
#     db8_end_expected = compat_dir / f"lztmre_{scene}_{eff_end}_db8mz.img"
#     import glob as _glob
#     dc4_existing = _glob.glob(str(compat_dir / f"lztmre_{scene}_*_dc4mz.img"))
#     need_compat = args.force_compat or (not db8_start_expected.exists() or not db8_end_expected.exists() or len(dc4_existing) < 2)
#     if need_compat:
#         # Build db8 (SR stacks) for start/end and dc4 (FPC) timeseries from FC inputs
#         # cmd_compat = [pyexe, 'scripts/slats_compat_builder.py', '--tile', scene,
#         #               '--sr-dir', sr_start_path, '--sr-dir', sr_end_path,
#         #               '--sr-date', eff_start, '--sr-date', eff_end]

#         # Path to new EASI compat builder in the same folder as this script
#         compat_script = Path(__file__).resolve().parent / "easi_slats_compat_builder.py"

#         cmd_compat = [
#             pyexe,
#             str(compat_script),
#             "--tile",
#             scene,
#             "--out-root",
#             str(compat_dir.parent),  # e.g. /home/jovyan/scratch/eds/compat
#             "--sr-dir",
#             sr_start_path,
#             "--sr-dir",
#             sr_end_path,
#             "--sr-date",
#             eff_start,
#             "--sr-date",
#             eff_end,
#         ]

#         for pat in fc_patterns:
#             cmd_compat.extend(['--fc', pat])
#         if args.fc_only_clr:
#             cmd_compat.append('--fc-only-clr')
#         if args.fc_prefer_clr:
#             cmd_compat.append('--fc-prefer-clr')
#         # Optional FC->FPC conversion flags
#         if args.fc_convert_to_fpc:
#             cmd_compat.append('--fc-convert-to-fpc')
#             cmd_compat.extend(['--fc-k', str(args.fc_k), '--fc-n', str(args.fc_n)])
#             if args.fc_nodata is not None:
#                 cmd_compat.extend(['--fc-nodata', str(args.fc_nodata)])
#         run_cmd(cmd_compat, args.dry_run, 'build_compat', results)
#     else:
#         print("\n[STEP] build_compat")
#         print("Existing compat products detected; skipping build (use --force-compat to rebuild)")

#     db8_start = compat_dir / f"lztmre_{scene}_{eff_start}_db8mz.img"
#     db8_end = compat_dir / f"lztmre_{scene}_{eff_end}_db8mz.img"
#     if not db8_start.exists():
#         db8_start = Path(f"lztmre_{scene}_{eff_start}_db8mz.img")
#     if not db8_end.exists():
#         db8_end = Path(f"lztmre_{scene}_{eff_end}_db8mz.img")

#     # 2. Legacy method: seasonal baseline + spectral indices -> DLL/DLJ rasters
#     dc4_glob = str(compat_dir / f"lztmre_{scene}_*_dc4mz.img")
#     # cmd_legacy = [pyexe, 'scripts/easi_eds_legacy_method_window.py', '--scene', scene,
#     #               '--start-date', eff_start, '--end-date', eff_end,
#     #               '--window-start', win_start, '--window-end', win_end,
#     #               '--lookback', str(lookback), '--start-db8', str(db8_start), '--end-db8', str(db8_end),
#     #               '--dc4-glob', dc4_glob, '--verbose']

#     # Path to legacy method script in the same folder as this pipeline
#     legacy_script = Path(__file__).resolve().parent / "easi_eds_legacy_method_window.py"

#     cmd_legacy = [
#         pyexe,
#         str(legacy_script),
#         '--scene', scene,
#         '--start-date', eff_start,
#         '--end-date', eff_end,
#         '--window-start', win_start,
#         '--window-end', win_end,
#         '--lookback', str(lookback),
#         '--start-db8', str(db8_start),
#         '--end-db8', str(db8_end),
#         '--dc4-glob', dc4_glob,
#         '--verbose',
#     ]

#     if args.omit_fpc_start_threshold:
#         cmd_legacy.append('--omit-fpc-start-threshold')
#     run_cmd(cmd_legacy, args.dry_run, 'legacy_method', results)

#     dll = compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img"
#     dlj = compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img"
#     if not dll.exists():
#         dll = Path(f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img")
#     if not dlj.exists():
#         dlj = Path(f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img")


#     # 3. Style: apply palette to DLL and band names to DLJ
#     # Use the esis_style_dll_dlj.py that lives alongside this pipeline script
#     style_script = Path(__file__).resolve().parent / "easi_style_dll_dlj.py"

#     cmd_style = [
#         pyexe,
#         str(style_script),
#         "--dll", str(dll),
#         "--dlj", str(dlj),
#     ]
#     run_cmd(cmd_style, args.dry_run, "style_outputs", results)


#     # 4. Polygonize thresholds: build merged polygons for classes ≥ thresholds (34..39)
#     shp_base = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha"
#     shp_base.mkdir(parents=True, exist_ok=True)

#     poly_script = Path(__file__).resolve().parent / "easi_polygonize_merged_thresholds.py"

#     cmd_poly = [
#         pyexe,
#         str(poly_script),
#         '--dll', str(dll),
#         '--out-dir', str(shp_base),
#         '--min-ha', str(args.min_ha),
#         '--thresholds',
#         *[str(t) for t in args.thresholds],
#     ]
#     run_cmd(cmd_poly, args.dry_run, 'polygonize_thresholds', results)


#     # 5. Post-process vectors: dissolve + remove skinny artifacts
#     shp_clean = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean"

#     post_script = Path(__file__).resolve().parent / "easi_vector_postprocess.py"

#     cmd_post = [
#         pyexe,
#         str(post_script),
#         "--input-dir", str(shp_base),
#         "--out-dir", str(shp_clean),
#         "--dissolve",
#         "--skinny-pixels", str(args.skinny_pixels),
#         "--from-raster", str(dll),
#     ]
#     run_cmd(cmd_post, args.dry_run, "vector_postprocess", results)



#     # 6. FC coverage: union footprint + presence ratio masks over dc4 stack
#     fc_cov_dir = compat_dir / 'fc_coverage'
#     fc_cov_dir.mkdir(parents=True, exist_ok=True)

#     cov_script = Path(__file__).resolve().parent / "easi_fc_coverage_extent.py"

#     cmd_cov = [
#         pyexe,
#         str(cov_script),
#         "--fc-dir", str(compat_dir),
#         "--scene", scene,
#         "--pattern", "*_dc4mz.img",
#         "--out-dir", str(fc_cov_dir),
#     ]

#     if args.ratio_presence:
#         cmd_cov.append("--ratios")
#         cmd_cov.extend(str(r) for r in args.ratio_presence)

#     if args.save_per_input_masks:
#         cmd_cov.append("--save-per-input-masks")

#     run_cmd(cmd_cov, args.dry_run, "fc_coverage", results)



#     # 7. Clip strict/ratio if available: clip to strict or ratio presence footprints
#     clip_script = Path(__file__).resolve().parent / "easi_clip_vectors.py"

#     strict_shp = fc_cov_dir / f"{scene}_fc_consistent.shp"
#     if strict_shp.exists():
#         clipped_strict = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_strict"
#         clipped_strict.mkdir(parents=True, exist_ok=True)
#         cmd_clip_strict = [
#             pyexe,
#             str(clip_script),
#             "--input-dir", str(shp_clean),
#             "--clip", str(strict_shp),
#             "--out-dir", str(clipped_strict),
#         ]
#         run_cmd(cmd_clip_strict, args.dry_run, "clip_strict", results)

#     ratio_mask = fc_cov_dir / f"{scene}_fc_consistent_mask.shp"  # see note below
#     if ratio_mask.exists():
#         clipped_ratio = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_ratio"
#         clipped_ratio.mkdir(parents=True, exist_ok=True)
#         cmd_clip_ratio = [
#             pyexe,
#             str(clip_script),
#             "--input-dir", str(shp_clean),
#             "--clip", str(ratio_mask),
#             "--out-dir", str(clipped_ratio),
#         ]
#         run_cmd(cmd_clip_ratio, args.dry_run, "clip_ratio", results)

#     # 8. Optional: package outputs to a ZIP in a working directory
#     if args.package_dest:
#         pkg_script = Path(__file__).resolve().parent / "easi_package_eds_outputs.py"
#         cmd_pkg = [
#             pyexe,
#             str(pkg_script),
#             "--compat-dir", str(compat_dir),
#             "--scene", scene,
#             "--start-date", eff_start,
#             "--end-date", eff_end,
#             "--dest-dir", args.package_dest,
#         ]
#         run_cmd(cmd_pkg, args.dry_run, "package_outputs", results)



#     results['outputs'] = {
#         'dll': str(dll),
#         'dlj': str(dlj),
#         'threshold_polygons_dir': str(shp_base),
#         'clean_polygons_dir': str(shp_clean),
#         'fc_coverage_dir': str(fc_cov_dir)
#     }

#     print("\n=== EDS MASTER PIPELINE COMPLETE ===")
#     print(json.dumps(results, indent=2))


# if __name__ == '__main__':
#     main()


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
    ap.add_argument('--tile', required=True)
    ap.add_argument('--start-date', required=True, help='YYYYMMDD start')
    ap.add_argument('--end-date', required=True, help='YYYYMMDD end')
    ap.add_argument(
        '--span-years',
        type=int,
        default=2,
        help='Years of FC baseline to look back'
    )
    ap.add_argument(
        '--sr-dir-start',
        required=False,
        help='Directory or composite file for start SR date '
             '(contains *_B2*.tif etc. OR *_srb6/7.tif)'
    )
    ap.add_argument(
        '--sr-dir-end',
        required=False,
        help='Directory or composite file for end SR date'
    )
    ap.add_argument(
        '--sr-root',
        required=False,
        help='Root of SR storage (informational)'
    )
    ap.add_argument(
        '--fc-root',
        required=False,
        help='Root of FC storage (informational)'
    )
    ap.add_argument(
        '--fc-glob',
        help='Override glob for FC inputs (recursive patterns allowed)'
    )
    ap.add_argument(
        '--out-root',
        default='data/compat/files',
        help='Base output root'
    )
    ap.add_argument(
        '--season-window',
        nargs=2,
        metavar=('MMDD_START', 'MMDD_END'),
        help='Override seasonal window for baseline (MMDD MMDD)'
    )
    ap.add_argument(
        '--thresholds',
        nargs='*',
        type=int,
        default=DEFAULT_THRESHOLDS
    )
    ap.add_argument(
        '--min-ha',
        type=float,
        default=1.0,
        help='Minimum polygon size in hectares'
    )
    ap.add_argument(
        '--skinny-pixels',
        type=int,
        default=3,
        help='Remove “skinny” artefacts narrower than this many pixels'
    )
    ap.add_argument(
        '--ratio-presence',
        nargs='*',
        type=float,
        help='Optional FC presence ratios for coverage masks'
    )
    ap.add_argument(
        '--dry-run',
        action='store_true',
        help='Print commands but do not actually run them'
    )
    ap.add_argument(
        '--omit-fpc-start-threshold',
        action='store_true',
        help='Disable fpcStart<108 => no-clearing rule in legacy method'
    )
    ap.add_argument(
        '--lookback-cap',
        type=int,
        default=10,
        help='Maximum years to look back for FC baseline'
    )
    ap.add_argument(
        '--save-per-input-masks',
        action='store_true',
        help='In FC coverage step, save individual input masks as well'
    )
    ap.add_argument(
        '--fc-only-clr',
        action='store_true',
        help='Forward to compat builder: use only *_fc3ms_clr.tif'
    )
    ap.add_argument(
        '--sr-only-clr',
        action='store_true',
        help='Restrict SR composites to *_nbart6m*_clr.tif or *_srb?_clr.tif where available'
    )
    ap.add_argument(
        '--fc-prefer-clr',
        action='store_true',
        help='Forward prefer-clr behaviour (otherwise default prefer)'
    )

    # FC→FPC conversion controls (used when compat builder needs to derive FPC from FC)
    ap.add_argument(
        '--fc-convert-to-fpc',
        action='store_true',
        help='Convert FC green to FPC in compat build (dc4) using '
             'FPC=100*(1-exp(-k*FC^n))'
    )
    ap.add_argument(
        '--fc-k',
        type=float,
        default=0.000435,
        help='k parameter for FC->FPC conversion (default 0.000435)'
    )
    ap.add_argument(
        '--fc-n',
        type=float,
        default=1.909,
        help='n parameter for FC->FPC conversion (default 1.909)'
    )
    ap.add_argument(
        '--fc-nodata',
        type=float,
        help='Override nodata value for FC inputs; '
             'defaults to band nodata if present'
    )

    # Runtime environment and packaging options
    ap.add_argument(
        '--python-exe',
        help='Override Python executable for subprocess steps '
             '(use GDAL-enabled env)'
    )
    ap.add_argument(
        '--force-compat',
        action='store_true',
        help='Force rebuilding compat products even if db8/dc4 already exist'
    )
    ap.add_argument(
        '--package-dest',
        help='If set, zip scene outputs to this directory at the end'
    )

    args = ap.parse_args()

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
    # 3. Build FC input patterns (for compat builder)
    # ----------------------------------------------------------------------
    # We want to support different directory layouts and both legacy and
    # newer FC naming schemes in one go. This block builds a list of glob
    # patterns that the compat builder script will use to find FC inputs.
    fc_patterns: List[str] = []
    if args.fc_glob:
        # If the user gave an explicit glob, just use that as-is.
        fc_patterns.append(args.fc_glob)
    else:
        base_root = args.fc_root or ''

        # EASI layout:   <fc_root>/p104r072/fc/...
        scene_dir = os.path.join(base_root, scene, "fc")

        # Legacy-ish layouts (if present in some environments):
        #   <fc_root>/104_072/fc
        underscore_dir = os.path.join(base_root, args.tile, "fc")
        #   <fc_root>/104/072/fc
        split_dir = os.path.join(base_root, args.tile.replace("_", "/"), "fc")

        # Legacy “fc3ms” format vs newer “fcm” format
        legacy_pattern = "*fc3ms_clr.tif" if args.fc_only_clr else "*fc3ms*.tif"
        easi_pattern   = "*fcm*_clr.tif"  if args.fc_only_clr else "*fcm*.tif"

        for base in (scene_dir, underscore_dir, split_dir):
            for pat in (legacy_pattern, easi_pattern):
                fc_patterns.append(os.path.join(base, "**", pat))

    # De-duplicate patterns while preserving order so logs stay readable.
    seen_fc = set()
    fc_patterns = [p for p in fc_patterns if not (p in seen_fc or seen_fc.add(p))]
    print(f"[DEBUG] fc_patterns: {fc_patterns}")

    # ----------------------------------------------------------------------
    # 4. Resolve SR inputs (start and end composites)
    # ----------------------------------------------------------------------
    # We may be given a direct path (file or directory), or just a root.
    # _resolve_sr_input encapsulates the “find nearest composite by date”
    # logic and returns both the chosen path and its effective date.
    hint_start = args.sr_dir_start or (args.sr_root or args.fc_root or '.')
    hint_end   = args.sr_dir_end   or (args.sr_root or args.fc_root or '.')

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

    # ----------------------------------------------------------------------
    # 5. Derive seasonal window (MMDD range) for FC baseline
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
        month_index = dt.year * 12 + (dt.month - 1) + delta_months
        year = month_index // 12
        month = month_index % 12 + 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(dt.day, last_day)
        print(f"[DEGUG] shift months- {year}-{month}-{day}")
        return datetime(year, month, day)

    if args.season_window:
        # User explicitly specified MMDD_START, MMDD_END → honour it.
        win_start, win_end = args.season_window
        print(f"[DEBUG] - explicet seasonal window win start: {win_end} win end: {win_end}")
    else:
        # Otherwise, build a default window around the effective SR dates:
        #   - 2 months before effective start
        #   - 2 months after effective end
        sd_dt = datetime.strptime(eff_start, "%Y%m%d")
        ed_dt = datetime.strptime(eff_end, "%Y%m%d")
        ws_dt = _shift_months(sd_dt, -2)  # 2 months before start
        we_dt = _shift_months(ed_dt, +2)  # 2 months after end
        win_start = f"{ws_dt.month:02d}{ws_dt.day:02d}"
        win_end   = f"{we_dt.month:02d}{we_dt.day:02d}"
        print(f"[DEBUG] - default 2 months seasonality win start: {win_start}, and win end {win_end}")

    # Legacy FC lookback years (bounded by lookback_cap)
    lookback = min(args.span_years, args.lookback_cap)
    print(f"[DEBUG] lookback: {lookback}")

    # ----------------------------------------------------------------------
    # 6. Initialise results log (JSON-friendly)
    # ----------------------------------------------------------------------
    # We keep a structured record of what the pipeline did, including:
    #   - requested vs effective dates
    #   - seasonal window used
    #   - which steps ran and how long they took
    results = {
        'tile': args.tile,
        'scene': scene,
        'requested_start_date': args.start_date,
        'requested_end_date': args.end_date,
        'effective_start_date': eff_start,
        'effective_end_date': eff_end,
        'window_start': win_start,
        'window_end': win_end,
        'span_years': args.span_years,
        'lookback_used': lookback,
        'outputs': {}
    }

    # ----------------------------------------------------------------------
    # 7. Step 1: Build compat products (db8 & dc4) if needed
    # ----------------------------------------------------------------------
    pyexe = args.python_exe or sys.executable

    # Expected db8 locations under compat directory
    db8_start_expected = compat_dir / f"lztmre_{scene}_{eff_start}_db8mz.img"
    db8_end_expected   = compat_dir / f"lztmre_{scene}_{eff_end}_db8mz.img"

    import glob as _glob
    dc4_existing = _glob.glob(str(compat_dir / f"lztmre_{scene}_*_dc4mz.img"))

    # Decide whether we need to (re)build compat products
    need_compat = (
        args.force_compat
        or (not db8_start_expected.exists()
            or not db8_end_expected.exists()
            or len(dc4_existing) < 2)
    )

    if need_compat:
        # Build db8 (start & end SR stacks) and dc4 (FPC time-series) from FC inputs.

        # Path to the new EASI compat builder (sits alongside this script).
        compat_script = Path(__file__).resolve().parent / "easi_slats_compat_builder.py"

        cmd_compat = [
            pyexe,
            str(compat_script),
            "--tile", scene,
            "--out-root", str(compat_dir.parent),  # e.g. /home/jovyan/scratch/eds/compat
            "--sr-dir", sr_start_path,
            "--sr-dir", sr_end_path,
            "--sr-date", eff_start,
            "--sr-date", eff_end,
        ]

        # Add FC patterns as multiple --fc arguments
        for pat in fc_patterns:
            cmd_compat.extend(['--fc', pat])

        # Optional flags to control FC input selection
        if args.fc_only_clr:
            cmd_compat.append('--fc-only-clr')
        if args.fc_prefer_clr:
            cmd_compat.append('--fc-prefer-clr')

        # Optional FC→FPC conversion flags (used when dc4 needs to be derived)
        if args.fc_convert_to_fpc:
            cmd_compat.append('--fc-convert-to-fpc')
            cmd_compat.extend(['--fc-k', str(args.fc_k), '--fc-n', str(args.fc_n)])
            if args.fc_nodata is not None:
                cmd_compat.extend(['--fc-nodata', str(args.fc_nodata)])

        run_cmd(cmd_compat, args.dry_run, 'build_compat', results)

    else:
        # If compat products are already in place and not forcibly rebuilt.
        print("\n[STEP] build_compat")
        print("Existing compat products detected; skipping build (use --force-compat to rebuild)")

    # Confirm final db8 locations (fall back to current directory if needed)
    db8_start = compat_dir / f"lztmre_{scene}_{eff_start}_db8mz.img"
    db8_end   = compat_dir / f"lztmre_{scene}_{eff_end}_db8mz.img"
    if not db8_start.exists():
        db8_start = Path(f"lztmre_{scene}_{eff_start}_db8mz.img")
    if not db8_end.exists():
        db8_end = Path(f"lztmre_{scene}_{eff_end}_db8mz.img")

    # ----------------------------------------------------------------------
    # 8. Step 2: Legacy change detection (DLL/DLJ)
    # ----------------------------------------------------------------------
    # Combine db8 (start/end) and dc4 (FPC stack) into clearing
    # classification (DLL) and interpretation (DLJ) rasters.
    dc4_glob = str(compat_dir / f"lztmre_{scene}_*_dc4mz.img")

    # Path to legacy method script (lives next to this pipeline).
    legacy_script = Path(__file__).resolve().parent / "easi_eds_legacy_method_window.py"

    cmd_legacy = [
        pyexe,
        str(legacy_script),
        '--scene', scene,
        '--start-date', eff_start,
        '--end-date', eff_end,
        '--window-start', win_start,
        '--window-end', win_end,
        '--lookback', str(lookback),
        '--start-db8', str(db8_start),
        '--end-db8', str(db8_end),
        '--dc4-glob', dc4_glob,
        '--verbose',
    ]
    if args.omit_fpc_start_threshold:
        cmd_legacy.append('--omit-fpc-start-threshold')

    run_cmd(cmd_legacy, args.dry_run, 'legacy_method', results)

    # Expected DLL/DLJ outputs
    dll = compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img"
    dlj = compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img"
    if not dll.exists():
        dll = Path(f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img")
    if not dlj.exists():
        dlj = Path(f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img")

    # ----------------------------------------------------------------------
    # 9. Step 3: Style outputs (apply palette & band names)
    # ----------------------------------------------------------------------
    # This makes the rasters easier to interpret visually in GIS tools.
    style_script = Path(__file__).resolve().parent / "easi_style_dll_dlj.py"

    cmd_style = [
        pyexe,
        str(style_script),
        "--dll", str(dll),
        "--dlj", str(dlj),
    ]
    run_cmd(cmd_style, args.dry_run, "style_outputs", results)

    # ----------------------------------------------------------------------
    # 10. Step 4: Polygonise clearing thresholds
    # ----------------------------------------------------------------------
    # Convert clearing classes (≥ thresholds, usually 34..39) into polygons.
    shp_base = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha"
    shp_base.mkdir(parents=True, exist_ok=True)

    poly_script = Path(__file__).resolve().parent / "easi_polygonize_merged_thresholds.py"

    cmd_poly = [
        pyexe,
        str(poly_script),
        '--dll', str(dll),
        '--out-dir', str(shp_base),
        '--min-ha', str(args.min_ha),
        '--thresholds',
        *[str(t) for t in args.thresholds],
    ]
    run_cmd(cmd_poly, args.dry_run, 'polygonize_thresholds', results)

    # ----------------------------------------------------------------------
    # 11. Step 5: Vector post-processing (clean up polygons)
    # ----------------------------------------------------------------------
    # Dissolve overlapping polygons and remove narrow “spaghetti” artefacts.
    shp_clean = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean"

    post_script = Path(__file__).resolve().parent / "easi_vector_postprocess.py"

    cmd_post = [
        pyexe,
        str(post_script),
        "--input-dir", str(shp_base),
        "--out-dir", str(shp_clean),
        "--dissolve",
        "--skinny-pixels", str(args.skinny_pixels),
        "--from-raster", str(dll),
    ]
    run_cmd(cmd_post, args.dry_run, "vector_postprocess", results)

    # ----------------------------------------------------------------------
    # 12. Step 6: FC coverage masks (extent / ratio presence)
    # ----------------------------------------------------------------------
    fc_cov_dir = compat_dir / 'fc_coverage'
    fc_cov_dir.mkdir(parents=True, exist_ok=True)

    cov_script = Path(__file__).resolve().parent / "easi_fc_coverage_extent.py"

    cmd_cov = [
        pyexe,
        str(cov_script),
        "--fc-dir", str(compat_dir),
        "--scene", scene,
        "--pattern", "*_dc4mz.img",
        "--out-dir", str(fc_cov_dir),
    ]
    if args.ratio_presence:
        cmd_cov.append("--ratios")
        cmd_cov.extend(str(r) for r in args.ratio_presence)
    if args.save_per_input_masks:
        cmd_cov.append("--save-per-input-masks")

    run_cmd(cmd_cov, args.dry_run, "fc_coverage", results)

    # ----------------------------------------------------------------------
    # 13. Step 7: Clip polygons to strict / ratio coverage (if available)
    # ----------------------------------------------------------------------
    clip_script = Path(__file__).resolve().parent / "easi_clip_vectors.py"

    # Strict coverage polygon
    strict_shp = fc_cov_dir / f"{scene}_fc_consistent.shp"
    if strict_shp.exists():
        clipped_strict = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_strict"
        clipped_strict.mkdir(parents=True, exist_ok=True)
        cmd_clip_strict = [
            pyexe,
            str(clip_script),
            "--input-dir", str(shp_clean),
            "--clip", str(strict_shp),
            "--out-dir", str(clipped_strict),
        ]
        run_cmd(cmd_clip_strict, args.dry_run, "clip_strict", results)

    # Ratio coverage polygon/mask
    ratio_mask = fc_cov_dir / f"{scene}_fc_consistent_mask.shp"
    if ratio_mask.exists():
        clipped_ratio = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_ratio"
        clipped_ratio.mkdir(parents=True, exist_ok=True)
        cmd_clip_ratio = [
            pyexe,
            str(clip_script),
            "--input-dir", str(shp_clean),
            "--clip", str(ratio_mask),
            "--out-dir", str(clipped_ratio),
        ]
        run_cmd(cmd_clip_ratio, args.dry_run, "clip_ratio", results)

    # ----------------------------------------------------------------------
    # 14. Step 8: Optional packaging to ZIP
    # ----------------------------------------------------------------------
    # This step bundles everything under compat_dir into a single ZIP file
    # (one per scene/date range) for easier transfer or archiving.
    if args.package_dest:
        pkg_script = Path(__file__).resolve().parent / "easi_package_eds_outputs.py"
        cmd_pkg = [
            pyexe,
            str(pkg_script),
            "--compat-dir", str(compat_dir),
            "--scene", scene,
            "--start-date", eff_start,
            "--end-date", eff_end,
            "--dest-dir", args.package_dest,
        ]
        run_cmd(cmd_pkg, args.dry_run, "package_outputs", results)

    # ----------------------------------------------------------------------
    # 15. Final summary
    # ----------------------------------------------------------------------
    results['outputs'] = {
        'dll': str(dll),
        'dlj': str(dlj),
        'threshold_polygons_dir': str(shp_base),
        'clean_polygons_dir': str(shp_clean),
        'fc_coverage_dir': str(fc_cov_dir),
    }

    print("\n=== EDS MASTER PIPELINE COMPLETE ===")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()

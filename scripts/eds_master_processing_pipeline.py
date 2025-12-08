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
    2. Legacy seasonal change method -> eds_legacy_method_window.py
    3. Style dll/dlj -> style_dll_dlj.py
    4. Polygonize merged thresholds -> polygonize_merged_thresholds.py
    5. Post-process (dissolve + skinny filter) -> vector_postprocess.py
    6. FC coverage + masks -> fc_coverage_extent.py
    7. Clip cleaned polygons (strict + ratio masks) -> clip_vectors.py

Key additions:
    - --sr-dir-start / --sr-dir-end: required explicit SR band directories or composite file paths.
    - --fc-only-clr / --fc-prefer-clr: propagate to compat builder for FC selection logic.
    - --span-years: sets legacy lookback (capped by --lookback-cap).
    - --fc-glob: optional override for FC input pattern (defaults to *fc3ms*.tif recursive under fc-root).
    - --python-exe: enforce running subprocesses in a GDAL-enabled interpreter (recommended on Windows).

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


def run_cmd(cmd: List[str], dry_run: bool, step: str, results: dict) -> None:
    """Execute a subprocess command, with optional dry-run and JSON-serializable logging.

    We capture only the tail of stdout/stderr (last 4000 chars) to keep the results
    dictionary compact while still providing useful context for debugging.
    """
    print(f"\n[STEP] {step}")
    print("Command:", " ".join(cmd))
    if dry_run:
        print("(dry-run) Skipped execution")
        return
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    results.setdefault("steps", []).append(
        {
            "step": step,
            "command": cmd,
            "returncode": proc.returncode,
            "duration_sec": dt,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit(f"Step failed: {step}")
    else:
        print(f"Completed in {dt:.1f}s")


def derive_scene(tile: str) -> str:
    """Convert a PPP_RRR tile (e.g., 094_076) to scene code (e.g., p094r076)."""
    if "_" not in tile or len(tile) != 7:
        raise ValueError("Tile must be PPP_RRR e.g. 094_076")
    p, r = tile.split("_")
    return f"p{p}r{r}"


def _resolve_sr_input(
    hint: str, date_tag: str, tile: str, sr_root: str | None, fc_root: str | None
) -> Tuple[str, str]:
    """Resolve SR composite input and date.

    Accepts a direct path to a composite (e.g., *_srb7.tif) or a directory containing
    per-band files. If the provided hint is ambiguous or missing, searches typical
    SR roots in both underscore (094_076) and split (094/076) layouts.

    Returns (resolved_path, effective_date). If the exact YYYYMMDD composite is not
    found, chooses the nearest by absolute day difference (ties broken toward newer).
    """
    import glob, re
    from datetime import datetime as _dt

    tile_tag = tile.replace("_", "").lower()

    def extract_date_from_name(name: str) -> str | None:
        m = re.search(r"(19|20)\d{6}", name)
        return m.group(0) if m else None

    def pick_nearest(paths: List[str], target: str) -> Tuple[str, str]:
        tgt = _dt.strptime(target, "%Y%m%d").date()
        best = None
        best_key = None
        for p in paths:
            d = extract_date_from_name(Path(p).name)
            if not d:
                continue
            dd = _dt.strptime(d, "%Y%m%d").date()
            key = (abs((dd - tgt).days), -int(d))
            if best_key is None or key < best_key:
                best_key = key
                best = (p, d)
        if best:
            return best
        return paths[0], (extract_date_from_name(Path(paths[0]).name) or target)

    # 1) Direct check: the hint may be a real file (composite) or a directory
    p_hint = Path(hint)
    if p_hint.exists():
        if p_hint.is_file():
            d = extract_date_from_name(p_hint.name) or date_tag
            return str(p_hint), d
        # Directory: prefer exact date composite; else any composite in that folder
        exact = []
        for pat in (f"*{date_tag}*srb7.tif", f"*{date_tag}*srb6.tif"):
            exact.extend(glob.glob(str(p_hint / pat)))
        exact = [c for c in exact if tile_tag in Path(c).name.lower()]
        if exact:
            return pick_nearest(exact, date_tag)
        anyc = []
        for pat in ("*srb7.tif", "*srb6.tif"):
            anyc.extend(glob.glob(str(p_hint / pat)))
        anyc = [c for c in anyc if tile_tag in Path(c).name.lower()]
        if anyc:
            return pick_nearest(anyc, date_tag)

    # 2) Roots search: look under SR/FC roots in underscore and split layouts
    roots = [r for r in (sr_root, fc_root) if r]
    yyyy, yyyymm = date_tag[:4], date_tag[:6]
    cands: List[str] = []
    for base in roots:
        udir = Path(base) / tile / yyyy / yyyymm
        p, r = tile.split("_")
        sdir = Path(base) / p / r / yyyy / yyyymm
        for ddir in (udir, sdir):
            for pat in (f"*{date_tag}*srb7.tif", f"*{date_tag}*srb6.tif"):
                cands.extend(glob.glob(str(ddir / pat)))
    cands = [c for c in cands if tile_tag in Path(c).name.lower()]
    if cands:
        return pick_nearest(sorted(set(cands)), date_tag)
    # Try any composite in those month folders
    any_month: List[str] = []
    for base in roots:
        udir = Path(base) / tile / yyyy / yyyymm
        p, r = tile.split("_")
        sdir = Path(base) / p / r / yyyy / yyyymm
        for ddir in (udir, sdir):
            for pat in ("*srb7.tif", "*srb6.tif"):
                any_month.extend(glob.glob(str(ddir / pat)))
    any_month = [c for c in any_month if tile_tag in Path(c).name.lower()]
    if any_month:
        return pick_nearest(sorted(set(any_month)), date_tag)

    # 3) Broad recursive search under roots (fallback)
    broad: List[str] = []
    for base in roots:
        for pat in (f"**/*{date_tag}*srb7.tif", f"**/*{date_tag}*srb6.tif"):
            broad.extend(glob.glob(str(Path(base) / pat), recursive=True))
        if broad:
            break
    broad = [c for c in broad if tile_tag in Path(c).name.lower()]
    if broad:
        return pick_nearest(sorted(set(broad)), date_tag)
    # If still nothing, search any composites for this tile under roots and pick nearest
    any_all: List[str] = []
    for base in roots:
        for pat in ("**/*srb7.tif", "**/*srb6.tif"):
            any_all.extend(glob.glob(str(Path(base) / pat), recursive=True))
        if any_all:
            break
    any_all = [c for c in any_all if tile_tag in Path(c).name.lower()]
    if any_all:
        return pick_nearest(sorted(set(any_all)), date_tag)

    # If all strategies failed, abort with a helpful message
    raise SystemExit(
        "\n".join(
            [
                f"[ERR] Could not resolve SR input for {tile} date {date_tag}.",
                " Hint: provide --sr-dir-start/--sr-dir-end as either a directory with bands or an *_srb7.tif path.",
                f" Searched roots: {roots or 'N/A'}",
            ]
        )
    )


def main():
    # Parse arguments for the orchestration. We keep defaults conservative
    # and expose knobs that map onto the individual called scripts.
    ap = argparse.ArgumentParser(description="EDS master processing pipeline")
    ap.add_argument("--tile", required=True)
    ap.add_argument("--start-date", required=True, help="YYYYMMDD start")
    ap.add_argument("--end-date", required=True, help="YYYYMMDD end")
    ap.add_argument(
        "--span-years", type=int, default=2, help="Years of FC baseline to look back"
    )
    ap.add_argument(
        "--sr-dir-start",
        required=True,
        help="Directory or composite file for start SR date (contains *_B2*.tif etc. OR *_srb6/7.tif)",
    )
    ap.add_argument(
        "--sr-dir-end",
        required=True,
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
    ap.add_argument("--season-window", nargs=2, metavar=("MMDD_START", "MMDD_END"))
    ap.add_argument("--thresholds", nargs="*", type=int, default=DEFAULT_THRESHOLDS)
    ap.add_argument("--min-ha", type=float, default=1.0)
    ap.add_argument("--skinny-pixels", type=int, default=3)
    ap.add_argument("--ratio-presence", nargs="*", type=float)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--omit-fpc-start-threshold", action="store_true")
    ap.add_argument("--lookback-cap", type=int, default=10)
    ap.add_argument("--save-per-input-masks", action="store_true")
    ap.add_argument(
        "--fc-only-clr",
        action="store_true",
        help="Forward to compat builder: use only *_fc3ms_clr.tif",
    )
    ap.add_argument(
        "--fc-prefer-clr",
        action="store_true",
        help="Forward prefer-clr behaviour (otherwise default prefer)",
    )
    # FC->FPC conversion passthrough to compat builder
    ap.add_argument(
        "--fc-convert-to-fpc",
        action="store_true",
        help="Convert FC green to FPC in compat build (dc4) using FPC=100*(1-exp(-k*FC^n))",
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
        help="Override nodata value for FC inputs; defaults to band nodata if present",
    )
    ap.add_argument(
        "--python-exe",
        help="Override Python executable for subprocess steps (use GDAL-enabled env)",
    )
    ap.add_argument(
        "--force-compat",
        action="store_true",
        help="Force rebuilding compat products even if db8/dc4 already exist",
    )
    args = ap.parse_args()

    # Convert PPP_RRR to scene code used in filenames (pPPPrRRR)
    scene = derive_scene(args.tile)
    compat_dir = Path(args.out_root) / scene
    compat_dir.mkdir(parents=True, exist_ok=True)

    win_start = args.season_window[0] if args.season_window else args.start_date[4:8]
    win_end = args.season_window[1] if args.season_window else args.end_date[4:8]
    lookback = min(args.span_years, args.lookback_cap)

    # FC input patterns: support both underscore and split directory layouts.
    # By default we search recursively for *fc3ms*.tif (or only *_clr if requested).
    fc_patterns: List[str] = []
    if args.fc_glob:
        fc_patterns.append(args.fc_glob)
    else:
        base_root = args.fc_root or ""
        underscore_dir = os.path.join(base_root, args.tile)  # e.g. D:\data\lsat\094_076
        split_dir = os.path.join(
            base_root, args.tile.replace("_", "/")
        )  # e.g. D:\data\lsat\094\076
        mask_pattern = "*fc3ms_clr.tif" if args.fc_only_clr else "*fc3ms*.tif"
        for base in (underscore_dir, split_dir):
            fc_patterns.append(os.path.join(base, "**", mask_pattern))
    # De-duplicate while preserving order
    seen_fc = set()
    fc_patterns = [p for p in fc_patterns if not (p in seen_fc or seen_fc.add(p))]

    # Resolve SR inputs (composite file or directory). If exact dates are missing,
    # we determine effective start/end by nearest available composites.
    sr_start_path, eff_start = _resolve_sr_input(
        args.sr_dir_start, args.start_date, args.tile, args.sr_root, args.fc_root
    )
    sr_end_path, eff_end = _resolve_sr_input(
        args.sr_dir_end, args.end_date, args.tile, args.sr_root, args.fc_root
    )

    results = {
        "tile": args.tile,
        "scene": scene,
        "requested_start_date": args.start_date,
        "requested_end_date": args.end_date,
        "effective_start_date": eff_start,
        "effective_end_date": eff_end,
        "window_start": win_start,
        "window_end": win_end,
        "span_years": args.span_years,
        "lookback_used": lookback,
        "outputs": {},
    }

    # 1. Compat build (skip if products already present unless forced)
    pyexe = args.python_exe or sys.executable
    db8_start_expected = compat_dir / f"lztmre_{scene}_{eff_start}_db8mz.img"
    db8_end_expected = compat_dir / f"lztmre_{scene}_{eff_end}_db8mz.img"
    import glob as _glob

    dc4_existing = _glob.glob(str(compat_dir / f"lztmre_{scene}_*_dc4mz.img"))
    need_compat = args.force_compat or (
        not db8_start_expected.exists()
        or not db8_end_expected.exists()
        or len(dc4_existing) < 2
    )
    if need_compat:
        # Build db8 (SR stacks) for start/end and dc4 (FPC) timeseries from FC inputs
        cmd_compat = [
            pyexe,
            "scripts/slats_compat_builder.py",
            "--tile",
            scene,
            "--sr-dir",
            sr_start_path,
            "--sr-dir",
            sr_end_path,
            "--sr-date",
            eff_start,
            "--sr-date",
            eff_end,
        ]
        for pat in fc_patterns:
            cmd_compat.extend(["--fc", pat])
        if args.fc_only_clr:
            cmd_compat.append("--fc-only-clr")
        if args.fc_prefer_clr:
            cmd_compat.append("--fc-prefer-clr")
        # Optional FC->FPC conversion flags
        if args.fc_convert_to_fpc:
            cmd_compat.append("--fc-convert-to-fpc")
            cmd_compat.extend(["--fc-k", str(args.fc_k), "--fc-n", str(args.fc_n)])
            if args.fc_nodata is not None:
                cmd_compat.extend(["--fc-nodata", str(args.fc_nodata)])
        run_cmd(cmd_compat, args.dry_run, "build_compat", results)
    else:
        print("\n[STEP] build_compat")
        print(
            "Existing compat products detected; skipping build (use --force-compat to rebuild)"
        )

    db8_start = compat_dir / f"lztmre_{scene}_{eff_start}_db8mz.img"
    db8_end = compat_dir / f"lztmre_{scene}_{eff_end}_db8mz.img"
    if not db8_start.exists():
        db8_start = Path(f"lztmre_{scene}_{eff_start}_db8mz.img")
    if not db8_end.exists():
        db8_end = Path(f"lztmre_{scene}_{eff_end}_db8mz.img")

    # 2. Legacy method: seasonal baseline + spectral indices -> DLL/DLJ rasters
    dc4_glob = str(compat_dir / f"lztmre_{scene}_*_dc4mz.img")
    cmd_legacy = [
        pyexe,
        "scripts/eds_legacy_method_window.py",
        "--scene",
        scene,
        "--start-date",
        eff_start,
        "--end-date",
        eff_end,
        "--window-start",
        win_start,
        "--window-end",
        win_end,
        "--lookback",
        str(lookback),
        "--start-db8",
        str(db8_start),
        "--end-db8",
        str(db8_end),
        "--dc4-glob",
        dc4_glob,
        "--verbose",
    ]
    if args.omit_fpc_start_threshold:
        cmd_legacy.append("--omit-fpc-start-threshold")
    run_cmd(cmd_legacy, args.dry_run, "legacy_method", results)

    dll = compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img"
    dlj = compat_dir / f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img"
    if not dll.exists():
        dll = Path(f"lztmre_{scene}_d{eff_start}{eff_end}_dllmz.img")
    if not dlj.exists():
        dlj = Path(f"lztmre_{scene}_d{eff_start}{eff_end}_dljmz.img")

    # 3. Style: apply palette to DLL and band names to DLJ
    cmd_style = [
        pyexe,
        "scripts/style_dll_dlj.py",
        "--dll",
        str(dll),
        "--dlj",
        str(dlj),
    ]
    run_cmd(cmd_style, args.dry_run, "style_outputs", results)

    # 4. Polygonize thresholds: build merged polygons for classes ≥ thresholds (34..39)
    shp_base = compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha"
    shp_base.mkdir(parents=True, exist_ok=True)
    cmd_poly = [
        pyexe,
        "scripts/polygonize_merged_thresholds.py",
        "--dll",
        str(dll),
        "--out-dir",
        str(shp_base),
        "--min-ha",
        str(args.min_ha),
        "--thresholds",
    ] + [str(t) for t in args.thresholds]
    run_cmd(cmd_poly, args.dry_run, "polygonize_thresholds", results)

    # 5. Post-process vectors: dissolve + remove skinny artifacts
    shp_clean = (
        compat_dir / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean"
    )
    cmd_post = [
        pyexe,
        "scripts/vector_postprocess.py",
        "--input-dir",
        str(shp_base),
        "--out-dir",
        str(shp_clean),
        "--dissolve",
        "--skinny-pixels",
        str(args.skinny_pixels),
        "--from-raster",
        str(dll),
    ]
    run_cmd(cmd_post, args.dry_run, "vector_postprocess", results)

    # 6. FC coverage: union footprint + presence ratio masks over dc4 stack
    fc_cov_dir = compat_dir / "fc_coverage"
    fc_cov_dir.mkdir(parents=True, exist_ok=True)
    cmd_cov = [
        pyexe,
        "scripts/fc_coverage_extent.py",
        "--fc-dir",
        str(compat_dir),
        "--scene",
        scene,
        "--pattern",
        "*_dc4mz.img",
        "--out-dir",
        str(fc_cov_dir),
    ]
    if args.ratio_presence:
        for r in args.ratio_presence:
            cmd_cov.extend(["--min-presence-ratio", str(r)])
    if args.save_per_input_masks:
        cmd_cov.append("--save-per-input-masks")
    run_cmd(cmd_cov, args.dry_run, "fc_coverage", results)

    # 7. Clip strict/ratio if available: clip to strict or ratio presence footprints
    strict_shp = fc_cov_dir / f"{scene}_fc_consistent.shp"
    if strict_shp.exists():
        clipped_strict = (
            compat_dir
            / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_strict"
        )
        clipped_strict.mkdir(parents=True, exist_ok=True)
        cmd_clip_strict = [
            pyexe,
            "scripts/clip_vectors.py",
            "--input-dir",
            str(shp_clean),
            "--clip",
            str(strict_shp),
            "--out-dir",
            str(clipped_strict),
        ]
        run_cmd(cmd_clip_strict, args.dry_run, "clip_strict", results)
    ratio_mask = fc_cov_dir / f"{scene}_fc_consistent_mask.shp"
    if ratio_mask.exists():
        clipped_ratio = (
            compat_dir
            / f"shp_d{eff_start}_{eff_end}_merged_min{int(args.min_ha)}ha_clean_clip_ratio"
        )
        clipped_ratio.mkdir(parents=True, exist_ok=True)
        cmd_clip_ratio = [
            pyexe,
            "scripts/clip_vectors.py",
            "--input-dir",
            str(shp_clean),
            "--clip",
            str(ratio_mask),
            "--out-dir",
            str(clipped_ratio),
        ]
        run_cmd(cmd_clip_ratio, args.dry_run, "clip_ratio", results)

    results["outputs"] = {
        "dll": str(dll),
        "dlj": str(dlj),
        "threshold_polygons_dir": str(shp_base),
        "clean_polygons_dir": str(shp_clean),
        "fc_coverage_dir": str(fc_cov_dir),
    }

    print("\n=== EDS MASTER PIPELINE COMPLETE ===")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

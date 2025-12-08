#!/usr/bin/env python
"""
collect_eds_tiles_for_download.py

Collect a number of .tif files (and their ancillary files) from your local
scratch EDS tiles directory, bundle them into a ZIP file, and write that ZIP
into your working drive so you can download it from Jupyter.

Defaults (adjust if needed):

- Source root (where the tiles are):
    ~/scratch/eds/tiles

- Working drive output directory:
    ~/work-easi-eds/downloads

Usage examples
--------------

# Collect 10 latest .tif files for a specific tile and zip them:
python collect_eds_tiles_for_download.py \
    --tile-id p104r070 \
    --number 10

# Collect 20 .tif files from ALL tiles:
python collect_eds_tiles_for_download.py \
    --number 20

# Specify a custom source root and output zip name:
python collect_eds_tiles_for_download.py \
    --source-root /home/jovyan/scratch/eds/tiles \
    --output-zip /home/jovyan/work-easi-eds/downloads/p104r070_sample.zip \
    --tile-id p104r070 \
    --number 15
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Tuple

import zipfile


def find_tif_files(
    source_root: Path,
    tile_id: str | None,
) -> List[Path]:
    """
    Find all .tif files under source_root.
    If tile_id is provided, restrict search to that tile directory.
    """
    if tile_id:
        search_root = source_root / tile_id
    else:
        search_root = source_root

    if not search_root.exists():
        print(f"[ZIP] WARNING: search root does not exist: {search_root}")
        return []

    # Recursive glob for .tif files
    tif_files = sorted(search_root.rglob("*.tif"))
    return tif_files


def select_files_by_mtime(
    tif_files: List[Path],
    number: int,
) -> List[Path]:
    """
    Select up to `number` .tif files, sorted by modification time (newest first).
    """
    if not tif_files:
        return []

    # Sort by mtime descending
    tif_with_mtime: List[Tuple[float, Path]] = [
        (f.stat().st_mtime, f) for f in tif_files
    ]
    tif_with_mtime.sort(key=lambda x: x[0], reverse=True)

    selected = [f for _, f in tif_with_mtime[:number]]
    return selected


def gather_ancillary_files(tif_path: Path) -> List[Path]:
    """
    Given a .tif file, find ancillary files in the same directory that share
    the same stem (basename without extension), e.g.:

        foo.tif
        foo.ovr
        foo.aux.xml
        foo_md5.txt   (if you use that pattern)

    Returns a list including the .tif itself and any matching sidecars.
    """
    dir_path = tif_path.parent
    stem = tif_path.stem  # "foo" from "foo.tif"

    # Match any file in the same directory that starts with the same stem.
    # This will include e.g. foo.tif, foo.ovr, foo.aux.xml, foo_md5.txt, etc.
    ancillary = []
    for p in dir_path.iterdir():
        if p.is_file() and p.name.startswith(stem):
            ancillary.append(p)

    # Ensure .tif is included even if pattern failed somehow
    if tif_path not in ancillary:
        ancillary.append(tif_path)

    return ancillary


def create_zip(
    source_root: Path,
    files: List[Path],
    output_zip: Path,
) -> None:
    """
    Create a ZIP file at output_zip containing `files`, stored with paths
    relative to `source_root` so the directory structure is preserved inside
    the archive.
    """
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    print(f"[ZIP] Creating ZIP: {output_zip}")
    with zipfile.ZipFile(output_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            try:
                rel_path = f.relative_to(source_root)
            except ValueError:
                # If file is outside source_root, just use its name
                rel_path = f.name

            print(f"[ZIP] Adding: {f} as {rel_path}")
            zf.write(f, arcname=str(rel_path))

    print("[ZIP] Done.")


def parse_args() -> argparse.Namespace:
    home = Path.home()

    default_source_root = home / "scratch" / "eds" / "tiles"
    default_output_dir = home / "work-easi-eds" / "downloads"
    default_output_zip = default_output_dir / "eds_tiles_sample.zip"

    parser = argparse.ArgumentParser(
        description=(
            "Collect N .tif files (plus ancillary files) from local EDS tiles "
            "and bundle them into a ZIP on your working drive."
        )
    )

    parser.add_argument(
        "--source-root",
        type=Path,
        default=default_source_root,
        help=f"Root directory containing tiles (default: {default_source_root})",
    )
    parser.add_argument(
        "--output-zip",
        type=Path,
        default=default_output_zip,
        help=f"Output ZIP path on working drive (default: {default_output_zip})",
    )
    parser.add_argument(
        "--tile-id",
        type=str,
        default=None,
        help="Optional tile ID (e.g. p104r070). If omitted, search all tiles.",
    )
    parser.add_argument(
        "--number",
        type=int,
        default=10,
        help="Number of .tif files to collect (default: 10).",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    source_root: Path = args.source_root
    output_zip: Path = args.output_zip
    tile_id: str | None = args.tile_id
    number: int = args.number

    print(f"[ZIP] Source root:   {source_root}")
    print(f"[ZIP] Tile ID:       {tile_id or '(ALL tiles)'}")
    print(f"[ZIP] Number of .tif: {number}")
    print(f"[ZIP] Output ZIP:    {output_zip}")
    print("")

    tif_files = find_tif_files(source_root, tile_id)
    if not tif_files:
        print("[ZIP] No .tif files found. Nothing to do.")
        return

    selected_tifs = select_files_by_mtime(tif_files, number)
    if not selected_tifs:
        print("[ZIP] No .tif files selected. Nothing to do.")
        return

    print(f"[ZIP] Found {len(tif_files)} .tif files, selected {len(selected_tifs)}:")
    for f in selected_tifs:
        print(f"       {f}")
    print("")

    # Gather ancillary files for each selected tif
    all_files: List[Path] = []
    seen: set[Path] = set()

    for tif in selected_tifs:
        anc = gather_ancillary_files(tif)
        for f in anc:
            if f not in seen:
                all_files.append(f)
                seen.add(f)

    print(f"[ZIP] Total files to add (including ancillaries): {len(all_files)}")
    create_zip(source_root, all_files, output_zip)


if __name__ == "__main__":
    main()

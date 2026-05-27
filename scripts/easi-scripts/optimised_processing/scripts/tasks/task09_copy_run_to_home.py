!/usr/bin/env python3

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


from __future__ import annotations

"""Task 09 (optional): copy key artefacts into a user-friendly folder.

Non-coder summary:
- Some environments (e.g. notebooks) have a convenient home folder like
    `/home/jovyan`.
- This task copies the most important run outputs (SR composites, DLL/DLJ COGs,
    masks, vectors) into `<home_out_dir>/<run_tag>/` so you can quickly download
    or inspect them.
- It can also zip the folder for easy transfer.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
import shutil
import zipfile

@dataclass(frozen=True)
class HomeCopyResult:
    dest_dir: Path
    copied: List[Path]


def _safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def _zip_directory(src_dir: Path, zip_path: Path, dry_run: bool = False) -> None:
    """Zip an entire directory preserving folder structure."""
    if dry_run:
        print(f"[DRY] ZIP {src_dir} -> {zip_path}")
        return

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in src_dir.rglob("*"):
            if file.is_file():
                # preserve relative folder structure
                zf.write(file, arcname=file.relative_to(src_dir))

    print(f"[OK] Created zip: {zip_path}")


def copy_run_to_home(
    *,
    run_tag: str,
    home_out_dir: Path,
    ga0_start_raw_local: Path | None = None,
    ga0_end_raw_local: Path | None = None,
    ga0_start_local: Path,
    ga0_end_local: Path,
    legacy_outputs: Iterable[Path],
    cog_outputs: Iterable[Path],
    mask_outputs: Iterable[Path],
    vector_dirs: Iterable[Path],
    zip_after: bool = False,
    dry_run: bool = False,
) -> HomeCopyResult:
    """Copy key outputs into a single run folder under `home_out_dir`."""
    home_out_dir = Path(home_out_dir)
    dest_dir = home_out_dir / run_tag

    copied: List[Path] = []

    def stage_file(p: Path, sub: str) -> None:
        nonlocal copied
        p = Path(p)

        if not p.exists():
            print(f"[WARN] Missing file, not copied: {p}")
            return

        dst = dest_dir / sub / p.name

        if dry_run:
            print(f"[DRY] COPY {p} -> {dst}")
            return

        _safe_copy(p, dst)
        copied.append(dst)

        # ---------------- DEBUG PRINT ----------------
        print(f"[COPY] {p}")
        print(f"       -> {dst}")

    # ga0
    if ga0_start_raw_local is not None:
        stage_file(Path(ga0_start_raw_local), "sr_ga0")
    if ga0_end_raw_local is not None:
        stage_file(Path(ga0_end_raw_local), "sr_ga0")
    stage_file(Path(ga0_start_local), "sr_ga0")
    stage_file(Path(ga0_end_local), "sr_ga0")

    # legacy .img/.hdr etc
    for p in legacy_outputs:
        stage_file(Path(p), "legacy_outputs")

    # cog outputs
    for p in cog_outputs:
        stage_file(Path(p), "cog_outputs")

    # masks
    for p in mask_outputs:
        stage_file(Path(p), "masks")

    # vectors (copy entire dir contents)
    for d in vector_dirs:
        d = Path(d)

        print(f"[DEBUG] Checking vector dir: {d}")

        if not d.exists():
            print(f"[WARN] Vector dir does not exist: {d}")
            continue

        files = sorted(d.glob("*"))
        print(f"[DEBUG] Found {len(files)} vector files in {d}")

        for f in files:
            if f.is_file():
                stage_file(f, "vectors")

    if not dry_run:
        print(f"[OK] Copied {len(copied)} files to: {dest_dir}")
        print("\n[SUMMARY] Files copied to home:")
        for f in copied:
            print(f"  {f}")
        print()

    if zip_after:
        zip_path = dest_dir.with_suffix(".zip")
        _zip_directory(dest_dir, zip_path, dry_run=dry_run)


    return HomeCopyResult(dest_dir=dest_dir, copied=copied)

#!/usr/bin/env python
"""
Package EDS compat outputs for a single scene into a ZIP archive and copy
the ZIP to a destination directory (e.g. your working drive).

Usage:

  python easi_package_eds_outputs.py \
    --compat-dir /home/jovyan/scratch/eds/compat/p104r072 \
    --scene p104r072 \
    --start-date 20200611 \
    --end-date 20220812 \
    --dest-dir /home/jovyan/work-easi-eds/exports
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from datetime import datetime


def make_zip_name(scene: str, start: str | None, end: str | None) -> str:
    if start and end:
        return f"{scene}_d{start}{end}_eds_outputs.zip"
    elif start:
        return f"{scene}_d{start}_eds_outputs.zip"
    else:
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        return f"{scene}_eds_outputs_{stamp}.zip"


def package_compat(
    compat_dir: Path, dest_dir: Path, scene: str, start: str | None, end: str | None
) -> Path:
    compat_dir = compat_dir.resolve()
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not compat_dir.exists():
        raise SystemExit(f"[ERR] Compat directory does not exist: {compat_dir}")

    # Collect files first, so we can report what we’re doing
    files = []
    total_bytes = 0
    for root, _, fnames in os.walk(compat_dir):
        root_path = Path(root)
        for fname in fnames:
            full = root_path / fname
            if full.is_file():
                files.append(full)
                total_bytes += full.stat().st_size

    print(
        f"[INFO] Packaging {len(files)} files "
        f"({total_bytes/1e9:.2f} GB) from {compat_dir}"
    )

    if not files:
        print("[WARN] No files found under compat dir – ZIP will be empty.")

    zip_name = make_zip_name(scene, start, end)
    zip_path = dest_dir / zip_name

    # Create ZIP – entries are relative to the scene directory
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, allowZip64=True) as zf:
        for full in files:
            # Arcname: scene-relative path, e.g. p104r072/...
            try:
                rel = full.relative_to(compat_dir.parent)
            except ValueError:
                # Fallback: just use filename
                rel = full.name
            zf.write(full, arcname=str(rel))

    print(f"[OK] Packaged outputs -> {zip_path}")
    return zip_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Package EDS compat outputs into a ZIP archive."
    )
    ap.add_argument(
        "--compat-dir",
        required=True,
        help="Scene compat directory (e.g. /home/jovyan/scratch/eds/compat/p104r072)",
    )
    ap.add_argument(
        "--scene",
        required=True,
        help="Scene code (e.g. p104r072) used in the ZIP filename",
    )
    ap.add_argument(
        "--start-date", help="Effective start date YYYYMMDD (for naming only)"
    )
    ap.add_argument("--end-date", help="Effective end date YYYYMMDD (for naming only)")
    ap.add_argument(
        "--dest-dir",
        required=True,
        help="Destination directory for the ZIP (e.g. your working drive)",
    )
    args = ap.parse_args(argv)

    compat_dir = Path(args.compat_dir)
    dest_dir = Path(args.dest_dir)
    package_compat(compat_dir, dest_dir, args.scene, args.start_date, args.end_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

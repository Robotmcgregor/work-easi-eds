#!/usr/bin/env python
"""
Inventory local Fractional Cover (FC) files under a root folder.

Matches files like:
- ga_ls_fc_<PPP_RRR>_<YYYYMMDD>_fc3ms.tif
- ga_ls_fc_<PPP_RRR>_<YYYYMMDD>_fc3ms_clr.tif

Writes a CSV with: tile, date, year, yearmonth, path, filename

Examples (PowerShell):
  # Scan a single tile
  python scripts\inventory_local_fc.py --root D:\data\lsat --tile 089_080 --csv data\local_fc_089_080.csv

  # Scan all tiles
  python scripts\inventory_local_fc.py --root D:\data\lsat --csv data\local_fc_all.csv
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List, Optional

RE_FC = re.compile(r"^ga_ls_fc_(?P<pr>\d{6})_(?P<ymd>\d{8})_fc3ms(?:_clr)?\.tif$", re.IGNORECASE)


def scan_local_fc(root: Path, only_tile: Optional[str] = None):
    rows = []
    # Normalise tile e.g. '089080' -> '089_080'
    want_tile = None
    if only_tile:
        t = only_tile.strip()
        want_tile = t if '_' in t else f"{t[:3]}_{t[3:]}"

    for dirpath, dirnames, filenames in os.walk(root):
        # if scanning a single tile, skip other top-level dirs
        if want_tile and Path(dirpath).parent == root and Path(dirpath).name != want_tile:
            continue
        for fn in filenames:
            m = RE_FC.match(fn)
            if not m:
                continue
            pr = m.group("pr")
            ymd = m.group("ymd")
            tile = f"{pr[:3]}_{pr[3:]}"
            if want_tile and tile != want_tile:
                continue
            full = str(Path(dirpath) / fn)
            rows.append({
                "tile": tile,
                "date": ymd,
                "year": ymd[:4],
                "yearmonth": ymd[:6],
                "path": full,
                "filename": fn,
            })
    # sort rows for stability
    rows.sort(key=lambda r: (r["tile"], r["date"], r["filename"]))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Inventory local FC files under a root directory")
    ap.add_argument("--root", required=True, help="Local root folder (e.g., D:\\data\\lsat)")
    ap.add_argument("--tile", help="Optional tile PPP_RRR or PPPRRR to restrict scan")
    ap.add_argument("--csv", required=True, help="Path to write CSV output")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"Root not found: {root}")

    rows = scan_local_fc(root, args.tile)

    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tile", "date", "year", "yearmonth", "path", "filename"]) 
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote local FC inventory: {out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

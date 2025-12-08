#!/usr/bin/env python
r"""
Seed the compatibility SQLite metadb with minimal entries so the QLD script runs unchanged.

This populates the landsat_list (and optionally slats_dates) tables for a given scene and dates.
You can provide explicit dates, or scan a local FC folder and filter by a seasonal window.

Examples (PowerShell):
  # Scan local FC for 089_080, months 07..10 over last 10 years ending 2025-10, and seed DB
    python scripts\compat_init_db.py --tile 089_080 --root D:\\data\\lsat \
    --start-yyyymm 202507 --end-yyyymm 202510 --span-years 10 \
        --write-timeseries-csv data\\timeseries_089_080.csv

  # Or pass explicit dates
    python scripts\compat_init_db.py --tile 089_080 --dates 20160715,20170803,20190922
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import List, Optional, Set
import sys

# Ensure repository root is on sys.path so 'rsc' package can be imported when running as a script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rsc.utils import metadb

RE_FC = re.compile(
    r"^ga_ls_fc_(?P<pr>\d{6})_(?P<ymd>\d{8})_fc3ms(?:_clr)?\.tif$", re.IGNORECASE
)


def _season_months(start_mm: int, end_mm: int) -> List[int]:
    if 1 <= start_mm <= 12 and 1 <= end_mm <= 12:
        if start_mm <= end_mm:
            return list(range(start_mm, end_mm + 1))
        return list(range(start_mm, 13)) + list(range(1, end_mm + 1))
    raise ValueError("Months must be in 1..12")


def _tile_norm(tile: str) -> str:
    t = tile.strip()
    return t if "_" in t else f"{t[:3]}_{t[3:]}"


def _scene_from_tile(tile: str) -> str:
    t = _tile_norm(tile)
    return f"p{t[:3]}r{t[4:]}"


def _scan_fc_dates(root: Path, tile: str) -> List[str]:
    want = _tile_norm(tile)
    dates: Set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        p = Path(dirpath)
        if p.parent == root and p.name != want:
            continue
        for fn in filenames:
            m = RE_FC.match(fn)
            if not m:
                continue
            pr = m.group("pr")
            if want != f"{pr[:3]}_{pr[3:]}":
                continue
            dates.add(m.group("ymd"))
    return sorted(dates)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Seed compat metadb with landsat_list for given dates"
    )
    ap.add_argument(
        "--tile", required=True, help="Tile PPP_RRR or PPPRRR (e.g., 089_080)"
    )
    ap.add_argument("--root", help="Local root to scan for FC (e.g., D:\\data\\lsat)")
    ap.add_argument("--dates", help="Comma-separated YYYYMMDD list to seed explicitly")
    ap.add_argument(
        "--start-yyyymm", help="Seasonal mode: start YYYYMM (months only considered)"
    )
    ap.add_argument(
        "--end-yyyymm", help="Seasonal mode: end YYYYMM (defines end year for span)"
    )
    ap.add_argument(
        "--span-years",
        type=int,
        default=10,
        help="Years back including end year (default 10)",
    )
    ap.add_argument(
        "--write-timeseries-csv",
        help="Optional CSV to write the final ordered timeseries dates",
    )
    ap.add_argument(
        "--allow-after-start",
        action="store_true",
        help="Allow timeseries dates after start date (non-standard but enables sparse runs)",
    )
    args = ap.parse_args(argv)

    scene = _scene_from_tile(args.tile)

    if args.dates:
        dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    else:
        if not (args.root and args.start_yyyymm and args.end_yyyymm):
            raise SystemExit(
                "Provide --dates OR (--root and --start-yyyymm and --end-yyyymm)"
            )
        root = Path(args.root)
        if not root.exists():
            raise SystemExit(f"Root not found: {root}")
        all_dates = _scan_fc_dates(root, args.tile)
        s_mon = int(args.start_yyyymm[4:])
        e_mon = int(args.end_yyyymm[4:])
        months = set(_season_months(s_mon, e_mon))
        e_year = int(args.end_yyyymm[:4])
        years = set(range(e_year - (args.span_years - 1), e_year + 1))
        dates = [d for d in all_dates if int(d[4:6]) in months and int(d[:4]) in years]
    if not dates:
        raise SystemExit("No dates selected to seed")

    con = metadb.connect()
    cur = con.cursor()
    # If we need synthetic pre-start dates ensure at least one prior date exists
    inserted = 0
    have_pre_start = any(d <= dates[0] for d in dates)
    for d in dates:
        cur.execute(
            "INSERT INTO landsat_list(scene, date, product, satellite, instrument) VALUES (?, ?, 're', ?, ?)",
            (scene, d, "lz", "tm"),
        )
        cur.execute(
            "INSERT INTO cloudamount(scene, date, pcntcloud) VALUES (?, ?, ?)",
            (scene, d, 0.0),
        )
        inserted += 1
    # If no date earlier than the first (start) date and not allowing after-start, inject a synthetic one 30 days prior
    if not have_pre_start and not args.allow_after_start:
        import datetime

        first = dates[0]
        dt = datetime.datetime.strptime(first, "%Y%m%d") - datetime.timedelta(days=30)
        synth = dt.strftime("%Y%m%d")
        cur.execute(
            "INSERT INTO landsat_list(scene, date, product, satellite, instrument) VALUES (?, ?, 're', ?, ?)",
            (scene, synth, "lz", "tm"),
        )
        cur.execute(
            "INSERT INTO cloudamount(scene, date, pcntcloud) VALUES (?, ?, ?)",
            (scene, synth, 0.0),
        )
        inserted += 1
        dates.insert(0, synth)
        print(
            f"[INFO] Added synthetic pre-start date {synth} for timeseries initialization"
        )
    con.commit()

    if args.write_timeseries_csv:
        out = Path(args.write_timeseries_csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            f.write("date\n")
            for d in dates:
                f.write(d + "\n")
        print(f"Wrote timeseries list: {out} ({len(dates)} dates)")

    print(f"Seeded landsat_list for scene {scene}: {inserted} date(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

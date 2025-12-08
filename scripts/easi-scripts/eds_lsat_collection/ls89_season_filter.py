#!/usr/bin/env python

"""
Filter a CSV (e.g. comparison_table.csv) by seasonal months,
with ±2 months padding and a 12-month cap.

Examples
--------
Core season: 202407 → 202410
  - core months: 7,8,9,10
  - padded: 5,6,(7,8,9,10),11,12  -> {5..12}

Core season: 202403 → 202501  (wraps over year)
  - core months: 3..12 and 1  -> 11 months
  - padded ±2 would exceed 12 months
  -> result: all months 1..12
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def parse_yyyymm(s: str) -> tuple[int, int]:
    """
    Parse a YYYYMM string into (year, month).

    We only really care about the month for seasonality, but
    we keep year for sanity / debugging.
    """
    s = str(s)
    if len(s) != 6 or not s.isdigit():
        raise ValueError(f"Invalid YYYYMM value: {s!r}")
    year = int(s[:4])
    month = int(s[4:6])
    if not 1 <= month <= 12:
        raise ValueError(f"Month out of range in {s!r}")
    return year, month


def month_add(m: int, delta: int) -> int:
    """
    Add delta months (can be negative) on a 1..12 circular calendar.

    Example:
      month_add(1, -2) -> 11
      month_add(12, 1) -> 1
    """
    return ((m - 1 + delta) % 12) + 1


def build_season_months(core_start_ym: str, core_end_ym: str) -> set[int]:
    """
    Build the set of months-of-year to keep.

    Steps:
      1. Take core months from start→end (inclusive), wrapping over year if needed.
      2. Add 2 months before start and 2 months after end.
      3. If this union is >= 12 months, return all 1..12.
    """
    _, start_m = parse_yyyymm(core_start_ym)
    _, end_m = parse_yyyymm(core_end_ym)

    # 1) core months on circular calendar
    core = set()
    m = start_m
    core.add(m)
    # step forward until we hit end_m (or safety break)
    while m != end_m:
        m = month_add(m, 1)
        core.add(m)
        if len(core) > 12:
            break  # safety, shouldn't normally happen

    # 2) padding ±2 months
    months = set(core)
    months.add(month_add(start_m, -1))
    months.add(month_add(start_m, -2))
    months.add(month_add(end_m, 1))
    months.add(month_add(end_m, 2))

    # 3) cap at 12 months
    if len(months) >= 12:
        months = set(range(1, 13))

    print(f"[SEASON] Core months from {core_start_ym} → {core_end_ym}: {sorted(core)}")
    print(f"[SEASON] With ±2 padding: {sorted(months)} (n={len(months)})")
    return months


def detect_date_column(df: pd.DataFrame) -> str:
    """
    Try to guess a date/time column name.
    Priorities: 'date', 'time', 'datetime'.
    """
    for cand in ["date", "time", "datetime"]:
        if cand in df.columns:
            return cand
    raise ValueError(
        "Could not find a date-like column. "
        "Expected one of: 'date', 'time', 'datetime'. "
        f"Columns available: {list(df.columns)}"
    )


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Filter comparison_table (or any CSV) by seasonal months with ±2 month padding."
    )

    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Input CSV path (e.g. comparison_table.csv).",
    )

    parser.add_argument(
        "--output",
        "-o",
        required=False,
        help="Output CSV path. Default: adds '_season' before extension.",
    )

    parser.add_argument(
        "--core-start",
        required=True,
        help="Core start month as YYYYMM (e.g. 202407).",
    )

    parser.add_argument(
        "--core-end",
        required=True,
        help="Core end month as YYYYMM (e.g. 202410).",
    )

    args = parser.parse_args()

    in_path = Path(args.input).expanduser()
    if not in_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {in_path}")

    if args.output:
        out_path = Path(args.output).expanduser()
    else:
        out_path = in_path.with_name(in_path.stem + "_season" + in_path.suffix)

    print(f"[SEASON] Input CSV : {in_path}")
    print(f"[SEASON] Output CSV: {out_path}")

    # 1) build month-of-year set
    season_months = build_season_months(args.core_start, args.core_end)

    # 2) load CSV
    df = pd.read_csv(in_path)

    # 3) detect date column & parse dates
    date_col = detect_date_column(df)
    print(f"[SEASON] Using date column: {date_col}")
    dates = pd.to_datetime(df[date_col])

    # 4) filter by month-of-year
    months = dates.dt.month
    mask = months.isin(season_months)
    df_filt = df[mask].copy()

    print(f"[SEASON] Rows before: {len(df)}, after season filter: {len(df_filt)}")

    # 5) write output
    df_filt.to_csv(out_path, index=False)
    print("[SEASON] Done.")


if __name__ == "__main__":
    main()

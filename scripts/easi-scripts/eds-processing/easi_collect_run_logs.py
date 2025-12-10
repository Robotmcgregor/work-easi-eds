#!/usr/bin/env python
"""
Collect lightweight JSON provenance logs from EDS seasonal-window runs and
produce a consolidated summary (JSON and CSV).

It scans a folder tree for files matching "*_dllmz_log.json" written by:
 - easi_eds_legacy_method_window_fc.py (process: vi-fpc)
 - easi_eds_legacy_method_window_sr_ndvi.py (process: vi-ndvi)
 - easi_eds_legacy_method_window_sr_vi.py (process: vi-<index>)

Outputs:
 - eds_run_summary.json: array of run objects
 - eds_run_summary.csv:  tabular summary for spreadsheets

Usage:
  python easi_collect_run_logs.py --root C:\path\to\compat --out C:\path\to\reports

Notes:
 - Non-technical friendly: field names are human-readable.
 - Safe: skips unreadable/corrupt JSONs and reports counts.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import List, Dict, Any


def find_log_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*_dllmz_log.json")]


essential_fields = [
    "scene",
    "start_date",
    "end_date",
    "process",
    "window_start",
    "window_end",
    "lookback_years",
]

optional_fields = [
    "baseline_dates",
    "selected_start_date",
    "selected_end_date",
]

output_fields = [
    "outputs.dll",
    "outputs.dlj",
]

param_fields = [
    "parameters.savi_L",
    "omit_fpc_start_threshold",
]


def flatten(d: Dict[str, Any], path: str) -> Any:
    cur = d
    for key in path.split('.'):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def collect_logs(root: Path) -> List[Dict[str, Any]]:
    logs: List[Dict[str, Any]] = []
    for p in find_log_files(root):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Enrich with source path
            data["log_path"] = str(p)
            logs.append(data)
        except Exception as e:
            print(f"[WARN] Skipping {p}: {e}")
    return logs


def write_json(summary: List[Dict[str, Any]], out_json: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)


def write_csv(summary: List[Dict[str, Any]], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    # Construct headers
    headers = [
        "scene",
        "start_date",
        "end_date",
        "process",
        "window_start",
        "window_end",
        "lookback_years",
        "selected_start_date",
        "selected_end_date",
        "outputs.dll",
        "outputs.dlj",
        "parameters.savi_L",
        "omit_fpc_start_threshold",
        "log_path",
    ]
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for row in summary:
            rec: Dict[str, Any] = {}
            for h in headers:
                rec[h] = flatten(row, h) if '.' in h else row.get(h)
            w.writerow(rec)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collect EDS seasonal-window run logs into JSON/CSV summary")
    ap.add_argument("--root", required=True, help="Root folder to scan for *_dllmz_log.json")
    ap.add_argument("--out", required=True, help="Output folder for summary files")
    args = ap.parse_args(argv)

    root = Path(args.root)
    out_dir = Path(args.out)

    logs = collect_logs(root)
    print(f"[INFO] Found {len(logs)} log files under {root}")

    # Sort by scene and end_date for readability
    logs_sorted = sorted(logs, key=lambda d: (d.get("scene", ""), d.get("end_date", "")))

    out_json = out_dir / "eds_run_summary.json"
    out_csv = out_dir / "eds_run_summary.csv"

    write_json(logs_sorted, out_json)
    write_csv(logs_sorted, out_csv)

    print(f"[INFO] Wrote: {out_json}")
    print(f"[INFO] Wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Verify that only Landsat 8/9 SR composites and FC products are present for a tile.

Scans a tile directory layout like:
  <root>/<PPP_RRR>/<YYYY>/<YYYYMM>/...*.tif

Reports any SR composites whose filenames indicate Landsat 5/7 (ga_ls5t_ard_* or ga_ls7e_ard_*),
and summarises counts by sensor for SR and FC. FC products (ga_ls_fc) include a platform
property in STAC but not in filename; we flag pre-2013 FC dates as a potential mixed-sensor period.

Usage:
  python scripts/verify_sr_fc_sources.py --root D:\data\lsat --tile 094_076 --report report_sources_094_076.json

Exit code is 0 even if issues found; warnings are printed and included in JSON so this can be
used as a non-fatal QA step in pipelines.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

SR_PREFIXES = {
    'ls5': 'ga_ls5t_ard_',
    'ls7': 'ga_ls7e_ard_',
    'ls8': 'ga_ls8c_ard_',
    'ls9': 'ga_ls9c_ard_',
}

def scan_tile(root: Path, tile: str) -> Dict[str, List[str]]:
    tile_dir = root / tile
    results: Dict[str, List[str]] = {k: [] for k in SR_PREFIXES}
    fc_files: List[str] = []
    if not tile_dir.exists():
        return results
    for tif in tile_dir.rglob('*.tif'):
        name = tif.name.lower()
        # SR composites contain _srb6/_srb7; individual bands have _nbart_
        if '_srb6' in name or '_srb7' in name or '_nbart_' in name:
            for sensor, pref in SR_PREFIXES.items():
                if name.startswith(pref):
                    results[sensor].append(str(tif))
                    break
        elif name.endswith('_fc3ms.tif') or name.endswith('_fc3ms_clr.tif'):
            fc_files.append(str(tif))
    results['fc'] = fc_files  # type: ignore
    return results

def main(argv=None):
    ap = argparse.ArgumentParser(description='Verify only Landsat 8/9 SR composites present for a tile')
    ap.add_argument('--root', required=True, help='Root data directory (e.g. D:\\data\\lsat)')
    ap.add_argument('--tile', required=True, help='Tile PPP_RRR (e.g. 094_076)')
    ap.add_argument('--report', help='Optional path to write JSON report')
    args = ap.parse_args(argv)

    root = Path(args.root)
    data = scan_tile(root, args.tile)

    ls5 = data.get('ls5', [])
    ls7 = data.get('ls7', [])
    ls8 = data.get('ls8', [])
    ls9 = data.get('ls9', [])
    fc = data.get('fc', [])

    print(f"[SUMMARY] SR counts -> LS8: {len(ls8)}, LS9: {len(ls9)}, LS7: {len(ls7)}, LS5: {len(ls5)}")
    if ls5 or ls7:
        print('[WARNING] Found Landsat 5/7 composites (should be excluded). List first 5:')
        for p in (ls5 + ls7)[:5]:
            print('  ', p)
    else:
        print('[OK] No LS5/LS7 SR composites detected.')
    print(f"[INFO] FC product files: {len(fc)}")
    # Flag potential pre-LS8 FC if any date < 2013
    pre2013 = [p for p in fc if any(int(seg[:4]) < 2013 for seg in p.split('_') if seg.isdigit() and len(seg) == 8)]
    if pre2013:
        print('[NOTE] FC files with dates before 2013 detected; FC product may internally derive from earlier sensors.')

    report = {
        'tile': args.tile,
        'root': str(root),
        'sr': {
            'ls5': ls5,
            'ls7': ls7,
            'ls8': ls8,
            'ls9': ls9,
        },
        'fc_files': fc,
        'issues': {
            'has_ls5': bool(ls5),
            'has_ls7': bool(ls7),
            'pre2013_fc': bool(pre2013),
        }
    }
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'[REPORT] Wrote {out}')
    else:
        print(json.dumps(report, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

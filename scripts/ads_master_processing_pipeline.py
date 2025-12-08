#!/usr/bin/env python
"""
Master processing pipeline to execute the legacy SLATS-style EDS workflow after inputs
(SR start/end composites + FC seasonal timeseries) have been acquired.

This script chains the steps documented in README_EDS_Workflow.md:
  1. Build SLATS compat layer (db8 + dc4) -> slats_compat_builder.py
  2. Run legacy seasonal change method -> eds_legacy_method_window.py
  3. Style dll/dlj rasters (palette + band names) -> style_dll_dlj.py
  4. Polygonize merged thresholds (>= semantics) -> polygonize_merged_thresholds.py
  5. Post-process vectors (dissolve + skinny core filter) -> vector_postprocess.py
  6. Derive FC coverage extent & consistent mask -> fc_coverage_extent.py
  7. Clip cleaned vectors by strict + ratio coverage masks -> clip_vectors.py
  8. (Optional) Inspection utilities (not auto-run here)

Assumptions:
 - Input acquisition already done (e.g., via eds_master_data_pipeline.py).
 - SR & FC data reside under --sr-root / --fc-root in a layout compatible with slats_compat_builder.
 - Filenames follow expected patterns (*_db8mz.img, *_dc4mz.img produced by compat step).

Span years: --span-years influences how many prior years of FC are considered for building the compat layer.
This script passes --lookback to eds_legacy_method_window.py based on span-years (capped by available FC).

Usage example (PowerShell):
  python scripts/ads_master_processing_pipeline.py \
    --tile 094_076 \
    --start-date 20230720 \
    --end-date   20240831 \
    --span-years 2 \
    --sr-root D:\data\lsat \
    --fc-root D:\data\lsat \
    --out-root data/compat/files \
    --season-window 0701 1031 \
    --min-ha 1 \
    --skinny-pixels 3 \
    --ratio-presence 0.95 0.90

You can add --dry-run to print the planned steps without executing.
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

# Ensure repo root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_THRESHOLDS = [34, 35, 36, 37, 38, 39]


def run_cmd(cmd: List[str], dry_run: bool, step: str, results: dict) -> None:
    print(f"\n[STEP] {step}")
    print("Command:", " ".join(cmd))
    if dry_run:
        print("(dry-run) Skipped execution")
        return
    #!/usr/bin/env python
    """Deprecated wrapper.

    The file was originally misnamed (ads_master_processing_pipeline.py). Use
    `scripts/eds_master_processing_pipeline.py` instead.

    This wrapper prints a message and exits with code 2 unless --allow-run-legacy is provided.
    """
    from __future__ import annotations

    import argparse
    import sys

    def main():
        ap = argparse.ArgumentParser(
            description="Deprecated ads* master pipeline wrapper"
        )
        ap.add_argument(
            "--allow-run-legacy",
            action="store_true",
            help="(Unused) maintain compat for old automation",
        )
        args, rest = ap.parse_known_args()
        print(
            "[DEPRECATION] ads_master_processing_pipeline.py has been replaced by eds_master_processing_pipeline.py"
        )
        print("Invoke: python scripts/eds_master_processing_pipeline.py <args>")
        if args.allow_run_legacy:
            print("No legacy implementation retained; exiting.")
        return 2

    if __name__ == "__main__":
        raise SystemExit(main())

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import re


@dataclass(frozen=True)
class LegacyOutputs:
    dll_img: Path
    dlj_img: Path
    log_json: Optional[Path]


def run_legacy_ndvi_window(
    *,
    methods_dir: Path,
    scene: str,
    start_date: str,
    end_date: str,
    ga1_glob: str,
    start_ga0: str,
    end_ga0: str,
    window_start_mmdd: str,
    window_end_mmdd: str,
    lookback: int,
    diagnostics: bool = False,
    verbose: bool = False,
    vi_tag: str = "vi-ndvi",
    home_out_dir: str | Path | None = None,
) -> LegacyOutputs:
    script = Path(methods_dir) / "legacy_window_ndvi_envi.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing legacy method script: {script}")

    print("ga1_glob: ", ga1_glob)
    print("start_ga0: ", start_ga0)
    print("end_ga0: ", end_ga0)

    tile = scene.lower()

    # Final desired output naming derived from end GA0
    end_name = Path(end_ga0).name
    m = re.match(r"(sl\d)olre_(p\d+r\d+)_\d{8}_ga0.*_e(\d+)\.tif", end_name)
    if not m:
        raise RuntimeError(f"Could not parse GA0 filename: {end_name}")

    platform = m.group(1)
    target_epsg = m.group(3)

    dll_img = Path(
        f"{platform}olre_{tile}_d{start_date}{end_date}_dll_e{target_epsg}.tif"
    )
    dlj_img = Path(
        f"{platform}olre_{tile}_d{start_date}{end_date}_dlj_e{target_epsg}.tif"
    )
    log_json = Path(
        f"{platform}olre_{tile}_d{start_date}{end_date}_dll_log_e{target_epsg}.json"
    )

    print("start_date: ", start_date)
    print("end_date: ", end_date)
    print("dll_img: ", dll_img)
    print("dlj_img: ", dlj_img)
    print("log_json : ", log_json)
    print("-" * 100)

    cmd = [
        "python", str(script),
        "--scene", scene.lower(),
        "--start-date", start_date,
        "--end-date", end_date,
        "--dc4-glob", ga1_glob,
        "--start-db8", start_ga0,
        "--end-db8", end_ga0,
        "--window-start", window_start_mmdd,
        "--window-end", window_end_mmdd,
        "--lookback", str(int(lookback)),
        "--vi-tag", vi_tag,
    ]

    if verbose:
        cmd.append("--verbose")
    if diagnostics:
        cmd.append("--diagnostics")

    print("[RUN]", " ".join(cmd))
    subprocess.check_call(cmd)

    return LegacyOutputs(
        dll_img=dll_img,
        dlj_img=dlj_img,
        log_json=log_json if log_json.exists() else None,
    )
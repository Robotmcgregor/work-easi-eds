from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class LegacyOutputs:
    dll_img: Path
    dlj_img: Path
    log_json: Optional[Path]


def run_legacy_ndvi_window(
    *,
    methods_dir: Path,
    scene: str,
    start_date: str,  # YYYYMMDD
    end_date: str,    # YYYYMMDD
    dc4_glob: str,
    start_db8: str,
    end_db8: str,
    window_start_mmdd: str,
    window_end_mmdd: str,
    lookback: int,
    diagnostics: bool = False,
    verbose: bool = False,
    vi_tag: str = 'vi-ndvi',
) -> LegacyOutputs:
    """Run the legacy NDVI seasonal-window method.

    We intentionally keep the legacy computation in a separate process to:
      - preserve behaviour
      - avoid side-effects from GDAL global state

    The legacy script writes ENVI .img outputs; downstream tasks convert them to COG GeoTIFF.
    """
    script = Path(methods_dir) / 'legacy_window_ndvi_envi.py'
    if not script.exists():
        raise FileNotFoundError(f'Missing legacy method script: {script}')

    out_base = f"lztmre_{scene.lower()}_d{start_date}{end_date}_{vi_tag}"
    dll_img = Path(f"{out_base}_dllmz.img")
    dlj_img = Path(f"{out_base}_dljmz.img")
    log_json = Path(f"{out_base}_dllmz_log.json")

    cmd = [
        'python', str(script),
        '--scene', scene.lower(),
        '--start-date', start_date,
        '--end-date', end_date,
        '--dc4-glob', dc4_glob,
        '--start-db8', start_db8,
        '--end-db8', end_db8,
        '--window-start', window_start_mmdd,
        '--window-end', window_end_mmdd,
        '--lookback', str(int(lookback)),
        '--vi-tag', vi_tag,
    ]

    if verbose:
        cmd.append('--verbose')
    if diagnostics:
        cmd.append('--diagnostics')

    print('[RUN]', ' '.join(cmd))
    subprocess.check_call(cmd)

    return LegacyOutputs(
        dll_img=dll_img,
        dlj_img=dlj_img,
        log_json=log_json if log_json.exists() else None,
    )

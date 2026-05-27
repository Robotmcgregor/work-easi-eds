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

"""Task 07: stage GA1 NDVI files locally.

Non-coder summary:
- Earlier steps ensure NDVI scenes exist in S3.
- The legacy method reads files from disk (local paths), not directly from S3.
- This task downloads the required NDVI COGs into a local folder for this run.
"""

from pathlib import Path

from lib.s3_io import download_s3_uri, s3_key_exists
from lib.dates import normalise_yyyymmdd


def stage_ga1_ndvi_locally(
    *,
    bucket: str,
    prefix: str,
    tile: str,
    required_dates: list[tuple[str, str, int]],
    work_dir: Path,
    dry_run: bool = False,
) -> Path:
    """Download the required NDVI COGs from S3 into a local staging directory.

    `required_dates` is a list of (YYYYMMDD, platform, epsg).
    Returns the directory containing the downloaded files.
    """
    tile = tile.lower().strip()
    work_dir = Path(work_dir)
    out_dir = work_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[DEBUG] required_dates passed to stage_ga1_ndvi_locally:")
    for item in required_dates:
        print("   ", item)

    for yyyymmdd, platform, epsg in required_dates:
        yyyymmdd = normalise_yyyymmdd(yyyymmdd)
        yyyymm = yyyymmdd[:6]
        platform_str = str(platform).strip().lower()

        if platform_str.startswith("sl"):
            platform_tag = platform_str
        elif platform_str.startswith("ls"):
            platform_tag = f"sl{platform_str[2:]}"
        elif platform_str.startswith("l") and len(platform_str) == 2:
            platform_tag = f"sl{platform_str[1:]}"
        else:
            raise ValueError(f"Unsupported platform format: {platform}")

        s3_key = (
            f"{prefix.rstrip('/')}/tiles/{tile}/{yyyymmdd[:4]}/{yyyymm}/"
            f"{platform_tag}olre_{tile}_{yyyymmdd}_ga1-clr_e{epsg}.tif"
        )
        uri = f"s3://{bucket}/{s3_key}"
        local_path = out_dir / f"{platform_tag}olre_{tile}_{yyyymmdd}_ga1-clr_e{epsg}.tif"

        print(f"[STAGE] {uri}")

        if local_path.exists():
            continue

        if not s3_key_exists(bucket, s3_key):
            print(f"[WARN] Missing NDVI in S3, skipping: {uri}")
            continue

        if dry_run:
            print(f"[DRY] STAGE {uri} -> {local_path}")
            continue

        download_s3_uri(uri, str(local_path))

    return out_dir

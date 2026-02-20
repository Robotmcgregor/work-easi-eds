from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import rasterio

from lib.cog import to_cog
from lib.s3_io import upload_file_to_s3


@dataclass(frozen=True)
class UploadedOutput:
    local_cog: Path
    s3_uri: str


@dataclass(frozen=True)
class ConvertedOutputs:
    dllmz_cog_local: Path
    dljmz_cog_local: Path
    uploaded: List[UploadedOutput]


def _envi_img_to_tif(src_img: Path, dst_tif: Path) -> None:
    """Convert ENVI .img (plus .hdr sidecar) to GeoTIFF preserving values."""
    with rasterio.open(src_img) as src:
        profile = src.profile.copy()
        profile.update(driver="GTiff")
        data = src.read()
        with rasterio.open(dst_tif, "w", **profile) as dst:
            dst.write(data)
            dst.update_tags(**src.tags())


def convert_outputs_to_cog_and_upload(
    *,
    dll_img: Path,
    dlj_img: Path,
    bucket: str,
    prefix: str,
    tile: str,
    run_tag: str,
    work_dir: Path,
) -> ConvertedOutputs:
    """Convert legacy ENVI outputs (dllmz/dljmz) to COG GeoTIFF and upload to S3.

    Returns local paths for both COGs and a list of uploaded S3 URIs.
    """
    tile = tile.lower().strip()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    uploaded: List[UploadedOutput] = []

    dllmz_cog_local: Optional[Path] = None
    dljmz_cog_local: Optional[Path] = None

    for src in [Path(dll_img), Path(dlj_img)]:
        if not src.exists():
            raise FileNotFoundError(f"Missing expected legacy output: {src}")

        base = src.stem  # without .img
        raw_tif = work_dir / f"{base}.tif"
        cog_tif = work_dir / f"{base}_cog.tif"

        _envi_img_to_tif(src, raw_tif)
        to_cog(str(raw_tif), str(cog_tif), overwrite=True)

        key = f"{prefix.rstrip('/')}/tiles/{tile}/outputs/{run_tag}/{cog_tif.name}"
        upload_file_to_s3(str(cog_tif), bucket=bucket, key=key)
        uploaded.append(UploadedOutput(local_cog=cog_tif, s3_uri=f"s3://{bucket}/{key}"))

        name = src.name.lower()
        if "dllmz" in name:
            dllmz_cog_local = cog_tif
        elif "dljmz" in name:
            dljmz_cog_local = cog_tif

        # cleanup the intermediate raw tif
        try:
            raw_tif.unlink(missing_ok=True)
        except Exception:
            pass

    if dllmz_cog_local is None or dljmz_cog_local is None:
        raise RuntimeError(
            f"Could not determine dllmz/dljmz outputs from inputs: {dll_img}, {dlj_img}"
        )

    return ConvertedOutputs(
        dllmz_cog_local=dllmz_cog_local,
        dljmz_cog_local=dljmz_cog_local,
        uploaded=uploaded,
    )

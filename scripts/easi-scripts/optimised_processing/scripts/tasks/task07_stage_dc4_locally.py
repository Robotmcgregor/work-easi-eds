from __future__ import annotations

from pathlib import Path

from lib.s3_io import download_s3_uri


def stage_dc4_ndvi_locally(
    *,
    bucket: str,
    prefix: str,
    tile: str,
    required_dates: list[tuple[str, str, int]],
    work_dir: Path,
    dry_run: bool = False,
) -> Path:

    """
    
    Download required NDVI COGs from S3 to a local folder.
    required_dates: list of (YYYYMMDD, platform, epsg)
    Returns the local directory containing the files.
    """
    tile = tile.lower().strip()
    work_dir = Path(work_dir)
    out_dir = work_dir / 'dc4_ndvi'
    out_dir.mkdir(parents=True, exist_ok=True)

    for yyyymmdd, platform, epsg in required_dates:
        s3_key = (
            f"{prefix.rstrip('/')}/tiles/{tile}/ndvi/{platform}/{yyyymmdd[:4]}/{yyyymmdd}/"
            f"lztmre_{tile}_{yyyymmdd}_ndvi_{epsg}.tif"
        )
        uri = f"s3://{bucket}/{s3_key}"
        local_path = out_dir / f"lztmre_{tile}_{yyyymmdd}_ndvi_{epsg}.tif"
        if local_path.exists():
            continue
        
        if dry_run:
            print(f"[DRY] STAGE {uri} -> {local_path}")
            continue


        download_s3_uri(uri, str(local_path))

    return out_dir

from __future__ import annotations

from pathlib import Path

from lib.s3_io import download_s3_uri, s3_key_exists


def stage_ga1_ndvi_locally(
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
    out_dir = work_dir / "ga1_ndvi"
    out_dir.mkdir(parents=True, exist_ok=True)

    for yyyymmdd, platform, epsg in required_dates:
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
            f"{prefix.rstrip('/')}/tiles/{tile}/{yyyymmdd[:4]}/{yyyymmdd}/"
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

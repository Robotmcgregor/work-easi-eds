from __future__ import annotations

from typing import Dict, Set

from lib.s3_io import list_s3_keys


def inventory_existing_ndvi(
    bucket: str,
    prefix: str,
    tile: str,
) -> Set[str]:
    """Return a set of S3 keys for existing NDVI outputs for fast resume.

    Expected layout (same as optimised_ndvi):
      {prefix}/tiles/{tile}/ndvi/{platform}/{YYYY}/{YYYYMMDD}/..._ndvi_*.tif

    We return keys (not URIs) so callers can do quick membership checks.
    """
    tile = tile.lower().strip()
    base = f"{prefix.rstrip('/')}/tiles/{tile}/ndvi/"
    keys = list_s3_keys(bucket=bucket, prefix=base)
    # only keep ndvi tifs
    return {k for k in keys if k.lower().endswith('.tif') and '_ndvi_' in k}

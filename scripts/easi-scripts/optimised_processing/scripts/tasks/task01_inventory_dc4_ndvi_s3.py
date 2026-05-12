from __future__ import annotations

from typing import Dict, Set

from lib.s3_io import list_s3_keys


def inventory_existing_ndvi(
    bucket: str,
    prefix: str,
    tile: str,
) -> Set[str]:
    """
    Return a set of S3 keys for NDVI files that already exist.

    This is mainly so we can skip stuff we already did and resume faster.

        Expected layout (month-bucketed):
            {prefix}/tiles/{tile}/ndvi/{platform}/{YYYY}/{YYYYMM}/..._ndvi_*.tif

    We return keys only (not full s3:// URIs) because its easier to compare.
    """
    # normalise tile name
    tile = tile.lower().strip()

    # build the base prefix where ndvi outputs should live
    base = f"{prefix.rstrip('/')}/tiles/{tile}/ndvi/"

    # list everything under that prefix
    keys = list_s3_keys(bucket=bucket, prefix=base)

    # only keep tif files that look like ndvi outputs
    return {
        k for k in keys
        if k.lower().endswith(".tif") and "_ndvi_" in k
    }
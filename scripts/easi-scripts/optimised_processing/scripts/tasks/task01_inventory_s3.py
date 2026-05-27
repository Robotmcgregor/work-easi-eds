from __future__ import annotations

from typing import List
from lib.s3_io import list_s3_keys


def inventory_existing_outputs(bucket: str, prefix: str, tile: str) -> List[str]:
    """
    Just lists NDVI outputs that already exist in S3 so we dont redo work.
    """
    # build the base path where ndvi files should be
    base = f"{prefix}/tiles/{tile}/ndvi/"

    # list all keys under that prefix
    keys = list_s3_keys(bucket=bucket, prefix=base)

    # only keep files that look like ndvi tifs
    # this is a bit loose but good enough for now
    return [k for k in keys if "_ndvi_" in k and k.endswith(".tif")]
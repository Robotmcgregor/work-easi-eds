from __future__ import annotations

from typing import List
from lib.s3_io import list_s3_keys


def inventory_existing_outputs(bucket: str, prefix: str, tile: str) -> List[str]:
    """
    Lightweight inventory: list NDVI outputs already present in S3.
    """
    base = f"{prefix}/tiles/{tile}/ndvi/"
    keys = list_s3_keys(bucket=bucket, prefix=base)
    # keep only ndvi outputs (optional)
    return [k for k in keys if "_ndvi_" in k and k.endswith(".tif")]


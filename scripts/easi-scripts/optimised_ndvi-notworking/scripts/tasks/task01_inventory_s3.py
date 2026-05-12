from __future__ import annotations
import boto3

def inventory_outputs(bucket: str, prefix: str, tile: str) -> list[str]:
    """
    List existing NDVI outputs under:
      <prefix>/tiles/<tile>/ndvi/
    Returns a list of S3 keys.
    """
    s3 = boto3.client("s3")
    base = f"{prefix}/tiles/{tile}/ndvi/".lstrip("/")
    keys = []

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=base):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys

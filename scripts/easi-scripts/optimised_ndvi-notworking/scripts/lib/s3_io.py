from __future__ import annotations
from pathlib import Path
import boto3
from boto3.s3.transfer import TransferConfig

def s3_key_exists(bucket: str, key: str) -> bool:
    s3 = boto3.client("s3")
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False

def upload_file_to_s3(local_path: str, bucket: str, key: str) -> None:
    """
    Multipart upload tuned for large GeoTIFFs.
    """
    s3 = boto3.client("s3")
    cfg = TransferConfig(
        multipart_threshold=64 * 1024 * 1024,   # 64MB
        multipart_chunksize=64 * 1024 * 1024,
        max_concurrency=8,
        use_threads=True,
    )
    s3.upload_file(local_path, bucket, key, Config=cfg)

def parse_s3_uri(uri: str) -> tuple[str, str]:
    # s3://bucket/key...
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3 uri: {uri}")
    no = uri[5:]
    bucket, key = no.split("/", 1)
    return bucket, key

def s3_uri_exists(uri: str) -> bool:
    b, k = parse_s3_uri(uri)
    return s3_key_exists(b, k)

def download_s3_uri(uri: str, local_path: str) -> None:
    b, k = parse_s3_uri(uri)
    s3 = boto3.client("s3")
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(b, k, local_path)

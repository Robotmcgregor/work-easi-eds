from __future__ import annotations

import boto3
from botocore.exceptions import ClientError
from typing import List, Tuple


def parse_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3 uri: {uri}")
    parts = uri[5:].split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


def s3_uri_exists(uri: str) -> bool:
    b, k = parse_s3_uri(uri)
    return s3_key_exists(b, k)


def s3_key_exists(bucket: str, key: str) -> bool:
    s3 = boto3.client("s3")
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        return False


def download_s3_uri(uri: str, local_path: str) -> None:
    b, k = parse_s3_uri(uri)
    s3 = boto3.client("s3")
    s3.download_file(b, k, local_path)


def upload_file_to_s3(local_path: str, bucket: str, key: str) -> None:
    import boto3
    from pathlib import Path

    s3 = boto3.client("s3")

    local_path = str(local_path)
    s3.upload_file(local_path, bucket, key)

    file_size = Path(local_path).stat().st_size / (1024 * 1024)

    print(
        f"[OK] Uploaded {Path(local_path).name} "
        f"({file_size:.2f} MB) -> s3://{bucket}/{key}"
    )



def list_s3_keys(bucket: str, prefix: str) -> List[str]:
    s3 = boto3.client("s3")
    keys: List[str] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            keys.append(obj["Key"])
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return keys

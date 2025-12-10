#!/usr/bin/env python
"""
Upload a packaged EDS ZIP file to an S3 bucket.

Usage example:

  python upload_eds_zip_to_s3.py \
    --zip-path /home/jovyan/work-easi-eds/exports/p104r072_d2020061120220812_eds_outputs.zip \
    --bucket eia-satellite \
    --prefix eds/outputs

This will upload the ZIP as:

  s3://eia-satellite/eds/outputs/p104r072_d2020061120220812_eds_outputs.zip

Credentials:
  - Relies on standard boto3 auth (env vars, AWS config/credentials file,
    or attached IAM role). Do NOT hard-code keys in this script.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def upload_zip_to_s3(
    zip_path: Path, bucket_name: str, prefix: str, region: str = "ap-southeast-2"
) -> str:
    """Upload the zip file to s3://bucket/prefix/filename and return the S3 key."""
    zip_path = zip_path.resolve()
    if not zip_path.exists():
        raise SystemExit(f"ZIP file does not exist: {zip_path}")

    # Normalise prefix (no leading slash, optional trailing slash)
    prefix = prefix.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    key = f"{prefix}{zip_path.name}"

    # Use standard boto3 auth (env vars, config file, or IAM role)
    s3 = boto3.resource(
        service_name="s3",
        region_name=region,
        # Do NOT hard-code aws_access_key_id / aws_secret_access_key here.
    )

    bucket = s3.Bucket(bucket_name)
    try:
        print(f"[INFO] Uploading {zip_path} -> s3://{bucket_name}/{key}")
        bucket.upload_file(str(zip_path), key)
        print(f"[OK] Uploaded to s3://{bucket_name}/{key}")
    except (BotoCoreError, ClientError) as e:
        raise SystemExit(f"[ERROR] Failed to upload to S3: {e}")

    return key


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Upload an EDS outputs ZIP to an S3 bucket."
    )
    ap.add_argument(
        "--zip-path",
        required=True,
        help="Path to the ZIP file produced by package_eds_outputs.py",
    )
    ap.add_argument(
        "--bucket",
        required=True,
        help="Target S3 bucket name (e.g. eia-satellite)",
    )
    ap.add_argument(
        "--prefix",
        default="eds/outputs",
        help="Key prefix inside the bucket (default: eds/outputs)",
    )
    ap.add_argument(
        "--region",
        default="ap-southeast-2",
        help="AWS region for the S3 resource (default: ap-southeast-2)",
    )
    args = ap.parse_args(argv)

    zip_path = Path(args.zip_path)
    upload_zip_to_s3(zip_path, args.bucket, args.prefix, region=args.region)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Lightweight S3 client wrapper for listing and downloading objects.

Usage:
    from src.config.settings import get_config
    from src.utils.s3_client import S3Client

    cfg = get_config().s3
    s3 = S3Client(bucket=cfg.bucket, region=cfg.region, profile=cfg.profile,
                  endpoint_url=cfg.endpoint_url, role_arn=cfg.role_arn)
    for obj in s3.list_prefix(cfg.base_prefix + "/090084/", recursive=True):
        print(obj)
    s3.download("landsat/090084/2025-10-01/sample.tif", "data/cache/090084/sample.tif")

Notes:
- Credentials are picked up from the configured AWS profile or environment variables.
- If role_arn is provided, the client will attempt to assume that role.
- For S3-compatible stores (e.g., MinIO), set endpoint_url.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Generator, Optional, List

logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.exceptions import ClientError, ProfileNotFound
except Exception:  # pragma: no cover - graceful if boto3 not installed
    boto3 = None
    ClientError = Exception
    class ProfileNotFound(Exception):
        pass


@dataclass
class S3Auth:
    profile: str = ""
    region: str = ""
    endpoint_url: str = ""
    role_arn: str = ""


class S3Client:
    def __init__(self, bucket: str, region: str = "", profile: str = "", endpoint_url: str = "", role_arn: str = ""):
        if not boto3:
            raise RuntimeError("boto3 is required for S3 operations. Please install boto3 and retry.")
        self.bucket = bucket
        # Prefer explicit region, else AWS_REGION, else AWS_DEFAULT_REGION
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        # Respect explicit empty string ("") to mean "do not use profile"
        if profile is None:
            self.profile = os.environ.get("AWS_PROFILE")
        else:
            self.profile = profile
        self.endpoint_url = endpoint_url or os.environ.get("S3_ENDPOINT_URL")
        self.role_arn = role_arn or os.environ.get("S3_ROLE_ARN")

        # Build session
        # If explicit static keys are present and no profile requested, ensure AWS_PROFILE env doesn't force a profile
        if (
            (not self.profile)
            and os.environ.get("AWS_PROFILE")
            and os.environ.get("AWS_ACCESS_KEY_ID")
            and os.environ.get("AWS_SECRET_ACCESS_KEY")
        ):
            # Remove AWS_PROFILE to stop boto3 auto-selecting an unavailable profile
            try:
                os.environ.pop("AWS_PROFILE")
            except KeyError:
                pass
        if self.profile:
            try:
                session = boto3.Session(profile_name=self.profile, region_name=self.region or None)
            except Exception as e:  # includes ProfileNotFound
                logger.warning("AWS profile '%s' not found or unusable; falling back to default credentials. (%s)", self.profile, e)
                session = boto3.Session(region_name=self.region or None)
        else:
            session = boto3.Session(region_name=self.region or None)

        # Assume role if provided
        if self.role_arn:
            sts = session.client("sts")
            resp = sts.assume_role(RoleArn=self.role_arn, RoleSessionName="eds-s3-session")
            creds = resp["Credentials"]
            self._client = boto3.client(
                "s3",
                region_name=self.region or None,
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                endpoint_url=self.endpoint_url or None,
            )
        else:
            self._client = session.client("s3", endpoint_url=self.endpoint_url or None)

    def list_prefix(self, prefix: str, recursive: bool = True, max_keys: Optional[int] = None) -> Generator[str, None, None]:
        """Yield object keys under the given prefix.

        Args:
            prefix: S3 key prefix
            recursive: Whether to traverse sub-prefixes
            max_keys: Optional limit of returned keys
        """
        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
        count = 0
        for page in pages:
            for obj in page.get("Contents", []) or []:
                yield obj["Key"]
                count += 1
                if max_keys and count >= max_keys:
                    return
            if not recursive:
                return

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if getattr(e, "response", {}).get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise

    def download(self, key: str, dest_path: str, overwrite: bool = False) -> str:
        """Download an object to a local path.

        Returns the destination path.
        """
        if not overwrite and os.path.exists(dest_path):
            return dest_path
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        logger.info(f"S3 download s3://{self.bucket}/{key} -> {dest_path}")
        self._client.download_file(self.bucket, key, dest_path)
        return dest_path

    def download_prefix(self, prefix: str, dest_dir: str, overwrite: bool = False, max_files: Optional[int] = None) -> List[str]:
        os.makedirs(dest_dir, exist_ok=True)
        downloaded: List[str] = []
        for i, key in enumerate(self.list_prefix(prefix, recursive=True, max_keys=max_files)):
            dest_path = os.path.join(dest_dir, os.path.basename(key))
            self.download(key, dest_path, overwrite=overwrite)
            downloaded.append(dest_path)
        return downloaded

    def upload(self, src_path: str, key: str, overwrite: bool = False, content_type: Optional[str] = None) -> str:
        """Upload a local file to S3 at the specified key.

        Args:
            src_path: Local file path
            key: Destination S3 key
            overwrite: If False and object exists, skip upload
            content_type: Optional Content-Type metadata

        Returns:
            The S3 key uploaded to
        """
        if not os.path.exists(src_path):
            raise FileNotFoundError(src_path)
        if not overwrite and self.exists(key):
            logger.info(f"S3 exists, skipping upload s3://{self.bucket}/{key}")
            return key
        extra = {}
        if content_type:
            extra["ContentType"] = content_type
        logger.info(f"S3 upload {src_path} -> s3://{self.bucket}/{key}")
        if extra:
            self._client.upload_file(src_path, self.bucket, key, ExtraArgs=extra)
        else:
            self._client.upload_file(src_path, self.bucket, key)
        return key

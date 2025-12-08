"""
Data access utilities for EDS: enumerate and fetch required inputs from S3 (or other sources).

Contract:
- Inputs: tile_id (PathRow, e.g., '090084'), date range, optional product prefix.
- Behavior: check configured S3 bucket/prefix for relevant files; if present, list/download to local cache.
- Outputs: list of local file paths ready for processing.

Note: This module focuses on S3 access via the S3Client wrapper. Upstream downloads from
public datasets (e.g., AWS Open Data Landsat) can be added later.
"""

from __future__ import annotations

import os
import re
import logging
from datetime import date, datetime
from typing import List, Optional, Tuple

from src.config.settings import get_config

logger = logging.getLogger(__name__)

try:
    from src.utils.s3_client import S3Client
except Exception:  # pragma: no cover
    S3Client = None  # type: ignore
try:
    from src.utils.m2m_client import USGSM2MClient
except Exception:  # pragma: no cover
    USGSM2MClient = None  # type: ignore


# Match dates in keys as YYYYMMDD or YYYY-MM-DD or YYYY/MM/DD
# Capture full 4-digit year in group 1
DATE_IN_KEY = re.compile(
    r"((?:19|20)\d{2})[-_/]?(0[1-9]|1[0-2])[-_/]?([0-2][0-9]|3[01])"
)


class DataAccessor:
    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        role_arn: Optional[str] = None,
        base_prefix: Optional[str] = None,
    ):
        self.cfg = get_config()
        self.cache_dir = self.cfg.processing.data_cache_directory
        os.makedirs(self.cache_dir, exist_ok=True)

        # Resolve effective S3 settings (overrides -> config)
        eff_bucket = bucket or (
            getattr(self.cfg, "s3", None).bucket
            if getattr(self.cfg, "s3", None)
            else None
        )
        eff_region = region or (
            self.cfg.s3.region if getattr(self.cfg, "s3", None) else None
        )
        eff_profile = profile or (
            self.cfg.s3.profile if getattr(self.cfg, "s3", None) else None
        )
        eff_endpoint = endpoint_url or (
            self.cfg.s3.endpoint_url if getattr(self.cfg, "s3", None) else None
        )
        eff_role = role_arn or (
            self.cfg.s3.role_arn if getattr(self.cfg, "s3", None) else None
        )
        self.base_prefix = (
            base_prefix
            if base_prefix is not None
            else (
                (self.cfg.s3.base_prefix if getattr(self.cfg, "s3", None) else "") or ""
            )
        )

        self.s3 = None
        if eff_bucket:
            if S3Client is None:
                raise RuntimeError(
                    "boto3 is required for S3 operations but is not installed."
                )
            self.s3 = S3Client(
                bucket=eff_bucket,
                region=eff_region or "",
                profile=eff_profile or "",
                endpoint_url=eff_endpoint or "",
                role_arn=eff_role or "",
            )

    def list_s3_for_tile(
        self,
        tile_id: str,
        start: date,
        end: date,
        prefix: Optional[str] = None,
        max_keys: int = 1000,
    ) -> List[str]:
        if not self.s3:
            logger.info("S3 is not configured. Skipping S3 listing.")
            return []
        base_prefix = prefix if prefix is not None else self.base_prefix
        # Build candidate prefixes: 090084 and 090_084 (common WRS-2 naming)
        if prefix is not None and (
            tile_id in prefix
            or (len(tile_id) == 6 and f"{tile_id[:3]}_{tile_id[3:]}" in prefix)
        ):
            # Treat provided prefix as explicit, do not append tile suffix
            candidates = [prefix if prefix.endswith("/") else prefix + "/"]
            base_prefix = ""
        elif prefix is not None:
            candidates = [prefix if prefix.endswith("/") else prefix + "/"]
        else:
            no_us = f"{tile_id}/"
            with_us = (
                f"{tile_id[:3]}_{tile_id[3:]}/"
                if len(tile_id) == 6 and tile_id.isdigit()
                else tile_id + "/"
            )
            candidates = [no_us, with_us]
            # Deduplicate in case they are identical
            candidates = list(dict.fromkeys(candidates))

        keys_all: List[str] = []
        for suffix in candidates:
            search_prefix = f"{base_prefix}/{suffix}" if base_prefix else suffix
            try:
                keys = list(
                    self.s3.list_prefix(
                        search_prefix, recursive=True, max_keys=max_keys
                    )
                )
                keys_all.extend(keys)
            except Exception as e:
                logger.warning(
                    f"S3 listing failed for prefix '{search_prefix}': {e}. Trying next candidate (if any)."
                )
                continue
        if not keys_all:
            return []
        # Filter keys by embedded date (YYYY, YYYYMMDD, YYYY-MM-DD)
        filtered = []
        for k in keys_all:
            m = DATE_IN_KEY.search(k)
            if not m:
                continue
            yyyy, mm, dd = m.group(1), m.group(2), m.group(3)
            try:
                d = datetime(int(yyyy), int(mm), int(dd)).date()
            except Exception:
                continue
            if start <= d <= end:
                filtered.append(k)
        return filtered

    def ensure_local_inputs(
        self,
        tile_id: str,
        start: date,
        end: date,
        prefix: Optional[str] = None,
        download: bool = True,
        max_files: Optional[int] = None,
    ) -> List[str]:
        """Ensure required inputs exist locally; if present in S3, download to cache.
        Returns a list of local file paths.
        """
        local_dir = os.path.join(self.cache_dir, tile_id)
        os.makedirs(local_dir, exist_ok=True)

        # 1) Try S3 first
        keys = self.list_s3_for_tile(
            tile_id, start, end, prefix=prefix, max_keys=max_files or 2000
        )
        local_paths: List[str] = []
        if keys and self.s3 and download:
            for key in keys:
                filename = os.path.basename(key)
                dest = os.path.join(local_dir, filename)
                self.s3.download(key, dest, overwrite=False)
                local_paths.append(dest)
            return local_paths

        logger.info(
            f"No S3 objects found for tile {tile_id} in {start}..{end}. Attempting USGS M2M fetch..."
        )

        # 2) Fallback to USGS M2M if configured
        m2m_paths: List[str] = []
        try:
            if (
                getattr(self.cfg, "usgs", None)
                and self.cfg.usgs.username
                and self.cfg.usgs.password
            ):
                if USGSM2MClient is None:
                    raise RuntimeError("USGS M2M client not available.")
                # Convert tile_id 'PPP RRR' to path/row
                p = int(tile_id[:3])
                r = int(tile_id[3:6])
                client = USGSM2MClient(
                    self.cfg.usgs.username,
                    self.cfg.usgs.password,
                    endpoint=self.cfg.usgs.endpoint,
                )
                scenes = client.search_scenes_wrs2(
                    self.cfg.usgs.dataset,
                    p,
                    r,
                    start,
                    end,
                    node=self.cfg.usgs.node,
                    max_results=max_files or 100,
                )
                if scenes:
                    entity_ids = [
                        s.get("entityId") or s.get("entity_id")
                        for s in scenes
                        if s.get("entityId") or s.get("entity_id")
                    ]
                    entity_ids = [e for e in entity_ids if e]
                    if entity_ids:
                        options = client.get_download_options(
                            self.cfg.usgs.dataset, entity_ids, node=self.cfg.usgs.node
                        )
                        # Pick first available product per scene (simple heuristic)
                        products = []
                        for opt in options:
                            # opt is per-entity list in some responses; normalize
                            if (
                                isinstance(opt, dict)
                                and opt.get("entityId")
                                and opt.get("products")
                            ):
                                for prod in opt["products"]:
                                    if prod.get("available"):
                                        products.append(
                                            {
                                                "datasetName": self.cfg.usgs.dataset,
                                                "entityId": opt["entityId"],
                                                "productId": prod.get("id")
                                                or prod.get("productId"),
                                            }
                                        )
                                        break
                        if products:
                            downloads = client.request_download(
                                self.cfg.usgs.dataset, products, node=self.cfg.usgs.node
                            )
                            m2m_paths = client.download_files(downloads, local_dir)
                            logger.info(
                                f"Downloaded {len(m2m_paths)} file(s) from USGS M2M"
                            )
                            return m2m_paths
                logger.info("No scenes available from USGS M2M for given criteria.")
            else:
                logger.info("USGS credentials not configured; skipping M2M fetch.")
        except Exception as e:
            logger.warning(f"USGS M2M fetch failed: {e}")

        return []

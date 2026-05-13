from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

import pandas as pd

from lib.cog import ensure_pyarrow
from lib.s3_io import download_s3_uri, parse_s3_uri, s3_uri_exists, upload_file_to_s3


RUN_LOG_COLUMNS = [
    "run_id",
    "pipeline",
    "tile",
    "run_tag",
    "status",
    "started_at_utc",
    "finished_at_utc",
    "requested_start_yyyymmdd",
    "requested_end_yyyymmdd",
    "effective_start_yyyymmdd",
    "effective_end_yyyymmdd",
    "lookback_years",
    "cloud_max",
    "ndvi_products",
    "sr_products",
    "target_epsg",
    "resolution",
    "chunk",
    "strong_threshold",
    "clear_threshold",
    "min_area_ha",
    "dry_run",
    "rebase",
    "run_manifest_uri",
    "s3_bucket",
    "s3_prefix",
    "error_message",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_run_log_uri(bucket: str, prefix: str) -> str:
    prefix = prefix.strip("/")
    return f"s3://{bucket}/{prefix}/runs/optimised_eds_runs.parquet"


def _empty_run_log_df() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in RUN_LOG_COLUMNS})


def load_run_log(run_log_uri: str, cache_dir: Path) -> pd.DataFrame:
    """Load the run log parquet from S3 or local path.

    Uses a local cache file under cache_dir.
    """
    ensure_pyarrow()
    cache_dir.mkdir(parents=True, exist_ok=True)

    local_path = cache_dir / "optimised_eds_runs.parquet"

    if run_log_uri.startswith("s3://"):
        if not s3_uri_exists(run_log_uri):
            return _empty_run_log_df()
        download_s3_uri(run_log_uri, str(local_path))
        df = pd.read_parquet(str(local_path))
    else:
        p = Path(run_log_uri)
        if not p.exists():
            return _empty_run_log_df()
        df = pd.read_parquet(str(p))

    for c in RUN_LOG_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[RUN_LOG_COLUMNS].copy()


def save_run_log(df: pd.DataFrame, run_log_uri: str, cache_dir: Path) -> None:
    ensure_pyarrow()
    cache_dir.mkdir(parents=True, exist_ok=True)

    local_path = cache_dir / "optimised_eds_runs.parquet"
    out = df.copy()
    for c in RUN_LOG_COLUMNS:
        if c not in out.columns:
            out[c] = None
    out = out[RUN_LOG_COLUMNS]
    out.to_parquet(str(local_path), index=False)

    if run_log_uri.startswith("s3://"):
        b, k = parse_s3_uri(run_log_uri)
        upload_file_to_s3(local_path=str(local_path), bucket=b, key=k)
    else:
        Path(run_log_uri).parent.mkdir(parents=True, exist_ok=True)
        Path(str(local_path)).replace(run_log_uri)


def new_run_row(
    *,
    tile: str,
    run_tag: str,
    requested_start_yyyymmdd: str,
    requested_end_yyyymmdd: str,
    effective_start_yyyymmdd: str,
    effective_end_yyyymmdd: str,
    lookback_years: int,
    cloud_max: float,
    ndvi_products: list[str],
    sr_products: list[str],
    target_epsg: int,
    resolution: float,
    chunk: int,
    strong_threshold: int,
    clear_threshold: int,
    min_area_ha: float,
    dry_run: bool,
    rebase: bool,
    run_manifest_uri: str,
    s3_bucket: str,
    s3_prefix: str,
    pipeline: str = "optimised_processing",
) -> Dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "pipeline": pipeline,
        "tile": tile,
        "run_tag": run_tag,
        "status": "running",
        "started_at_utc": utc_now_iso(),
        "finished_at_utc": None,
        "requested_start_yyyymmdd": requested_start_yyyymmdd,
        "requested_end_yyyymmdd": requested_end_yyyymmdd,
        "effective_start_yyyymmdd": effective_start_yyyymmdd,
        "effective_end_yyyymmdd": effective_end_yyyymmdd,
        "lookback_years": int(lookback_years),
        "cloud_max": float(cloud_max),
        "ndvi_products": " ".join(ndvi_products),
        "sr_products": " ".join(sr_products),
        "target_epsg": int(target_epsg),
        "resolution": float(resolution),
        "chunk": int(chunk),
        "strong_threshold": int(strong_threshold),
        "clear_threshold": int(clear_threshold),
        "min_area_ha": float(min_area_ha),
        "dry_run": bool(dry_run),
        "rebase": bool(rebase),
        "run_manifest_uri": run_manifest_uri,
        "s3_bucket": s3_bucket,
        "s3_prefix": s3_prefix,
        "error_message": None,
    }


def finish_run_row(
    row: Dict[str, Any],
    *,
    status: str,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    out = dict(row)
    out["status"] = status
    out["finished_at_utc"] = utc_now_iso()
    out["error_message"] = error_message
    return out

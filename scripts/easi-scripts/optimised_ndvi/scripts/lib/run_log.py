from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

import pandas as pd

from lib.cog import ensure_pyarrow
from lib.s3_io import (
    download_s3_uri,
    parse_s3_uri,
    s3_uri_exists,
    upload_file_to_s3,
)


RUN_LOG_COLUMNS = [
    "run_id",
    "pipeline",
    "tile",
    "status",
    "started_at_utc",
    "finished_at_utc",
    "start_yyyymmdd",
    "end_yyyymmdd",
    "scenes_total",
    "scenes_processed",
    "scenes_skipped_existing",
    "scenes_failed",
    "dry_run",
    "rebase",
    "s3_bucket",
    "s3_prefix",
    "error_message",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_run_log_uri(bucket: str, prefix: str) -> str:
    prefix = prefix.strip("/")
    return f"s3://{bucket}/{prefix}/runs/optimised_ndvi_runs.parquet"


def _empty_run_log_df() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in RUN_LOG_COLUMNS})


def load_run_log(run_log_uri: str, cache_dir: Path) -> pd.DataFrame:
    """Load the run log parquet from S3 or local path.

    Uses a local cache file under cache_dir.
    """
    ensure_pyarrow()
    cache_dir.mkdir(parents=True, exist_ok=True)

    local_path = cache_dir / "optimised_ndvi_runs.parquet"

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

    # Ensure all expected columns exist (forward-compatible).
    for c in RUN_LOG_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[RUN_LOG_COLUMNS].copy()


def save_run_log(df: pd.DataFrame, run_log_uri: str, cache_dir: Path) -> None:
    ensure_pyarrow()
    cache_dir.mkdir(parents=True, exist_ok=True)

    local_path = cache_dir / "optimised_ndvi_runs.parquet"
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
    start_yyyymmdd: str,
    end_yyyymmdd: str,
    dry_run: bool,
    rebase: bool,
    s3_bucket: str,
    s3_prefix: str,
    pipeline: str = "optimised_ndvi",
) -> Dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "pipeline": pipeline,
        "tile": tile,
        "status": "running",
        "started_at_utc": utc_now_iso(),
        "finished_at_utc": None,
        "start_yyyymmdd": start_yyyymmdd,
        "end_yyyymmdd": end_yyyymmdd,
        "scenes_total": 0,
        "scenes_processed": 0,
        "scenes_skipped_existing": 0,
        "scenes_failed": 0,
        "dry_run": bool(dry_run),
        "rebase": bool(rebase),
        "s3_bucket": s3_bucket,
        "s3_prefix": s3_prefix,
        "error_message": None,
    }


def finish_run_row(
    row: Dict[str, Any],
    *,
    status: str,
    scenes_total: int,
    scenes_processed: int,
    scenes_skipped_existing: int,
    scenes_failed: int,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    out = dict(row)
    out["status"] = status
    out["finished_at_utc"] = utc_now_iso()
    out["scenes_total"] = int(scenes_total)
    out["scenes_processed"] = int(scenes_processed)
    out["scenes_skipped_existing"] = int(scenes_skipped_existing)
    out["scenes_failed"] = int(scenes_failed)
    out["error_message"] = error_message
    return out


def last_success_end_date(df: pd.DataFrame, tile: str) -> Optional[str]:
    if df is None or df.empty:
        return None
    sub = df[(df["tile"].astype(str).str.lower() == tile.lower()) & (df["status"] == "success")]
    if sub.empty:
        return None
    # end_yyyymmdd should be an 8-digit string.
    vals = [str(v) for v in sub["end_yyyymmdd"].dropna().tolist()]
    vals = [v for v in vals if len(v) >= 8]
    if not vals:
        return None
    return max(v[:8] for v in vals)

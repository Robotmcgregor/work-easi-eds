# ------------------------------------------------------------------------------
# MIT License

# Copyright (c) 2026 Robert McGregor

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ------------------------------------------------------------------------------

"""
run_log.py: EDS Pipeline Run Log Management
-------------------------------------------

This script provides utility functions for managing the run log of the EDS (Early Detection System)
processing pipeline. The run log records metadata and status for every pipeline execution, including
parameters, start/end times, and error messages. It supports both local and S3 storage, and ensures
consistent tracking of all runs for auditing, debugging, and reproducibility.

Why this exists:
        - To provide a single source of truth for all EDS pipeline runs.
        - To enable robust tracking, error reporting, and post-run analysis.
        - To support both local and cloud-based workflows.

Which pipeline calls it:
        - This module is called by the main EDS processing pipeline (e.g., eds_master_pipeline_optimised.py)
            and any related scripts that need to record or update run metadata.
        - It is not intended to be run directly, but imported and used by pipeline orchestration scripts.
"""

# This script manages the run log for the EDS processing pipeline.
# It handles saving, loading, and updating the log of all pipeline runs.
# The log records what was run, when, with what settings, and the outcome.
from __future__ import annotations


# Standard library imports
from datetime import datetime, timezone 
from pathlib import Path
from typing import Any, Dict, Optional
import uuid
import pandas as pd

# Local imports for S3 and file utilities
from lib.cog import ensure_pyarrow  # Makes sure pyarrow is available for parquet files
from lib.s3_io import download_s3_uri, parse_s3_uri, s3_uri_exists, upload_file_to_s3


 # Set up Run log columns
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



# Get the current UTC time as a string
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()



# Build the default S3 URI for the run log file, given a bucket and prefix.
def default_run_log_uri(bucket: str, prefix: str) -> str:
    prefix = prefix.strip("/")
    return f"s3://{bucket}/{prefix}/runs/optimised_eds_runs.parquet"



# Create an empty DF with RUN_LOG_COLUMNS - used for the run log.
def _empty_run_log_df() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in RUN_LOG_COLUMNS})



# Load the run log as a DF, from S3 or a local file.
def load_run_log(run_log_uri: str, cache_dir: Path) -> pd.DataFrame:
    """Load the run log parquet from S3 or local path. Uses a local cache file under cache_dir."""
    ensure_pyarrow()  # Make sure pyarrow is available for reading parquet files
    cache_dir.mkdir(parents=True, exist_ok=True)  # Make sure the cache directory exists

    local_path = cache_dir / "optimised_eds_runs.parquet"  # Path to the local cache file

    if run_log_uri.startswith("s3://"):
        # If the run log is on S3, download it to the cache if it exists
        if not s3_uri_exists(run_log_uri):
            return _empty_run_log_df()
        download_s3_uri(run_log_uri, str(local_path))
        df = pd.read_parquet(str(local_path))
    else:
        # Otherwise, load from a local file path
        p = Path(run_log_uri)
        if not p.exists():
            return _empty_run_log_df()
        df = pd.read_parquet(str(p))

    # Make sure all expected columns are present
    for c in RUN_LOG_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[RUN_LOG_COLUMNS].copy()



# Save the run log DF to S3 or a local file, updating the cache as well.
def save_run_log(df: pd.DataFrame, run_log_uri: str, cache_dir: Path) -> None:
    ensure_pyarrow()  # Make sure pyarrow is available for writing parquet files
    cache_dir.mkdir(parents=True, exist_ok=True)  # Make sure the cache directory exists

    local_path = cache_dir / "optimised_eds_runs.parquet"  # Path to the local cache file
    out = df.copy()
    # Ensure all expected columns are present
    for c in RUN_LOG_COLUMNS:
        if c not in out.columns:
            out[c] = None
    out = out[RUN_LOG_COLUMNS]
    out.to_parquet(str(local_path), index=False)  # Save to local cache

    if run_log_uri.startswith("s3://"):
        # If the run log is on S3, upload the cache file to S3
        b, k = parse_s3_uri(run_log_uri)
        upload_file_to_s3(local_path=str(local_path), bucket=b, key=k)
    else:
        # Otherwise, move the cache file to the final local destination
        Path(run_log_uri).parent.mkdir(parents=True, exist_ok=True)
        Path(str(local_path)).replace(run_log_uri)



# Create a new row (dictionary) for a pipeline run, with all required metadata.
# This is used to record the start of a new run in the log.
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
        "run_id": str(uuid.uuid4()),  # Unique ID for this run
        "pipeline": pipeline,  # Name of the pipeline
        "tile": tile,  # Tile being processed
        "run_tag": run_tag,  # Tag for this run
        "status": "running",  # Initial status
        "started_at_utc": utc_now_iso(),  # Start time
        "finished_at_utc": None,  # Will be filled in when run finishes
        "requested_start_yyyymmdd": requested_start_yyyymmdd,  # User-requested start date
        "requested_end_yyyymmdd": requested_end_yyyymmdd,  # User-requested end date
        "effective_start_yyyymmdd": effective_start_yyyymmdd,  # Actual start date used
        "effective_end_yyyymmdd": effective_end_yyyymmdd,  # Actual end date used
        "lookback_years": int(lookback_years),  # How many years to look back for baseline
        "cloud_max": float(cloud_max),  # Max cloud cover allowed
        "ndvi_products": " ".join(ndvi_products),  # NDVI products used (as string)
        "sr_products": " ".join(sr_products),  # SR products used (as string)
        "target_epsg": int(target_epsg),  # Output projection
        "resolution": float(resolution),  # Output pixel size
        "chunk": int(chunk),  # Chunk size for processing
        "strong_threshold": int(strong_threshold),  # Threshold for strong detections
        "clear_threshold": int(clear_threshold),  # Threshold for clear detections
        "min_area_ha": float(min_area_ha),  # Minimum area (hectares)
        "dry_run": bool(dry_run),  # If True, run is a dry run (no outputs)
        "rebase": bool(rebase),  # If True, overwrite existing outputs
        "run_manifest_uri": run_manifest_uri,  # Where the manifest is stored
        "s3_bucket": s3_bucket,  # S3 bucket used
        "s3_prefix": s3_prefix,  # S3 prefix used
        "error_message": None,  # Will be filled in if run fails
    }



# Update a run log row to mark it as finished, with status and error message if any.
def finish_run_row(
    row: Dict[str, Any],
    *,
    status: str,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    out = dict(row)  # Copy the row so we don't modify the original
    out["status"] = status  # Set the final status (e.g. 'success', 'failed')
    out["finished_at_utc"] = utc_now_iso()  # Set the finish time
    out["error_message"] = error_message  # Record any error message
    return out

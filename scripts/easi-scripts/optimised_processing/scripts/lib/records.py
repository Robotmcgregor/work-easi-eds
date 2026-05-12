from __future__ import annotations
import io
import pandas as pd
import boto3
from datetime import datetime, timezone

def _records_key(prefix: str, tile: str) -> str:
    return f"{prefix}/records/{tile}/inventory.csv".lstrip("/")

def upsert_inventory_row(bucket: str, prefix: str, tile: str, date: str, platform: str,
                         status: str, output_key: str, cloud: float, error: str = "") -> None:
    """
    Simple “DB-lite” inventory:
      - stored as CSV per tile in S3
      - append-only is fine initially; later you can dedupe by (date, platform)
    """
    s3 = boto3.client("s3")
    key = _records_key(prefix, tile)

    now = datetime.now(timezone.utc).isoformat()

    new_row = pd.DataFrame([{
        "tile": tile,
        "date": date,
        "platform": platform,
        "cloud": cloud,
        "status": status,
        "output_key": output_key,
        "error": error,
        "updated_at": now,
    }])

    # Try to load existing CSV
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        old = pd.read_csv(obj["Body"])
        df = pd.concat([old, new_row], ignore_index=True)
    except Exception:
        df = new_row

    # Save back to S3
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue().encode("utf-8"))

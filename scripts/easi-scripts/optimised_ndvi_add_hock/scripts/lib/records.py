from __future__ import annotations
import io
import pandas as pd
import boto3
from datetime import datetime, timezone

def _records_key(prefix: str, tile: str) -> str:
    # build the s3 key where the inventory csv lives
    # strip leading slash just in case
    return f"{prefix}/records/{tile}/inventory.csv".lstrip("/")


def upsert_inventory_row(
    bucket: str,
    prefix: str,
    tile: str,
    date: str,
    platform: str,
    status: str,
    output_key: str,
    cloud: float,
    error: str = "",
) -> None:
    """
    very basic inventory thing:
      - stored as a csv per tile in s3
      - we just keep appending rows for now
      - later can clean it up if needed
    """

    # make s3 client
    s3 = boto3.client("s3")

    # work out where the csv should be
    key = _records_key(prefix, tile)

    # current time in utc so we know when this was written
    now = datetime.now(timezone.utc).isoformat()

    # create a single-row dataframe for this update
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

    # try to load the existing csv from s3
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        old = pd.read_csv(obj["Body"])

        # append the new row to whatever was there before
        df = pd.concat([old, new_row], ignore_index=True)
    except Exception:
        # if the file doesnt exist or cant be read, just start fresh
        df = new_row

    # write the csv back to s3
    buf = io.StringIO()
    df.to_csv(buf, index=False)

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue().encode("utf-8"),
    )
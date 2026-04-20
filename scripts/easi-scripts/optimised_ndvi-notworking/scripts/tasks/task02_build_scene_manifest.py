from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import pandas as pd

from lib.s3_io import (
    s3_uri_exists,
    download_s3_uri,
    upload_file_to_s3,
    parse_s3_uri,
)

# Manifest columns REQUIRED by ndvi_master_pipeline + task03
REQUIRED_COLS = ["date", "platform", "cloud", "red_path", "nir_path", "ffmask_path", "target_epsg"]

# filenames we create during download stage (based on your naming convention)
# lztmre_<tile>_<yyyymmdd>_<datatype>_<epsg>.tif
FNAME_RE = re.compile(
    r"^lztmre_(?P<tile>p\d{3}r\d{3})_(?P<date>\d{8})_(?P<dtype>[a-z0-9_]+)_(?P<epsg>\d+)\.tif$"
)

# Only what we need for NDVI
NEEDED_DTYPES = {"nbart_red", "nbart_nir", "oa_fmask"}


def load_or_build_manifest(
    tile: str,
    manifest_uri: str,
    source_dir: str | None,
    cloud_max: float,
    start_date: str | None,
    end_date: str | None,
    work_dir: str,
    **_ignored,
) -> pd.DataFrame:

    ...

    """
    Manifest stored as Parquet (local or S3).

    If missing, build it by:
      - running ls89_fc_sr_pipeline.py (SR-only, optional download)
      - scanning downloaded SR assets for nbart_red, nbart_nir, oa_fmask
      - writing parquet manifest (and uploading to S3 if manifest_uri is s3://)

    Notes:
      - This avoids STAC_URL/TILE_BBOX entirely.
      - start_date/end_date should be YYYYMMDD OR YYYY-MM-DD; we normalise.
    """
    tile = tile.lower()
    cache_dir = Path(work_dir) / "manifests"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_cache = cache_dir / f"{tile}_manifest.parquet"

    # 1) load if exists
    if manifest_uri.startswith("s3://"):
        if s3_uri_exists(manifest_uri):
            download_s3_uri(manifest_uri, str(local_cache))
            df = _read_parquet(str(local_cache))
            return _finalise(df, cloud_max, start_date, end_date)
    else:
        p = Path(manifest_uri)
        if p.exists():
            df = _read_parquet(str(p))
            return _finalise(df, cloud_max, start_date, end_date)

    # 2) build if missing
    # We build by running your existing ls89_fc_sr_pipeline.py and then scanning outputs.
    if not source_dir:
        # If source_dir isn't provided, choose a sensible default under work_dir
        source_dir = str(Path(work_dir) / "ls89_cache")

    Path(source_dir).mkdir(parents=True, exist_ok=True)

    # Defaults: if caller didn't pass these, read env or use common paths
    if ls89_pipeline is None:
        # You can override this from ndvi_master_pipeline args later
        ls89_pipeline = os.environ.get(
            "LS89_PIPELINE",
            "/home/jovyan/work-easi-eds/scripts/easi-scripts/eds_lsat_collection/ls89_fc_sr_pipeline.py",
        )

    if tile_shp is None:
        tile_shp = os.environ.get(
            "EDS_TILE_SHP",
            "/home/jovyan/assets/eds_lsat_grid_min_max.shp",
        )

    # Run ls89 pipeline (SR only) to ensure SR assets exist locally to scan
    _run_ls89_pipeline(
        ls89_pipeline=ls89_pipeline,
        tile_shp=tile_shp,
        tile=tile,
        span_years=span_years,
        start_date=start_date,
        end_date=end_date,
        cloud_max=cloud_max,
        out_dir=source_dir,
        run_download=run_download,
    )

    # Scan for nbart_red, nbart_nir, oa_fmask for this tile
    df = build_manifest_from_download_dir(tile=tile, download_root=source_dir)

    # Add cloud if unknown (pipeline may not provide per-file cloud here)
    # Keep column for inventory consistency; default to NaN if not available.
    if "cloud" not in df.columns:
        df["cloud"] = float("nan")

    df = _finalise(df, cloud_max, start_date, end_date)

    # 3) write + upload
    _write_parquet(df, str(local_cache))
    if manifest_uri.startswith("s3://"):
        b, k = parse_s3_uri(manifest_uri)
        upload_file_to_s3(local_path=str(local_cache), bucket=b, key=k)
    else:
        Path(manifest_uri).parent.mkdir(parents=True, exist_ok=True)
        Path(str(local_cache)).replace(manifest_uri)

    return df


def _normalise_date(d: str | None) -> str | None:
    if not d:
        return None
    d = d.strip()
    # allow YYYY-MM-DD or YYYYMMDD
    if "-" in d:
        parts = d.split("-")
        if len(parts) == 3:
            return f"{parts[0]}{parts[1]}{parts[2]}"
    return d


def _run_ls89_pipeline(
    ls89_pipeline: str,
    tile_shp: str,
    tile: str,
    span_years: int,
    start_date: str | None,
    end_date: str | None,
    cloud_max: float,
    out_dir: str,
    run_download: bool,
) -> None:
    """
    Calls your existing ls89_fc_sr_pipeline.py to ensure SR data exists locally.

    This assumes your pipeline supports flags similar to:
      --tile-shp, --tile-id, --span-years, --run-download, --sr-only

    If your exact flags differ, tweak this function only.
    """
    start_yyyymmdd = _normalise_date(start_date)
    end_yyyymmdd = _normalise_date(end_date)

    cmd = [
        "python",
        ls89_pipeline,
        "--tile-shp",
        tile_shp,
        "--tile-id",
        tile,
        "--span-years",
        str(span_years),
        "--sr-only",
    ]

    # If your ls89 pipeline supports season core args, you can map start/end here.
    # Leaving them out is OK; span-years will constrain.
    # If you DO have date flags in ls89 pipeline, add them here.
    # We keep cloud_max here for future use (query filtering) if pipeline supports it.
    if run_download:
        cmd.append("--run-download")

    # Optional: tell it where to store downloads if supported
    # If your ls89 pipeline has an output-dir flag, add it here:
    # cmd += ["--out-dir", out_dir]

    print("[INFO] Running LS89 pipeline for SR discovery/download:")
    print(" ".join(cmd))

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        raise RuntimeError(f"ls89 pipeline failed (rc={res.returncode}). See output above.")


def build_manifest_from_download_dir(tile: str, download_root: str) -> pd.DataFrame:
    """
    Scan a local directory tree for files named:
      lztmre_<tile>_<yyyymmdd>_<datatype>_<epsg>.tif

    We require nbart_red + nbart_nir + oa_fmask per (date, epsg).
    """
    tile = tile.lower()
    root = Path(download_root)

    # map (date, epsg) -> dict(dtype -> path)
    bucket: dict[tuple[str, int], dict[str, str]] = {}

    for p in root.rglob("lztmre_*.tif"):
        m = FNAME_RE.match(p.name)
        if not m:
            continue
        if m.group("tile").lower() != tile:
            continue
        dtype = m.group("dtype")
        if dtype not in NEEDED_DTYPES:
            continue

        date = m.group("date")
        epsg = int(m.group("epsg"))
        key = (date, epsg)
        bucket.setdefault(key, {})[dtype] = str(p)

    rows = []
    for (date, epsg), d in sorted(bucket.items()):
        if not all(k in d for k in NEEDED_DTYPES):
            # incomplete set; skip
            continue

        # platform is not encoded in your filename convention;
        # if you want it, you must include it in directory layout or add a sidecar.
        # For now default to "LS" and you can refine later.
        # If your download pipeline stores L8/L9 in the path, we can infer it.
        platform = infer_platform_from_path(d["nbart_red"]) or "LS"

        rows.append({
            "date": date,
            "platform": platform,
            "cloud": float("nan"),
            "red_path": d["nbart_red"],
            "nir_path": d["nbart_nir"],
            "ffmask_path": d["oa_fmask"],   # oa_fmask on input
            "target_epsg": epsg,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(
            f"No complete (nbart_red, nbart_nir, oa_fmask) sets found for {tile} under {download_root}.\n"
            "Check that ls89 pipeline actually downloaded SR and wrote lztmre_* files into that folder tree."
        )
    return df


def infer_platform_from_path(path: str) -> str | None:
    p = path.lower()
    if "ls8" in p or "landsat8" in p:
        return "L8"
    if "ls9" in p or "landsat9" in p:
        return "L9"
    return None


def _finalise(df: pd.DataFrame, cloud_max: float, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Manifest missing columns: {missing}. Have: {list(df.columns)}")

    out = df.copy()

    # cloud filter (if cloud is NaN we keep it)
    out["cloud"] = pd.to_numeric(out["cloud"], errors="coerce")
    if out["cloud"].notna().any():
        out = out[(out["cloud"].isna()) | (out["cloud"] <= float(cloud_max))]

    # date filter (normalize to YYYYMMDD)
    start_n = _normalise_date(start_date)
    end_n = _normalise_date(end_date)
    out["date"] = out["date"].astype(str)
    if start_n:
        out = out[out["date"] >= start_n]
    if end_n:
        out = out[out["date"] <= end_n]

    out = out.sort_values(["platform", "date", "target_epsg"]).reset_index(drop=True)
    return out


def _read_parquet(path: str) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)
    except Exception as e:
        raise RuntimeError(
            f"Failed to read parquet: {path}. "
            "Install pyarrow in this env (recommended). "
            f"Original error: {e}"
        )


def _write_parquet(df: pd.DataFrame, path: str) -> None:
    try:
        df.to_parquet(path, index=False)
    except Exception as e:
        raise RuntimeError(
            f"Failed to write parquet: {path}. "
            "Install pyarrow in this env (recommended). "
            f"Original error: {e}"
        )

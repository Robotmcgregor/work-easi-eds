from pathlib import Path
from datetime import date, timedelta
import argparse

import pandas as pd
import datacube


# -----------------------------
# Helper functions
# -----------------------------

def infer_platform(md: dict) -> str | None:
    """
    Try to infer Landsat platform from metadata.
    Returns something like 'landsat-8', 'landsat-9', 'LC08', 'LC09', or None.
    """
    # 1) Explicit platform/satellite fields
    for key in ("platform", "satellite", "eo:platform", "odc:platform"):
        val = md.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # 2) landsat_product_id (common pattern: LC08, LC09, LE07, LT05, ...)
    lp = md.get("landsat_product_id") or md.get("label")
    if isinstance(lp, str):
        if lp.startswith("LC08"):
            return "LC08"
        if lp.startswith("LC09"):
            return "LC09"

    # 3) lineage / source_datasets keys (FC often stores lineage here)
    lineage = md.get("lineage", {})
    src = lineage.get("source_datasets", md.get("source_datasets", {}))
    if isinstance(src, dict):
        for k in src.keys():
            k_low = k.lower()
            if "ls8" in k_low:
                return "landsat-8"
            if "ls9" in k_low:
                return "landsat-9"

    return None


def dataset_to_row(ds, product: str) -> dict:
    """
    Convert a Datacube Dataset -> one row for our summary tables.
    """
    md = ds.metadata_doc
    props = md.get("properties", {}) or {}

    # time
    try:
        time = ds.center_time
    except AttributeError:
        time = md.get("time")
    time = pd.to_datetime(str(time))

    # region_code -> path/row (e.g. '104070' -> 104, 70)
    region_code = (
        md.get("region_code")
        or getattr(ds.metadata, "region_code", None)
        or props.get("odc:region_code")
        or None
    )
    path = row = None
    if region_code is not None:
        rc_str = str(region_code)
        if len(rc_str) >= 6:
            try:
                path = int(rc_str[:3])
                row = int(rc_str[3:6])
            except Exception:
                path = row = None

    # --- cloud cover: look in top-level THEN in properties ---
    cc = md.get("cloud_cover", None)
    if cc is None:
        cc = props.get("eo:cloud_cover", props.get("cloud_cover"))
    cloud_cover = cc

    # Landsat product / label
    landsat_id = (
        md.get("landsat_product_id")
        or md.get("label")
        or props.get("landsat:product_id")
        or md.get("id")
        or None
    )

    platform_guess = infer_platform(md)  # you can keep your improved version here

    return {
        "product": product,
        "time": time,
        "date": time.date(),
        "region_code": region_code,
        "path": path,
        "row": row,
        "cloud_cover": cloud_cover,
        "landsat_product_id": landsat_id,
        "platform_guess": platform_guess,
        "id": str(ds.id),
    }


def search_product(dc, product: str, lat_range, lon_range, time_range):
    """
    Use dc.find_datasets to get all datasets for a product in a given
    time + spatial window.
    """
    ds_list = dc.find_datasets(
        product=product,
        latitude=lat_range,
        longitude=lon_range,
        time=time_range,
    )
    return ds_list

def run_query(
    start_date: str,
    end_date: str,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    span_years: int | None = None,
    tile_path: int | None = None,
    tile_row: int | None = None,
    tile_id: str | None = None,
):
    # ...
    if tile_id and (tile_path is None or tile_row is None):
        tid = tile_id.strip().lower()
        if tid.startswith("p") and "r" in tid:
            p_str, r_str = tid[1:].split("r")
            tile_path = int(p_str)
            tile_row = int(r_str)
        else:
            raise ValueError(f"Unrecognised tile_id format: {tile_id}")

    print(f"[DEBUG] Tile filter: tile_path={tile_path}, tile_row={tile_row}, tile_id={tile_id}")

    def apply_tile_filter(df: pd.DataFrame, label: str) -> pd.DataFrame:
        if df.empty:
            print(f"[DEBUG] {label}: empty before tile filter")
            return df
        if tile_path is None or tile_row is None:
            print(f"[DEBUG] {label}: no tile filter applied (no path/row provided)")
            return df

        before = len(df)
        df = df.loc[
            (df["path"] == int(tile_path)) &
            (df["row"]  == int(tile_row))
        ].copy()
        after = len(df)
        print(
            f"[DEBUG] {label}: {before} → {after} rows after tile filter "
            f"(path={tile_path}, row={tile_row})"
        )
        return df

    """
    Main driver:
    - start_date/end_date: 'YYYY-MM-DD'
    - lat_min/max, lon_min/max: floats defining bounding box
    """

    # ------------------------------------------------------------------
    # 0. Normalise inputs and set up paths
    # ------------------------------------------------------------------
    t_start = pd.to_datetime(start_date)
    t_end = pd.to_datetime(end_date)

    # Datacube likes (min, max) ordering
    lat_range = (min(lat_min, lat_max), max(lat_min, lat_max))
    lon_range = (min(lon_min, lon_max), max(lon_min, lon_max))
    time_range = (t_start, t_end)

    # ------------------------------------------------------------------
    # Tile filter from tile_id or path/row
    # ------------------------------------------------------------------
    # If tile_id like "p104r070" was given, parse it when path/row missing
    if tile_id and (tile_path is None or tile_row is None):
        tid = tile_id.strip().lower()
        # very simple parser: "p104r070"
        if tid.startswith("p") and "r" in tid:
            p_str, r_str = tid[1:].split("r")
            tile_path = int(p_str)
            tile_row = int(r_str)
        else:
            raise ValueError(f"Unrecognised tile_id format: {tile_id}")

    print(f"[DEBUG] Tile filter: tile_path={tile_path}, tile_row={tile_row}, tile_id={tile_id}")

    def apply_tile_filter(df: pd.DataFrame, label: str) -> pd.DataFrame:
        """
        Restrict a dataframe to a single path/row if requested.
        Assumes df has 'path' and 'row' integer columns from dataset_to_row().
        """
        if df.empty:
            print(f"[DEBUG] {label}: empty before tile filter")
            return df

        if tile_path is None or tile_row is None:
            print(f"[DEBUG] {label}: no tile filter applied (no path/row provided)")
            return df

        before = len(df)
        df = df.loc[
            (df["path"] == int(tile_path)) &
            (df["row"]  == int(tile_row))
        ].copy()
        after = len(df)

        print(
            f"[DEBUG] {label}: {before} → {after} rows after tile filter "
            f"(path={tile_path}, row={tile_row})"
        )
        return df

    # Where to write outputs
    span_tag = f"{t_start:%Y%m%d}{t_end:%Y%m%d}"
    out_root = Path.home() / "scratch" / "eds" / "queries" / span_tag
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"Output directory: {out_root}")

    # placeholders so later checks are safe even if no data found
    df_sr_cc40 = pd.DataFrame()
    df_fc_filtered = pd.DataFrame()

    # ------------------------------------------------------------------
    # 1. Connect to Datacube
    # ------------------------------------------------------------------
    dc = datacube.Datacube(app="eds_ls8_ls9_fc_sr_query")

    # ------------------------------------------------------------------
    # 2. Search SR (Landsat 8 + 9 ARD) products
    # ------------------------------------------------------------------
    sr_products = ["ga_ls8c_ard_3", "ga_ls9c_ard_3"]
    sr_rows = []

    for prod in sr_products:
        ds_list = search_product(dc, prod, lat_range, lon_range, time_range)
        print(f"{prod} datasets found: {len(ds_list)}")
        for ds in ds_list:
            sr_rows.append(dataset_to_row(ds, prod))

    df_sr = pd.DataFrame(sr_rows)
    if df_sr.empty:
        print("No SR datasets found in the given window.")
        df_sr_cc40 = pd.DataFrame()
    else:
        # already LS8/9 by product; now apply CC filter
        df_sr["cloud_cover"] = pd.to_numeric(df_sr["cloud_cover"], errors="coerce")
        df_sr_cc40 = (
            df_sr
            .dropna(subset=["cloud_cover"])
            .loc[df_sr["cloud_cover"] < 40]  # CC < 40
            .copy()
            .reset_index(drop=True)
        )

        before_tile = len(df_sr_cc40)
        df_sr_cc40 = apply_tile_filter(df_sr_cc40, label="SR CC<40")
        after_tile = len(df_sr_cc40)

        print(
            f"SR rows total (all LS8/9): {len(df_sr)}, "
            f"after cloud_cover < 40: {before_tile}, "
            f"after tile filter: {after_tile}"
        )

        sr_csv = out_root / "sr_table.csv"
        df_sr_cc40.to_csv(sr_csv, index=False)
        print(f"SR table written to: {sr_csv}")

    # ------------------------------------------------------------------
    # 3. Search FC product (ga_ls_fc_3), then tile filter
    # ------------------------------------------------------------------
    fc_product = "ga_ls_fc_3"
    fc_rows = []

    ds_fc_list = search_product(dc, fc_product, lat_range, lon_range, time_range)
    print(f"{fc_product} datasets found: {len(ds_fc_list)}")

    for ds in ds_fc_list:
        fc_rows.append(dataset_to_row(ds, fc_product))

    df_fc = pd.DataFrame(fc_rows)
    if df_fc.empty:
        print("No FC datasets found.")
        df_fc_filtered = pd.DataFrame()
    else:
        df_fc_filtered = df_fc.copy().reset_index(drop=True)
        print(f"FC rows total (all platforms kept at this stage): {len(df_fc_filtered)}")

        df_fc_filtered = apply_tile_filter(df_fc_filtered, label="FC all")

        fc_csv = out_root / "fc_table.csv"
        df_fc_filtered.to_csv(fc_csv, index=False)
        print(f"FC table written to: {fc_csv}")

    # ------------------------------------------------------------------
    # 4. Fmask table (same as SR table, since Fmask is a band in ARD)
    # ------------------------------------------------------------------
    if not df_sr_cc40.empty:
        df_fmask = df_sr_cc40.copy()
        df_fmask["has_fmask_band"] = True   # explicit flag
        fmask_csv = out_root / "fmask_table.csv"
        df_fmask.to_csv(fmask_csv, index=False)
        print(f"Fmask table written to: {fmask_csv}")
    else:
        print("Skipping fmask table (no SR CC<40 rows after tile filter).")

    # ------------------------------------------------------------------
    # 5. Comparison table: match SR + FC on date + path + row
    # ------------------------------------------------------------------
    if not df_sr_cc40.empty and not df_fc_filtered.empty:
        # Ensure we have date/path/row
        for df in (df_sr_cc40, df_fc_filtered):
            if "date" not in df.columns:
                df["date"] = pd.to_datetime(df["time"]).dt.date

        print(f"[DEBUG] SR rows going into comparison: {len(df_sr_cc40)}")
        print(f"[DEBUG] FC rows going into comparison: {len(df_fc_filtered)}")
        print("[DEBUG] Unique SR (path,row):")
        print(df_sr_cc40[["path", "row"]].drop_duplicates().sort_values(["path", "row"]))
        print("[DEBUG] Unique FC (path,row):")
        print(df_fc_filtered[["path", "row"]].drop_duplicates().sort_values(["path", "row"]))

        cols_for_key = [
            "date",
            "path",
            "row",
            "product",
            "cloud_cover",
            "landsat_product_id",
            "platform_guess",
            "id",
        ]

        df_sr_keyed = df_sr_cc40[cols_for_key].rename(
            columns={
                "product": "sr_product",
                "cloud_cover": "sr_cloud_cover",
                "landsat_product_id": "sr_landsat_id",
                "platform_guess": "sr_platform",
                "id": "sr_id",
            }
        )

        df_fc_keyed = df_fc_filtered[cols_for_key].rename(
            columns={
                "product": "fc_product",
                "cloud_cover": "fc_cloud_cover",
                "landsat_product_id": "fc_landsat_id",
                "platform_guess": "fc_platform",
                "id": "fc_id",
            }
        )

        # Optional: deduplicate to one FC per (date,path,row) if needed
        # df_fc_keyed = df_fc_keyed.drop_duplicates(subset=["date", "path", "row"])

        comparison = (
            pd.merge(
                df_sr_keyed,
                df_fc_keyed,
                on=["date", "path", "row"],
                how="inner",
            )
            .sort_values(["date", "path", "row"])
        )

        print(f"[DEBUG] Comparison DataFrame shape: {comparison.shape}")
        print("[DEBUG] First 3 comparison rows:")
        print(comparison.head(3))

        comp_csv = out_root / "comparison_table.csv"
        comparison.to_csv(comp_csv, index=False)
        print(f"Comparison table written to: {comp_csv}")
        print(
            f"Comparison rows: {len(comparison)} "
            "(unique (date,path,row) with SR CC<40 and matching FC, after tile filter)"
        )
    else:
        print("Skipping comparison table (no SR CC<40 or no FC rows after tile filter).")

    print("\n--- Comparison table build complete ---")
    print("Done.")

# -----------------------------
# CLI argument parsing
# -----------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Query LS8/LS9 SR + FC (and Fmask) over a bbox and time span."
    )

    parser.add_argument(
        "--lat-min",
        type=float,
        required=True,
        help="Minimum latitude (south).",
    )
    parser.add_argument(
        "--lat-max",
        type=float,
        required=True,
        help="Maximum latitude (north).",
    )
    parser.add_argument(
        "--lon-min",
        type=float,
        required=True,
        help="Minimum longitude (west).",
    )
    parser.add_argument(
        "--lon-max",
        type=float,
        required=True,
        help="Maximum longitude (east).",
    )

    parser.add_argument(
        "--span-years",
        type=int,
        default=10,
        help="Number of years back from end date (default: 10).",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date 'YYYY-MM-DD'. If omitted, uses today.",
    )

    # 🔹 NEW: tile filters
    parser.add_argument(
        "--tile-id",
        type=str,
        default=None,
        help="Tile ID like 'p104r070'. Optional.",
    )
    parser.add_argument(
        "--tile-path",
        type=int,
        default=None,
        help="WRS path. Optional (used if tile-id not given).",
    )
    parser.add_argument(
        "--tile-row",
        type=int,
        default=None,
        help="WRS row. Optional (used if tile-id not given).",
    )

    return parser.parse_args()



# -----------------------------------------------------
# Main entry point
# -----------------------------------------------------
if __name__ == "__main__":
    args = parse_args()

    # Decide end date
    if args.end_date:
        end_date_dt = pd.to_datetime(args.end_date).date()
    else:
        end_date_dt = date.today()

    # Compute start date from span_years
    try:
        start_date_dt = end_date_dt.replace(year=end_date_dt.year - args.span_years)
    except ValueError:
        start_date_dt = end_date_dt - timedelta(days=365 * args.span_years)

    start_date = start_date_dt.isoformat()
    end_date = end_date_dt.isoformat()

    print(f"Using date span: {start_date} → {end_date} ({args.span_years} years)")
    print(f"Lat range: {args.lat_min} to {args.lat_max}")
    print(f"Lon range: {args.lon_min} to {args.lon_max}")
    print(f"Tile args from CLI: tile_id={args.tile_id}, "
          f"tile_path={args.tile_path}, tile_row={args.tile_row}")

    run_query(
        start_date=start_date,
        end_date=end_date,
        lat_min=args.lat_min,
        lat_max=args.lat_max,
        lon_min=args.lon_min,
        lon_max=args.lon_max,
        span_years=args.span_years,
        tile_path=args.tile_path,
        tile_row=args.tile_row,
        tile_id=args.tile_id,
    )

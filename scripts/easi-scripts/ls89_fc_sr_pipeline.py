#!/usr/bin/env python

"""
Pipeline master for LS8/9 SR + FC queries driven by a tile grid.

- Reads a tile shapefile (default: ~/scratch/eds/assets/eds_lsat_grid_min_max.shp)
- For each tile (or a selected one), extracts:
    lat_min, lat_max, lon_min, lon_max
- Calls ls89_fc_sr_query.py with those bounds + span_years

You can later extend this script to:
- Read the comparison_table.csv outputs
- Trigger downloads / composites / uploads to S3
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import geopandas as gpd


# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

HOME = Path.home()
DEFAULT_TILE_REL = "assets/eds_lsat_grid_min_max.shp"
DEFAULT_TILE_SHP = HOME / "scratch" / "eds" / DEFAULT_TILE_REL

DEFAULT_QUERY_SCRIPT = (
    HOME / "work-easi-eds" / "scripts" / "easi-scripts" / "ls89_fc_sr_query.py"
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def resolve_tile_path(tile_arg: str | None) -> Path:
    """
    Resolve the tile shapefile path.

    - If None: use DEFAULT_TILE_SHP
    - If relative: assume relative to ~/scratch/eds/
    - If absolute: use as-is
    """
    if tile_arg is None:
        return DEFAULT_TILE_SHP

    p = Path(tile_arg).expanduser()
    if p.is_absolute():
        return p

    # treat as relative to ~/scratch/eds
    base = HOME / "scratch" / "eds"
    return base / p



def run_ls89_fc_sr_query(
    script_path,
    lat_min,
    lat_max,
    lon_min,
    lon_max,
    span_years,
    dry_run=False,
    tile_id=None,
    tile_path=None,
    tile_row=None,
):
    """
    Call ls89_fc_sr_query.py as a subprocess with the given params.
    """

    cmd = [
        "python",
        str(script_path),
        "--lat-min", str(lat_min),
        "--lat-max", str(lat_max),
        "--lon-min", str(lon_min),
        "--lon-max", str(lon_max),
        "--span-years", str(span_years),
    ]

    # 🔹 ONLY ONE of these is needed, tile_id is nicest
    if tile_id is not None:
        cmd += ["--tile-id", tile_id]
    elif tile_path is not None and tile_row is not None:
        cmd += ["--tile-path", str(tile_path), "--tile-row", str(tile_row)]

    print("[PIPELINE] Running:", " ".join(cmd))

    if dry_run:
        print("[PIPELINE] Dry run: not executing command.")
        return

    subprocess.run(cmd, check=True)



# ---------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LS8/9 SR+FC pipeline driven by a tile grid shapefile."
    )

    parser.add_argument(
        "--tile-shp",
        default=str(DEFAULT_TILE_SHP),
        help=(
            "Path to tile shapefile. "
            "If relative, interpreted under ~/. "
            f"Default: {DEFAULT_TILE_SHP}"
        ),
    )

    parser.add_argument(
        "--span-years",
        type=int,
        default=10,
        help="Time span in years (end = today, start = today - span_years). Default: 10.",
    )

    parser.add_argument(
        "--tile-id",
        type=str,
        default=None,
        help=(
            "Optional specific tile_id to run, e.g. 'p104r070'. "
            "If not provided, runs for ALL tiles in the shapefile."
        ),
    )

    parser.add_argument(
        "--path",
        type=int,
        default=None,
        help="Optional WRS path (overrides tile-id if both path and row provided).",
    )

    parser.add_argument(
        "--row",
        type=int,
        default=None,
        help="Optional WRS row (overrides tile-id if both path and row provided).",
    )

    parser.add_argument(
        "--query-script",
        default=str(DEFAULT_QUERY_SCRIPT),
        help=f"Path to ls89_fc_sr_query.py. Default: {DEFAULT_QUERY_SCRIPT}",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands but do not actually run ls89_fc_sr_query.py.",
    )

    args = parser.parse_args()

    tile_path = resolve_tile_path(args.tile_shp)

    script_path = Path(args.query_script).expanduser()

    print("Tile shapefile:", tile_path)
    print("Query script  :", script_path)
    print("Span years    :", args.span_years)

    if not tile_path.exists():
        raise FileNotFoundError(f"Tile shapefile not found: {tile_path}")
    if not script_path.exists():
        raise FileNotFoundError(f"Query script not found: {script_path}")

    # -----------------------------------------------------------------
    # Load tile grid
    # -----------------------------------------------------------------
    gdf = gpd.read_file(tile_path)
    print("Loaded tiles:", len(gdf))

    # Ensure required columns exist
    required_cols = ["path", "row", "lat_min", "lat_max", "lon_min", "lon_max"]
    missing = [c for c in required_cols if c not in gdf.columns]
    if missing:
        raise ValueError(
            f"Tile shapefile missing required columns: {missing}. "
            "Expected at least path, row, lat_min, lat_max, lon_min, lon_max."
        )

    # Build tile_id if not present
    if "tile_id" not in gdf.columns:
        gdf["tile_id"] = gdf.apply(
            lambda r: f"p{int(r['path']):03d}r{int(r['row']):03d}", axis=1
        )

    # -----------------------------------------------------------------
    # Filter tiles if requested
    # -----------------------------------------------------------------
    if args.path is not None and args.row is not None:
        sel = gdf[(gdf["path"] == args.path) & (gdf["row"] == args.row)]
        if sel.empty:
            raise ValueError(f"No tile found for path={args.path}, row={args.row}")
        run_tiles = sel
        print(f"Filtering to path={args.path}, row={args.row} -> {len(sel)} feature(s).")

    elif args.tile_id is not None:
        sel = gdf[gdf["tile_id"] == args.tile_id]
        if sel.empty:
            raise ValueError(f"No tile found with tile_id={args.tile_id}")
        run_tiles = sel
        print(f"Filtering to tile_id={args.tile_id} -> {len(sel)} feature(s).")

    else:
        run_tiles = gdf
        print("No specific tile filter provided: running for ALL tiles.")

    # -----------------------------------------------------------------
    # Loop over tiles and run query
    # -----------------------------------------------------------------
    # -----------------------------------------------------------------
    # Loop over tiles and run query
    # -----------------------------------------------------------------
    for idx, row in run_tiles.iterrows():
        tile_id = row["tile_id"]
        path = int(row["path"])
        rownum = int(row["row"])

        lat_min = float(row["lat_min"])
        lat_max = float(row["lat_max"])
        lon_min = float(row["lon_min"])
        lon_max = float(row["lon_max"])

        print(f"\n=== Running tile {tile_id} (path={path}, row={rownum}) ===")
        print(f"  lat_min={lat_min}, lat_max={lat_max}")
        print(f"  lon_min={lon_min}, lon_max={lon_max}")

        run_ls89_fc_sr_query(
            script_path=script_path,
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max,
            span_years=args.span_years,
            dry_run=args.dry_run,
            tile_id=tile_id,
            tile_path=path,
            tile_row=rownum,
        )

        # -----------------------------------------------------------------
        # PLACEHOLDER: future pipeline steps
        # -----------------------------------------------------------------
        # Here you can add:
        #  - logic to derive the output directory span_tag (if you want)
        #  - reading comparison_table.csv for this tile
        #  - downloading scenes/composites
        #  - uploading to S3, etc.
        #
        # e.g. something like:
        # post_process_tile(tile_id, args.span_years, ...)
        # -----------------------------------------------------------------


if __name__ == "__main__":
    main()


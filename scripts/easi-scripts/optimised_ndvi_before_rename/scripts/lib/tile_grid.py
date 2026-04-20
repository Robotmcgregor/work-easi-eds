from __future__ import annotations

import math
import re
import geopandas as gpd
import math

def derive_target_epsg_gda94_mga_from_lon(lon: float) -> int:
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    return 28300 + zone

# back-compat wrapper (keep this)
def derive_target_epsg_gda94_mga(geom_wgs84) -> int:
    minx, miny, maxx, maxy = geom_wgs84.bounds
    centre_lon = (minx + maxx) / 2.0
    return derive_target_epsg_gda94_mga_from_lon(centre_lon)



def load_tile_bbox_wgs84(tile_shp: str, tile: str) -> tuple[float, float, float, float]:
    """
    Returns (lon_min, lat_min, lon_max, lat_max) for a tile like p089r084
    using shapefile columns: lon_min, lon_max, lat_min, lat_max
    """
    tile = tile.lower().strip()
    m = re.fullmatch(r"p(\d{3})r(\d{3})", tile)
    if not m:
        raise ValueError(f"Expected tile like p089r084, got: {tile}")

    p = int(m.group(1))
    r = int(m.group(2))

    gdf = gpd.read_file(tile_shp)

    if "path" not in gdf.columns or "row" not in gdf.columns:
        raise RuntimeError(f"tile_shp missing path/row fields. Columns: {list(gdf.columns)}")

    sel = gdf[(gdf["path"].astype(int) == p) & (gdf["row"].astype(int) == r)]
    if sel.empty:
        raise RuntimeError(f"Tile {tile} not found in {tile_shp} using path={p}, row={r}")

    for c in ("lon_min", "lon_max", "lat_min", "lat_max"):
        if c not in sel.columns:
            raise RuntimeError(f"tile_shp missing {c}. Columns: {list(gdf.columns)}")

    lon_min = float(sel["lon_min"].iloc[0])
    lon_max = float(sel["lon_max"].iloc[0])
    lat_min = float(sel["lat_min"].iloc[0])
    lat_max = float(sel["lat_max"].iloc[0])

    return lon_min, lat_min, lon_max, lat_max


def load_tile_geometry_wgs84(tile_shp: str, tile: str):
    """
    Loads tile geometry from a shapefile and returns it in WGS84.

    Supports tile ids like:
      - "p089r084" (what you normally use)

    Shapefile might store it as:
      - a Name like "89_84" or "089_084"
      - OR separate columns path=89 row=84
    """
    # normalise tile string
    tile = tile.lower().strip()

    # load the shapefile
    gdf = gpd.read_file(tile_shp)

    # ---------- case A: tile is like p###r### ----------
    m = re.fullmatch(r"p(\d{3})r(\d{3})", tile)
    if m:
        # pull out path and row as ints
        p = int(m.group(1))
        r = int(m.group(2))

        # try the nice case first: explicit path/row columns
        if "path" in gdf.columns and "row" in gdf.columns:
            sel = gdf[(gdf["path"].astype(int) == p) & (gdf["row"].astype(int) == r)]

            # if nothing matches, bail out with some debug info
            if sel.empty:
                raise RuntimeError(
                    f"Tile {tile} not found by path/row in {tile_shp}. "
                    f"Tried path={p}, row={r}. "
                    f"Example rows: {gdf[['path','row']].head(10).to_dict('records')}"
                )
        else:
            # fallback: try match by a Name field like "89_84"
            if "Name" not in gdf.columns and "name" not in gdf.columns:
                # if there is no Name and no path/row, we cant really do much
                raise RuntimeError(
                    f"Shapefile has no (path,row) and no Name field to match. "
                    f"Columns: {list(gdf.columns)}"
                )

            # decide which name column to use
            name_col = "Name" if "Name" in gdf.columns else "name"

            # possible formats we might find
            candidates = {f"{p}_{r}", f"{p:03d}_{r:03d}"}

            # select any matching rows
            sel = gdf[gdf[name_col].astype(str).isin(candidates)]

            # if still nothing, show some examples so its easier to debug
            if sel.empty:
                examples = gdf[name_col].astype(str).head(10).tolist()
                raise RuntimeError(
                    f"Tile {tile} not found in {tile_shp} via Name candidates {sorted(candidates)}. "
                    f"Examples: {examples}"
                )
    # ---------- Case B: tile is whatever Name stores ----------
    else:
        if "Name" in gdf.columns:
            name_col = "Name"
        elif "name" in gdf.columns:
            name_col = "name"
        else:
            raise RuntimeError(
                f"Cannot find tile identifier fields in {tile_shp}. "
                f"Columns: {list(gdf.columns)}"
            )

        sel = gdf[gdf[name_col].astype(str).str.lower() == tile.lower()]
        if sel.empty:
            examples = gdf[name_col].astype(str).head(10).tolist()
            raise RuntimeError(
                f"Tile {tile} not found in {tile_shp} (field {name_col}). Examples: {examples}"
            )

    geom = sel.geometry.iloc[0]

    # ensure WGS84
    if sel.crs is not None and str(sel.crs).lower() not in ("epsg:4326", "4326"):
        sel = sel.to_crs("EPSG:4326")
        geom = sel.geometry.iloc[0]

    return geom




import math

# ---------------------------------------------------------------------
# Backwards compatibility
# Older code imported derive_target_epsg_gda94_mga(geom)
# In the bbox-optimised pipeline we derive from lon centre.
# ---------------------------------------------------------------------
def derive_target_epsg_gda94_mga(geom_wgs84) -> int:
    """
    Back-compat wrapper.
    Accepts a shapely geom (in EPSG:4326) and derives MGA EPSG from centre lon.
    """
    minx, miny, maxx, maxy = geom_wgs84.bounds
    centre_lon = (minx + maxx) / 2.0
    return derive_target_epsg_gda94_mga_from_lon(centre_lon)

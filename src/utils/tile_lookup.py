"""
Helpers to resolve tile metadata from the database (e.g., bounding boxes) for use in CLIs.
"""
from __future__ import annotations

import json
from typing import Optional, Tuple

from src.database.connection import get_db
from src.database.models import LandsatTile


def get_tile_bbox(tile_id: str) -> Optional[Tuple[float, float, float, float]]:
    """Return (min_lon, min_lat, max_lon, max_lat) for a tile from bounds_geojson.

    Expects bounds_geojson to be a Polygon. If not present or invalid, returns None.
    """
    with get_db() as session:
        tile = session.query(LandsatTile).filter(LandsatTile.tile_id == tile_id).first()
        if not tile or not tile.bounds_geojson:
            return None
        try:
            geom_obj = json.loads(tile.bounds_geojson)
        except Exception:
            return None

        # Support Feature wrapper
        if isinstance(geom_obj, dict) and geom_obj.get("type") == "Feature" and "geometry" in geom_obj:
            geom_obj = geom_obj.get("geometry")

        def iter_xy_from_geom(gobj):
            if not isinstance(gobj, dict):
                return
            gtype = gobj.get("type")
            coords = gobj.get("coordinates")
            if not gtype or coords is None:
                return
            def emit_xy(pt):
                # pt may be [x,y] or [x,y,z] or nested; normalize to first two numbers
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    x0 = pt[0]
                    y0 = pt[1]
                    try:
                        yield float(x0), float(y0)
                    except Exception:
                        return
            if gtype == "Polygon":
                for ring in coords:
                    for pt in ring:
                        for xy in emit_xy(pt):
                            yield xy
            elif gtype == "MultiPolygon":
                for poly in coords:
                    for ring in poly:
                        for pt in ring:
                            for xy in emit_xy(pt):
                                yield xy
            elif gtype == "LineString":
                for pt in coords:
                    for xy in emit_xy(pt):
                        yield xy
            elif gtype == "MultiLineString":
                for line in coords:
                    for pt in line:
                        for xy in emit_xy(pt):
                            yield xy
            elif gtype == "Point":
                for xy in emit_xy(coords):
                    yield xy
            elif gtype == "MultiPoint":
                for pt in coords:
                    for xy in emit_xy(pt):
                        yield xy

        xs: list[float] = []
        ys: list[float] = []
        for x, y in iter_xy_from_geom(geom_obj):
            xs.append(x)
            ys.append(y)
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

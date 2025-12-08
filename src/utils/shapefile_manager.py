"""
Shapefile management for Australian Landsat tiles.
Handles reading and processing of Landsat tile boundary shapefiles.
"""

import os
import geopandas as gpd
import pandas as pd
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import logging
from shapely.geometry import Polygon, Point

from ..config.settings import get_config, SystemConfig

logger = logging.getLogger(__name__)


class ShapefileManager:
    """Manages Landsat tile shapefiles and boundary operations."""

    def __init__(self, config: SystemConfig = None):
        self.config = config or get_config()
        # Use current working directory as project root
        self.assets_path = Path.cwd() / "assets"
        self.tile_gdf = None

    def load_tile_shapefile(self, shapefile_path: str = None) -> gpd.GeoDataFrame:
        """
        Load Landsat tile boundaries from shapefile.

        Args:
            shapefile_path: Path to shapefile. If None, searches for .shp files in assets folder.

        Returns:
            GeoDataFrame with tile boundaries
        """
        try:
            if shapefile_path is None:
                # Search for shapefile in assets folder
                shapefile_path = self._find_tile_shapefile()

            if not shapefile_path or not os.path.exists(shapefile_path):
                raise FileNotFoundError(f"Shapefile not found: {shapefile_path}")

            logger.info(f"Loading tile shapefile from: {shapefile_path}")
            self.tile_gdf = gpd.read_file(shapefile_path)

            # Ensure CRS is set (WGS84)
            if self.tile_gdf.crs is None:
                self.tile_gdf.set_crs("EPSG:4326", inplace=True)
            elif self.tile_gdf.crs != "EPSG:4326":
                self.tile_gdf = self.tile_gdf.to_crs("EPSG:4326")

            logger.info(f"Loaded {len(self.tile_gdf)} tiles from shapefile")
            return self.tile_gdf

        except Exception as e:
            logger.error(f"Error loading shapefile: {e}")
            raise

    def _find_tile_shapefile(self) -> Optional[str]:
        """Find the first .shp file in the assets folder."""
        if not self.assets_path.exists():
            return None

        for file in self.assets_path.rglob("*.shp"):
            logger.info(f"Found shapefile: {file}")
            return str(file)

        return None

    def get_australian_tiles(self) -> List[Dict]:
        """
        Get all Australian Landsat tiles from the shapefile.

        Returns:
            List of dictionaries with tile information
        """
        if self.tile_gdf is None:
            self.load_tile_shapefile()

        tiles = []
        for idx, df_row in self.tile_gdf.iterrows():
            # Extract path and row from shapefile attributes
            # Common field names: PATH, ROW, PR, PATH_ROW, etc.
            path, row_num = self._extract_path_row(df_row)

            if path and row_num:
                tile_info = {
                    "tile_id": f"{path:03d}{row_num:03d}",
                    "path": path,
                    "row": row_num,
                    "geometry": df_row.geometry,
                    "bounds": df_row.geometry.bounds,  # (minx, miny, maxx, maxy)
                    "center_lat": df_row.geometry.centroid.y,
                    "center_lon": df_row.geometry.centroid.x,
                    "area_km2": self._calculate_area_km2(df_row.geometry),
                    "shapefile_data": dict(df_row),  # Store all original attributes
                }
                tiles.append(tile_info)

        logger.info(f"Extracted {len(tiles)} Australian tiles")
        return tiles

    def _extract_path_row(self, row) -> Tuple[Optional[int], Optional[int]]:
        """
        Extract path and row numbers from shapefile row.
        Handles various common field naming conventions.
        """
        # Common field names for path
        path_fields = ["PATH", "Path", "path", "WRS_PATH", "PR_PATH"]
        row_fields = ["ROW", "Row", "row", "WRS_ROW", "PR_ROW"]

        path = None
        row_num = None

        # Try to find path in standard fields
        for field in path_fields:
            if field in row.index and pd.notna(row[field]):
                path = int(row[field])
                break

        # Try to find row in standard fields
        for field in row_fields:
            if field in row.index and pd.notna(row[field]):
                row_num = int(row[field])
                break

        # Try to extract from combined field like 'PR' or 'PATH_ROW'
        if path is None or row_num is None:
            combined_fields = ["PR", "PATH_ROW", "PATHROW", "WRS_PR"]
            for field in combined_fields:
                if field in row.index and pd.notna(row[field]):
                    combined = str(row[field]).replace("_", "").replace("-", "")
                    if len(combined) >= 6:  # Format like '090066'
                        path = int(combined[:3])
                        row_num = int(combined[3:6])
                        break

        # Try to extract from 'Name' field (common in KML-derived shapefiles)
        if (
            (path is None or row_num is None)
            and "Name" in row.index
            and pd.notna(row["Name"])
        ):
            name = str(row["Name"])
            # Look for patterns like "91_91", "090_066", etc.
            if "_" in name:
                parts = name.split("_")
                if len(parts) >= 2:
                    try:
                        path = int(parts[0])
                        row_num = int(parts[1])
                    except ValueError:
                        pass

        # Try to extract from PopupInfo field (HTML content with PATH/ROW data)
        if (
            (path is None or row_num is None)
            and "PopupInfo" in row.index
            and pd.notna(row["PopupInfo"])
        ):
            popup_info = str(row["PopupInfo"])

            # Look for PATH in the HTML content
            import re

            path_match = re.search(
                r"<strong>PATH</strong>:\s*(\d+(?:\.\d+)?)", popup_info
            )
            row_match = re.search(
                r"<strong>ROW</strong>:\s*(\d+(?:\.\d+)?)", popup_info
            )

            if path_match:
                path = int(float(path_match.group(1)))
            if row_match:
                row_num = int(float(row_match.group(1)))

        return path, row_num

    def _calculate_area_km2(self, geometry: Polygon) -> float:
        """Calculate area of geometry in square kilometers."""
        # For more accurate area calculation, project to appropriate UTM zone
        # For now, use simple approximation
        bounds = geometry.bounds
        lat_center = (bounds[1] + bounds[3]) / 2

        # Rough approximation: 1 degree ≈ 111 km at equator
        # Adjust for latitude
        lat_factor = abs(lat_center / 90.0)
        km_per_degree_lat = 111.32
        km_per_degree_lon = 111.32 * (1 - lat_factor * 0.5)  # Simplified

        width_km = (bounds[2] - bounds[0]) * km_per_degree_lon
        height_km = (bounds[3] - bounds[1]) * km_per_degree_lat

        return width_km * height_km

    def get_tile_by_coordinates(self, lat: float, lon: float) -> Optional[Dict]:
        """
        Find which Landsat tile contains the given coordinates.

        Args:
            lat: Latitude
            lon: Longitude

        Returns:
            Tile information dict or None if not found
        """
        if self.tile_gdf is None:
            self.load_tile_shapefile()

        point = Point(lon, lat)

        for idx, row in self.tile_gdf.iterrows():
            if row.geometry.contains(point):
                path, row_num = self._extract_path_row(row)
                if path and row_num:
                    return {
                        "tile_id": f"{path:03d}{row_num:03d}",
                        "path": path,
                        "row": row_num,
                        "geometry": row.geometry,
                        "shapefile_data": dict(row),
                    }

        return None

    def get_tiles_in_bounds(
        self, min_lat: float, max_lat: float, min_lon: float, max_lon: float
    ) -> List[Dict]:
        """
        Get all tiles that intersect with the given bounding box.

        Args:
            min_lat, max_lat: Latitude bounds
            min_lon, max_lon: Longitude bounds

        Returns:
            List of tile information dictionaries
        """
        if self.tile_gdf is None:
            self.load_tile_shapefile()

        from shapely.geometry import box

        bbox = box(min_lon, min_lat, max_lon, max_lat)

        intersecting_tiles = []
        for idx, row in self.tile_gdf.iterrows():
            if row.geometry.intersects(bbox):
                path, row_num = self._extract_path_row(row)
                if path and row_num:
                    tile_info = {
                        "tile_id": f"{path:03d}{row_num:03d}",
                        "path": path,
                        "row": row_num,
                        "geometry": row.geometry,
                        "intersection_area": row.geometry.intersection(bbox).area,
                        "shapefile_data": dict(row),
                    }
                    intersecting_tiles.append(tile_info)

        return intersecting_tiles

    def export_tile_summary(self, output_path: str = None) -> pd.DataFrame:
        """
        Export a summary of all tiles to CSV.

        Args:
            output_path: Path for output CSV. If None, saves to data folder.

        Returns:
            DataFrame with tile summary
        """
        if self.tile_gdf is None:
            self.load_tile_shapefile()

        tiles = self.get_australian_tiles()

        # Create summary DataFrame
        summary_data = []
        for tile in tiles:
            summary_data.append(
                {
                    "tile_id": tile["tile_id"],
                    "path": tile["path"],
                    "row": tile["row"],
                    "center_lat": tile["center_lat"],
                    "center_lon": tile["center_lon"],
                    "area_km2": tile["area_km2"],
                    "min_lon": tile["bounds"][0],
                    "min_lat": tile["bounds"][1],
                    "max_lon": tile["bounds"][2],
                    "max_lat": tile["bounds"][3],
                }
            )

        df = pd.DataFrame(summary_data)

        if output_path is None:
            output_path = Path.cwd() / "data" / "tile_summary.csv"

        df.to_csv(output_path, index=False)
        logger.info(f"Exported tile summary to: {output_path}")

        return df

    def validate_shapefile(self) -> Dict[str, any]:
        """
        Validate the loaded shapefile and return diagnostic information.

        Returns:
            Dictionary with validation results
        """
        if self.tile_gdf is None:
            self.load_tile_shapefile()

        validation = {
            "total_features": len(self.tile_gdf),
            "crs": str(self.tile_gdf.crs),
            "bounds": self.tile_gdf.total_bounds.tolist(),
            "columns": list(self.tile_gdf.columns),
            "geometry_types": self.tile_gdf.geometry.geom_type.unique().tolist(),
            "has_path_row": False,
            "path_range": None,
            "row_range": None,
            "sample_features": [],
        }

        # Check for path/row fields
        paths = []
        rows = []

        for idx, row in self.tile_gdf.head(10).iterrows():  # Check first 10 features
            path, row_num = self._extract_path_row(row)
            if path and row_num:
                paths.append(path)
                rows.append(row_num)
                validation["sample_features"].append(
                    {
                        "tile_id": f"{path:03d}{row_num:03d}",
                        "path": path,
                        "row": row_num,
                        "bounds": list(row.geometry.bounds),
                    }
                )

        if paths and rows:
            validation["has_path_row"] = True
            validation["path_range"] = [min(paths), max(paths)]
            validation["row_range"] = [min(rows), max(rows)]

        return validation

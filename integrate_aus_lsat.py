#!/usr/bin/env python
"""
Script to integrate the specific aus_lsat.shp shapefile with the EDS system.
"""

import sys
import os
from pathlib import Path

# Add src directory to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from src.utils.shapefile_manager import ShapefileManager
from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.config.settings import get_config
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/aus_lsat_integration.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def main():
    """Main function to integrate the aus_lsat.shp shapefile."""
    try:
        logger.info("Starting aus_lsat.shp integration...")

        # Initialize components
        config = get_config()
        shapefile_manager = ShapefileManager(config)

        # Load the specific aus_lsat.shp file
        aus_lsat_path = project_root / "assets" / "aus_lsat.shp"

        if not aus_lsat_path.exists():
            print("ERROR: aus_lsat.shp not found in assets folder!")
            return

        # Load and validate the specific shapefile
        logger.info(f"Loading aus_lsat.shp from: {aus_lsat_path}")
        gdf = shapefile_manager.load_tile_shapefile(str(aus_lsat_path))

        # Validate shapefile
        validation = shapefile_manager.validate_shapefile()

        print("\n=== AUS_LSAT.SHP VALIDATION RESULTS ===")
        print(f"Total features: {validation['total_features']}")
        print(f"CRS: {validation['crs']}")
        print(f"Bounds: {validation['bounds']}")
        print(f"Has path/row data: {validation['has_path_row']}")

        if validation["has_path_row"]:
            print(f"Path range: {validation['path_range']}")
            print(f"Row range: {validation['row_range']}")
            print(f"Sample features: {len(validation['sample_features'])}")

            # Show sample features
            print("\nSample tiles:")
            for feature in validation["sample_features"][:5]:
                print(
                    f"  {feature['tile_id']}: Path {feature['path']}, Row {feature['row']}"
                )
        else:
            print("ERROR: Could not extract path/row information from aus_lsat.shp")
            return

        # Ask user if they want to proceed
        response = input(
            f"\nDo you want to integrate {validation['total_features']} Australian Landsat tiles into the database? (y/n): "
        )
        if response.lower() not in ["y", "yes"]:
            print("Integration cancelled.")
            return

        # Load all tiles from shapefile
        logger.info("Extracting tiles from aus_lsat.shp...")
        tiles = shapefile_manager.get_australian_tiles()

        # Connect to database and update tiles
        logger.info("Connecting to database...")
        db_manager = DatabaseManager(config.database.connection_url)

        with db_manager.get_session() as session:
            updated_count = 0
            new_count = 0

            for tile_data in tiles:
                try:
                    # Check if tile exists
                    existing_tile = (
                        session.query(LandsatTile)
                        .filter(LandsatTile.tile_id == tile_data["tile_id"])
                        .first()
                    )

                    if existing_tile:
                        # Update existing tile with shapefile data
                        import json

                        existing_tile.bounds_geojson = json.dumps(
                            tile_data["geometry"].__geo_interface__
                        )
                        existing_tile.center_lat = tile_data["center_lat"]
                        existing_tile.center_lon = tile_data["center_lon"]
                        existing_tile.processing_notes = (
                            f"Area: {tile_data['area_km2']:.2f} km² (from aus_lsat.shp)"
                        )
                        updated_count += 1
                        logger.debug(f"Updated tile {tile_data['tile_id']}")
                    else:
                        # Create new tile
                        import json

                        new_tile = LandsatTile(
                            tile_id=tile_data["tile_id"],
                            path=tile_data["path"],
                            row=tile_data["row"],
                            center_lat=tile_data["center_lat"],
                            center_lon=tile_data["center_lon"],
                            bounds_geojson=json.dumps(
                                tile_data["geometry"].__geo_interface__
                            ),
                            processing_notes=f"Area: {tile_data['area_km2']:.2f} km² (from aus_lsat.shp)",
                        )
                        session.add(new_tile)
                        new_count += 1
                        logger.debug(f"Created tile {tile_data['tile_id']}")

                except Exception as e:
                    logger.error(
                        f"Error processing tile {tile_data.get('tile_id', 'unknown')}: {e}"
                    )

            session.commit()

        print(f"\n=== INTEGRATION COMPLETE ===")
        print(f"Total tiles processed: {len(tiles)}")
        print(f"New tiles created: {new_count}")
        print(f"Existing tiles updated: {updated_count}")

        # Export summary
        summary_path = project_root / "data" / "aus_lsat_tile_summary.csv"
        df = shapefile_manager.export_tile_summary(str(summary_path))
        print(f"Tile summary exported to: {summary_path}")

        # Show path/row distribution
        paths = sorted(set(tile["path"] for tile in tiles))
        rows = sorted(set(tile["row"] for tile in tiles))

        print(f"\n=== AUSTRALIAN LANDSAT COVERAGE ===")
        print(f"Paths: {paths[0]}-{paths[-1]} ({len(paths)} paths)")
        print(f"Rows: {rows[0]}-{rows[-1]} ({len(rows)} rows)")
        print(f"Geographic bounds: {validation['bounds']}")
        print(f"Total tiles: {len(tiles)}")

        logger.info("aus_lsat.shp integration completed successfully")

        print(f"\n=== NEXT STEPS ===")
        print("1. Start the dashboard: py start_dashboard.py")
        print("2. View tiles at: http://localhost:8050")
        print("3. Run processing jobs: py scripts/run_eds.py")

    except Exception as e:
        logger.error(f"Error during aus_lsat.shp integration: {e}")
        raise


if __name__ == "__main__":
    main()

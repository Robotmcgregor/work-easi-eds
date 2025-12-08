"""
Tile initialization script for the EDS application.
This script initializes the Landsat tile grid covering Australia.
"""

import sys
import logging
import argparse
from pathlib import Path

# Add the src directory to the path so we can import our modules
project_root = Path(__file__).parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(src_path))

from src.config import load_config, validate_config
from src.database import init_database, TileManager
from src.utils.tile_management import (
    initialize_australian_tiles,
    get_australian_tile_grid,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def show_tile_statistics():
    """Display statistics about the Australian tile grid."""
    try:
        logger.info("Calculating tile grid statistics...")

        from src.utils.tile_management import TileInitializer

        initializer = TileInitializer()
        stats = initializer.get_tile_statistics()

        logger.info("=== Australian Landsat Tile Grid Statistics ===")
        logger.info(f"Total tiles: {stats['total_tiles']}")
        logger.info(f"Path range: {stats['path_range']}")
        logger.info(f"Row range: {stats['row_range']}")
        logger.info(f"Latitude range: {stats['latitude_range']}")
        logger.info(f"Longitude range: {stats['longitude_range']}")
        logger.info(f"Approximate coverage: {stats['coverage_area_approx_km2']:,} km²")

        return True

    except Exception as e:
        logger.error(f"Failed to calculate statistics: {e}")
        return False


def initialize_tiles(update_existing=False):
    """Initialize tiles in the database."""
    try:
        logger.info("Initializing Landsat tiles in database...")

        # Initialize database connection
        config = load_config()
        if not validate_config():
            logger.error("Configuration validation failed")
            return False

        init_database()

        # Initialize tiles
        tiles_processed = initialize_australian_tiles(update_existing=update_existing)

        logger.info(f"Tile initialization complete: {tiles_processed} tiles processed")

        # Show database statistics
        show_database_tile_status()

        return True

    except Exception as e:
        logger.error(f"Tile initialization failed: {e}")
        return False


def show_database_tile_status():
    """Show the current status of tiles in the database."""
    try:
        logger.info("=== Database Tile Status ===")

        # Get all tiles
        all_tiles = TileManager.get_all_tiles(active_only=False)
        active_tiles = TileManager.get_all_tiles(active_only=True)

        logger.info(f"Total tiles in database: {len(all_tiles)}")
        logger.info(f"Active tiles: {len(active_tiles)}")

        # Status breakdown
        if active_tiles:
            from collections import Counter

            status_counts = Counter(tile.status for tile in active_tiles)

            logger.info("Status breakdown:")
            for status, count in status_counts.items():
                logger.info(f"  {status}: {count}")

        # Recent processing
        pending_tiles = TileManager.get_tiles_by_status("pending")
        logger.info(f"Tiles pending processing: {len(pending_tiles)}")

        return True

    except Exception as e:
        logger.error(f"Failed to get tile status: {e}")
        return False


def reset_tile_status():
    """Reset all tiles to pending status."""
    try:
        logger.info("Resetting all tiles to pending status...")

        all_tiles = TileManager.get_all_tiles(active_only=True)
        reset_count = 0

        for tile in all_tiles:
            if TileManager.update_tile_status(
                tile.tile_id, "pending", "Reset by initialization script"
            ):
                reset_count += 1

        logger.info(f"Reset {reset_count} tiles to pending status")
        return True

    except Exception as e:
        logger.error(f"Failed to reset tile status: {e}")
        return False


def export_tile_list(output_file):
    """Export the tile list to a CSV file."""
    try:
        import csv

        logger.info(f"Exporting tile list to {output_file}...")

        tiles = TileManager.get_all_tiles()

        with open(output_file, "w", newline="") as csvfile:
            fieldnames = [
                "tile_id",
                "path",
                "row",
                "center_lat",
                "center_lon",
                "status",
                "last_processed",
                "is_active",
                "priority",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for tile in tiles:
                writer.writerow(
                    {
                        "tile_id": tile.tile_id,
                        "path": tile.path,
                        "row": tile.row,
                        "center_lat": tile.center_lat,
                        "center_lon": tile.center_lon,
                        "status": tile.status,
                        "last_processed": (
                            tile.last_processed.isoformat()
                            if tile.last_processed
                            else ""
                        ),
                        "is_active": tile.is_active,
                        "priority": tile.processing_priority,
                    }
                )

        logger.info(f"Exported {len(tiles)} tiles to {output_file}")
        return True

    except Exception as e:
        logger.error(f"Failed to export tile list: {e}")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Initialize Landsat tiles for the EDS system"
    )
    parser.add_argument("--config", help="Path to configuration file", default=None)
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update existing tiles with new information",
    )
    parser.add_argument(
        "--stats-only", action="store_true", help="Only show tile grid statistics"
    )
    parser.add_argument(
        "--status-only", action="store_true", help="Only show database tile status"
    )
    parser.add_argument(
        "--reset-status", action="store_true", help="Reset all tiles to pending status"
    )
    parser.add_argument("--export-csv", help="Export tile list to CSV file")

    args = parser.parse_args()

    logger.info("=== EDS Tile Initialization ===")

    if args.stats_only:
        if show_tile_statistics():
            sys.exit(0)
        else:
            sys.exit(1)

    if args.status_only:
        # Need database connection for this
        config = load_config(args.config)
        if not validate_config():
            logger.error("Configuration validation failed")
            sys.exit(1)
        init_database()

        if show_database_tile_status():
            sys.exit(0)
        else:
            sys.exit(1)

    if args.reset_status:
        # Need database connection
        config = load_config(args.config)
        if not validate_config():
            logger.error("Configuration validation failed")
            sys.exit(1)
        init_database()

        if reset_tile_status():
            logger.info("Tile status reset complete")
        else:
            logger.error("Tile status reset failed")
            sys.exit(1)

    if args.export_csv:
        # Need database connection
        config = load_config(args.config)
        if not validate_config():
            logger.error("Configuration validation failed")
            sys.exit(1)
        init_database()

        if export_tile_list(args.export_csv):
            logger.info("Tile export complete")
        else:
            logger.error("Tile export failed")
            sys.exit(1)

    # Default action: initialize tiles
    if not any([args.stats_only, args.status_only, args.reset_status, args.export_csv]):
        if not initialize_tiles(args.update_existing):
            logger.error("Tile initialization failed")
            sys.exit(1)

        logger.info("=== Tile Initialization Complete ===")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""
Script to integrate shapefile data with the EDS tile management system.
Loads shapefile data and updates the database with accurate tile boundaries.
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/shapefile_integration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    """Main function to integrate shapefile data."""
    try:
        logger.info("Starting shapefile integration...")
        
        # Initialize components
        config = get_config()
        shapefile_manager = ShapefileManager(config)
        db_manager = DatabaseManager(config.database.connection_url)
        
        # Validate shapefile
        logger.info("Validating shapefile...")
        validation = shapefile_manager.validate_shapefile()
        
        print("\n=== SHAPEFILE VALIDATION RESULTS ===")
        print(f"Total features: {validation['total_features']}")
        print(f"CRS: {validation['crs']}")
        print(f"Bounds: {validation['bounds']}")
        print(f"Columns: {validation['columns']}")
        print(f"Geometry types: {validation['geometry_types']}")
        print(f"Has path/row data: {validation['has_path_row']}")
        
        if validation['has_path_row']:
            print(f"Path range: {validation['path_range']}")
            print(f"Row range: {validation['row_range']}")
            print(f"Sample features: {len(validation['sample_features'])}")
            
            # Show sample features
            print("\nSample tiles:")
            for feature in validation['sample_features'][:5]:
                print(f"  {feature['tile_id']}: Path {feature['path']}, Row {feature['row']}")
        else:
            print("WARNING: Could not extract path/row information from shapefile")
            print("Available columns:", validation['columns'])
            return
            
        # Ask user if they want to proceed
        response = input("\nDo you want to update the database with this shapefile data? (y/n): ")
        if response.lower() not in ['y', 'yes']:
            print("Integration cancelled.")
            return
            
        # Load all tiles from shapefile
        logger.info("Loading tiles from shapefile...")
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
                    existing_tile = session.query(LandsatTile).filter(
                        LandsatTile.tile_id == tile_data['tile_id']
                    ).first()
                    
                    if existing_tile:
                        # Update existing tile with shapefile data
                        import json
                        existing_tile.bounds_geojson = json.dumps(tile_data['geometry'].__geo_interface__)
                        existing_tile.center_lat = tile_data['center_lat']
                        existing_tile.center_lon = tile_data['center_lon']
                        existing_tile.processing_notes = f"Area: {tile_data['area_km2']:.2f} km² (from shapefile)"
                        updated_count += 1
                        logger.debug(f"Updated tile {tile_data['tile_id']}")
                    else:
                        # Create new tile
                        import json
                        new_tile = LandsatTile(
                            tile_id=tile_data['tile_id'],
                            path=tile_data['path'],
                            row=tile_data['row'],
                            center_lat=tile_data['center_lat'],
                            center_lon=tile_data['center_lon'],
                            bounds_geojson=json.dumps(tile_data['geometry'].__geo_interface__),
                            processing_notes=f"Area: {tile_data['area_km2']:.2f} km² (from shapefile)"
                        )
                        session.add(new_tile)
                        new_count += 1
                        logger.debug(f"Created tile {tile_data['tile_id']}")
                        
                except Exception as e:
                    logger.error(f"Error processing tile {tile_data['tile_id']}: {e}")
                    
            session.commit()
            
        print(f"\n=== INTEGRATION COMPLETE ===")
        print(f"Total tiles processed: {len(tiles)}")
        print(f"New tiles created: {new_count}")
        print(f"Existing tiles updated: {updated_count}")
        
        # Export summary
        summary_path = project_root / "data" / "tile_summary_from_shapefile.csv"
        df = shapefile_manager.export_tile_summary(str(summary_path))
        print(f"Tile summary exported to: {summary_path}")
        
        logger.info("Shapefile integration completed successfully")
        
    except Exception as e:
        logger.error(f"Error during shapefile integration: {e}")
        raise

if __name__ == "__main__":
    main()
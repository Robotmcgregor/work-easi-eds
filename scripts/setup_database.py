"""
Database setup script for the EDS application.
This script creates the database, tables, and initializes the system.
"""

import sys
import logging
import argparse
from pathlib import Path

# Add the src directory to the path so we can import our modules
project_root = Path(__file__).parent.parent
src_path = project_root / 'src'
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(src_path))

from src.config import load_config, validate_config, get_database_url
from src.database import init_database, db_manager
from src.utils.tile_management import initialize_australian_tiles

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_database(config_file=None, force_recreate=False):
    """
    Set up the EDS database with tables and initial data.
    
    Args:
        config_file: Optional configuration file path
        force_recreate: If True, drop existing tables and recreate
    """
    try:
        # Load configuration
        logger.info("Loading configuration...")
        config = load_config(config_file)
        
        if not validate_config():
            logger.error("Configuration validation failed")
            return False
        
        logger.info(f"Using database: {get_database_url().replace('postgresql://', '').split('@')[1]}")
        
        # Initialize database connection
        logger.info("Initializing database connection...")
        init_database(get_database_url(), create_tables=False)
        
        # Test database connection
        if not db_manager.health_check():
            logger.error("Database health check failed - check connection settings")
            return False
        
        logger.info("Database connection successful")
        
        # Drop tables if force recreate is requested
        if force_recreate:
            logger.warning("Force recreate requested - dropping existing tables")
            try:
                db_manager.drop_tables()
                logger.info("Existing tables dropped")
            except Exception as e:
                logger.warning(f"Error dropping tables (may not exist): {e}")
        
        # Create tables
        logger.info("Creating database tables...")
        db_manager.create_tables()
        logger.info("Database tables created successfully")
        
        return True
        
    except Exception as e:
        logger.error(f"Database setup failed: {e}")
        return False


def initialize_tiles():
    """Initialize the Landsat tile grid for Australia."""
    try:
        logger.info("Initializing Australian Landsat tile grid...")
        
        # Initialize tiles in database
        tiles_processed = initialize_australian_tiles(update_existing=True)
        
        logger.info(f"Tile initialization complete: {tiles_processed} tiles processed")
        
        return True
        
    except Exception as e:
        logger.error(f"Tile initialization failed: {e}")
        return False


def verify_setup():
    """Verify that the database setup was successful."""
    try:
        logger.info("Verifying database setup...")
        
        from src.database import TileManager, SystemStatusManager
        
        # Check that tiles exist
        tiles = TileManager.get_all_tiles()
        logger.info(f"Found {len(tiles)} tiles in database")
        
        if len(tiles) == 0:
            logger.warning("No tiles found - run tile initialization")
            return False
        
        # Update system status
        SystemStatusManager.update_system_status("healthy")
        logger.info("System status updated")
        
        logger.info("Database setup verification completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Setup verification failed: {e}")
        return False


def main():
    """Main setup function."""
    parser = argparse.ArgumentParser(description="Set up the EDS database")
    parser.add_argument(
        "--config", 
        help="Path to configuration file",
        default=None
    )
    parser.add_argument(
        "--force-recreate",
        action="store_true",
        help="Drop existing tables and recreate (WARNING: destroys data)"
    )
    parser.add_argument(
        "--skip-tiles",
        action="store_true", 
        help="Skip tile initialization"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing setup"
    )
    
    args = parser.parse_args()
    
    logger.info("=== EDS Database Setup ===")
    
    if args.verify_only:
        logger.info("Running verification only...")
        if verify_setup():
            logger.info("Setup verification successful")
            sys.exit(0)
        else:
            logger.error("Setup verification failed")
            sys.exit(1)
    
    # Set up database
    if not setup_database(args.config, args.force_recreate):
        logger.error("Database setup failed")
        sys.exit(1)
    
    # Initialize tiles unless skipped
    if not args.skip_tiles:
        if not initialize_tiles():
            logger.error("Tile initialization failed")
            sys.exit(1)
    
    # Verify setup
    if not verify_setup():
        logger.error("Setup verification failed")
        sys.exit(1)
    
    logger.info("=== EDS Database Setup Complete ===")
    logger.info("You can now start the dashboard with: python src/dashboard/app.py")


if __name__ == "__main__":
    main()
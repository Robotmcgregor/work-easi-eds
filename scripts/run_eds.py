"""
Main application runner for the EDS system.
This script can start various components of the system.
"""

import sys
import logging
import argparse
import signal
import time
from pathlib import Path

# Add the src directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.config import load_config, validate_config
from src.database import init_database

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def start_dashboard(config_file=None, host=None, port=None, debug=None):
    """Start the web dashboard."""
    try:
        logger.info("Starting EDS Dashboard...")

        # Load configuration
        config = load_config(config_file)
        if not validate_config():
            logger.error("Configuration validation failed")
            return False

        # Initialize database
        init_database()

        # Override config with command line arguments
        dashboard_config = config.dashboard
        if host:
            dashboard_config.host = host
        if port:
            dashboard_config.port = port
        if debug is not None:
            dashboard_config.debug = debug

        # Import and run dashboard
        from src.dashboard.app import app

        logger.info(
            f"Dashboard starting on http://{dashboard_config.host}:{dashboard_config.port}"
        )
        app.run_server(
            debug=dashboard_config.debug,
            host=dashboard_config.host,
            port=dashboard_config.port,
        )

        return True

    except KeyboardInterrupt:
        logger.info("Dashboard stopped by user")
        return True
    except Exception as e:
        logger.error(f"Failed to start dashboard: {e}")
        return False


def start_scheduler(config_file=None):
    """Start the processing scheduler."""
    try:
        logger.info("Starting EDS Scheduler...")

        # Load configuration
        config = load_config(config_file)
        if not validate_config():
            logger.error("Configuration validation failed")
            return False

        # Check if scheduler is enabled
        if not config.processing.enable_scheduler:
            logger.warning("Scheduler is disabled in configuration")
            return False

        # Initialize database
        init_database()

        # Start scheduler
        from src.processing import start_scheduler

        start_scheduler()

        logger.info("Scheduler started. Press Ctrl+C to stop.")

        # Keep running until interrupted
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping scheduler...")
            from src.processing import stop_scheduler

            stop_scheduler()
            logger.info("Scheduler stopped")

        return True

    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        return False


def run_processing(
    config_file=None, tile_id=None, all_tiles=False, pending_only=False, days_back=7
):
    """Run EDS processing."""
    try:
        logger.info("Starting EDS Processing...")

        # Load configuration
        config = load_config(config_file)
        if not validate_config():
            logger.error("Configuration validation failed")
            return False

        # Initialize database
        init_database()

        from src.processing import EDSPipelineManager

        # Create processing config
        processing_config = EDSPipelineManager.create_processing_config(
            days_back=days_back
        )

        if tile_id:
            # Process single tile
            logger.info(f"Processing single tile: {tile_id}")
            result = EDSPipelineManager.run_tile_processing(tile_id, processing_config)

            if result.success:
                logger.info(
                    f"Processing successful: {result.alerts_detected} alerts detected"
                )
            else:
                logger.error(f"Processing failed: {result.error_message}")
                return False

        elif all_tiles:
            # Process all tiles
            logger.info("Processing all tiles...")
            results = EDSPipelineManager.run_automatic_processing(
                hours_since_last=0,  # Process all regardless of last processing time
                config=processing_config,
            )

            successful = sum(1 for r in results if r.success)
            total_alerts = sum(r.alerts_detected for r in results)

            logger.info(
                f"Batch processing complete: {successful}/{len(results)} successful, "
                f"{total_alerts} total alerts detected"
            )

        elif pending_only:
            # Process only pending/failed tiles
            logger.info("Processing pending and failed tiles...")
            results = EDSPipelineManager.run_automatic_processing(
                hours_since_last=24, config=processing_config
            )

            successful = sum(1 for r in results if r.success)
            total_alerts = sum(r.alerts_detected for r in results)

            logger.info(
                f"Pending processing complete: {successful}/{len(results)} successful, "
                f"{total_alerts} total alerts detected"
            )

        else:
            logger.error("Must specify --tile-id, --all-tiles, or --pending-only")
            return False

        return True

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        return False


def show_status(config_file=None):
    """Show system status."""
    try:
        logger.info("=== EDS System Status ===")

        # Load configuration
        config = load_config(config_file)
        if not validate_config():
            logger.error("Configuration validation failed")
            return False

        # Initialize database
        init_database()

        from src.database import TileManager, SystemStatusManager
        from src.processing import get_scheduler_status

        # System statistics
        stats = SystemStatusManager.get_system_stats()
        logger.info(f"Active jobs: {stats['active_jobs']}")
        logger.info(f"Alerts today: {stats['alerts_today']}")
        logger.info(f"Jobs processed today: {stats['jobs_today']}")

        # Tile statistics
        all_tiles = TileManager.get_all_tiles()
        pending_tiles = TileManager.get_tiles_by_status("pending")
        processing_tiles = TileManager.get_tiles_by_status("processing")
        failed_tiles = TileManager.get_tiles_by_status("failed")

        logger.info(f"Total tiles: {len(all_tiles)}")
        logger.info(f"Pending tiles: {len(pending_tiles)}")
        logger.info(f"Processing tiles: {len(processing_tiles)}")
        logger.info(f"Failed tiles: {len(failed_tiles)}")

        # Scheduler status
        scheduler_status = get_scheduler_status()
        logger.info(f"Scheduler running: {scheduler_status['running']}")

        return True

    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="EDS System Runner")
    parser.add_argument("--config", help="Path to configuration file", default=None)

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Dashboard command
    dashboard_parser = subparsers.add_parser(
        "dashboard", help="Start the web dashboard"
    )
    dashboard_parser.add_argument("--host", help="Dashboard host (default from config)")
    dashboard_parser.add_argument(
        "--port", type=int, help="Dashboard port (default from config)"
    )
    dashboard_parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode"
    )

    # Scheduler command
    scheduler_parser = subparsers.add_parser(
        "scheduler", help="Start the processing scheduler"
    )

    # Processing command
    process_parser = subparsers.add_parser("process", help="Run EDS processing")
    process_group = process_parser.add_mutually_exclusive_group(required=True)
    process_group.add_argument("--tile-id", help="Process specific tile ID")
    process_group.add_argument(
        "--all-tiles", action="store_true", help="Process all tiles"
    )
    process_group.add_argument(
        "--pending-only", action="store_true", help="Process only pending/failed tiles"
    )
    process_parser.add_argument(
        "--days-back", type=int, default=7, help="Days back for time range (default: 7)"
    )

    # Status command
    status_parser = subparsers.add_parser("status", help="Show system status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute command
    success = False

    if args.command == "dashboard":
        success = start_dashboard(
            config_file=args.config, host=args.host, port=args.port, debug=args.debug
        )

    elif args.command == "scheduler":
        success = start_scheduler(config_file=args.config)

    elif args.command == "process":
        success = run_processing(
            config_file=args.config,
            tile_id=args.tile_id,
            all_tiles=args.all_tiles,
            pending_only=args.pending_only,
            days_back=args.days_back,
        )

    elif args.command == "status":
        success = show_status(config_file=args.config)

    if success:
        logger.info("Command completed successfully")
        sys.exit(0)
    else:
        logger.error("Command failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

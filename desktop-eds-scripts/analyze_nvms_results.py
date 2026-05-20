#!/usr/bin/env python
"""
Query and analyze NVMS pilot results.
Provides detailed analysis of the three pilot runs and processing history.
"""

import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add src directory to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.database.nvms_models import NVMSRun, NVMSResult, ProcessingHistory
from src.config.settings import get_config


def analyze_processing_timeline():
    """Analyze when each tile was last processed and processing gaps."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)

    with db_manager.get_session() as session:
        print("\n" + "=" * 80)
        print("PROCESSING TIMELINE ANALYSIS")
        print("=" * 80)

        # Get all results with timing information
        results = session.query(NVMSResult).all()

        # Group by tile to find last processing time
        tile_last_processed = {}
        for result in results:
            tile_id = result.tile_id
            run_date = result.end_date_dt

            if (
                tile_id not in tile_last_processed
                or run_date > tile_last_processed[tile_id]["date"]
            ):
                tile_last_processed[tile_id] = {
                    "date": run_date,
                    "run": result.run_id,
                    "analyst": result.analyst,
                }

        print(f"\nTiles with processing history: {len(tile_last_processed)}")

        # Find tiles last processed by run
        by_run = {}
        for tile_id, info in tile_last_processed.items():
            run = info["run"]
            if run not in by_run:
                by_run[run] = []
            by_run[run].append((tile_id, info["date"]))

        for run_id in sorted(by_run.keys()):
            tiles = by_run[run_id]
            dates = [t[1] for t in tiles]
            print(f"\n{run_id}: {len(tiles)} tiles")
            print(f"  Date range: {min(dates)} to {max(dates)}")
            print(f"  Sample tiles: {[t[0] for t in tiles[:5]]}")

        # Find tiles in our database that haven't been processed
        all_tiles = session.query(LandsatTile).all()
        processed_tile_ids = set(tile_last_processed.keys())
        unprocessed_tiles = [
            tile for tile in all_tiles if tile.tile_id not in processed_tile_ids
        ]

        print(f"\nUnprocessed tiles in database: {len(unprocessed_tiles)}")
        if unprocessed_tiles:
            print(f"Sample unprocessed: {[t.tile_id for t in unprocessed_tiles[:10]]}")


def analyze_detection_patterns():
    """Analyze detection patterns across runs and tiles."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)

    with db_manager.get_session() as session:
        print("\n" + "=" * 80)
        print("DETECTION PATTERNS ANALYSIS")
        print("=" * 80)

        # Get all results with detections
        results = (
            session.query(NVMSResult)
            .filter((NVMSResult.cleared != None) | (NVMSResult.not_cleared != None))
            .all()
        )

        print(f"\nTiles with detection data: {len(results)}")

        # Analyze by run
        run_stats = {}
        for result in results:
            run_id = result.run_id
            if run_id not in run_stats:
                run_stats[run_id] = {
                    "tiles": 0,
                    "cleared": 0,
                    "not_cleared": 0,
                    "high_clearing_tiles": [],  # >50 cleared detections
                }

            run_stats[run_id]["tiles"] += 1
            run_stats[run_id]["cleared"] += result.cleared or 0
            run_stats[run_id]["not_cleared"] += result.not_cleared or 0

            if (result.cleared or 0) > 50:
                run_stats[run_id]["high_clearing_tiles"].append(
                    (result.tile_id, result.cleared, result.analyst)
                )

        for run_id, stats in run_stats.items():
            total = stats["cleared"] + stats["not_cleared"]
            clearing_rate = (stats["cleared"] / total * 100) if total > 0 else 0

            print(f"\n{run_id}:")
            print(f"  Tiles with detections: {stats['tiles']}")
            print(f"  Total detections: {total:,}")
            print(f"  Cleared: {stats['cleared']:,} ({clearing_rate:.1f}%)")
            print(f"  Not cleared: {stats['not_cleared']:,}")
            print(f"  High clearing tiles (>50): {len(stats['high_clearing_tiles'])}")

            if stats["high_clearing_tiles"]:
                print("  Top clearing tiles:")
                for tile_id, count, analyst in sorted(
                    stats["high_clearing_tiles"], key=lambda x: x[1], reverse=True
                )[:5]:
                    print(f"    {tile_id}: {count} cleared ({analyst})")


def analyze_analyst_performance():
    """Analyze analyst workload and patterns."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)

    with db_manager.get_session() as session:
        print("\n" + "=" * 80)
        print("ANALYST PERFORMANCE ANALYSIS")
        print("=" * 80)

        results = session.query(NVMSResult).all()

        analyst_stats = {}
        for result in results:
            analyst = result.analyst or "Unknown"
            run = result.run_id

            if analyst not in analyst_stats:
                analyst_stats[analyst] = {
                    "total_tiles": 0,
                    "runs": set(),
                    "tile_breakdown": {},
                }

            analyst_stats[analyst]["total_tiles"] += 1
            analyst_stats[analyst]["runs"].add(run)

            if run not in analyst_stats[analyst]["tile_breakdown"]:
                analyst_stats[analyst]["tile_breakdown"][run] = 0
            analyst_stats[analyst]["tile_breakdown"][run] += 1

        print(f"\nAnalysts involved: {len(analyst_stats)}")

        for analyst, stats in sorted(
            analyst_stats.items(), key=lambda x: x[1]["total_tiles"], reverse=True
        ):
            print(f"\n{analyst}:")
            print(f"  Total tiles processed: {stats['total_tiles']}")
            print(
                f"  Runs participated: {len(stats['runs'])} ({', '.join(sorted(stats['runs']))})"
            )
            print(f"  Breakdown by run:")
            for run in sorted(stats["tile_breakdown"].keys()):
                count = stats["tile_breakdown"][run]
                print(f"    {run}: {count} tiles")


def find_tile_processing_history(tile_id):
    """Find the complete processing history for a specific tile."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)

    with db_manager.get_session() as session:
        print(f"\n" + "=" * 80)
        print(f"PROCESSING HISTORY FOR TILE {tile_id}")
        print("=" * 80)

        # Get tile info
        tile = session.query(LandsatTile).filter(LandsatTile.tile_id == tile_id).first()
        if not tile:
            print(f"Tile {tile_id} not found in database")
            return

        print(f"Tile {tile_id} (Path {tile.path}, Row {tile.row})")
        print(f"Center: {tile.center_lat:.3f}, {tile.center_lon:.3f}")
        print(f"Current status: {tile.status}")
        print(f"Last processed: {tile.last_processed}")

        # Get NVMS results for this tile
        nvms_results = (
            session.query(NVMSResult)
            .filter(NVMSResult.tile_id == tile_id)
            .order_by(NVMSResult.start_date_dt)
            .all()
        )

        if nvms_results:
            print(f"\nNVMS Processing History ({len(nvms_results)} runs):")
            for result in nvms_results:
                total_detections = (result.cleared or 0) + (result.not_cleared or 0)
                print(f"\n  {result.run_id}:")
                print(
                    f"    Period: {result.start_date_dt.strftime('%Y-%m-%d')} to {result.end_date_dt.strftime('%Y-%m-%d')}"
                )
                print(f"    Analyst: {result.analyst or 'Unknown'}")
                print(f"    Visual check: {result.visual_check}")
                print(
                    f"    Detections: {total_detections} total ({result.cleared or 0} cleared, {result.not_cleared or 0} not cleared)"
                )
                if result.comments:
                    print(f"    Comments: {result.comments}")
        else:
            print(f"\nNo NVMS processing history found for tile {tile_id}")

        # Get processing history
        proc_history = (
            session.query(ProcessingHistory)
            .filter(ProcessingHistory.tile_id == tile_id)
            .order_by(ProcessingHistory.processed_at)
            .all()
        )

        if proc_history:
            print(f"\nProcessing History ({len(proc_history)} entries):")
            for history in proc_history:
                print(f"\n  {history.processing_run} ({history.processing_type}):")
                print(f"    Processed: {history.processed_at}")
                print(f"    Period: {history.time_start} to {history.time_end}")
                print(f"    Detections: {history.detections_total} total")
                print(f"    Status: {history.status}")


def main():
    """Main analysis function."""
    print("NVMS PILOT RESULTS ANALYSIS")
    print("=" * 80)

    # Run analyses
    analyze_processing_timeline()
    analyze_detection_patterns()
    analyze_analyst_performance()

    # Example tile analysis
    print("\n" + "=" * 80)
    print("SAMPLE TILE ANALYSIS")
    print("=" * 80)

    # Find a tile with lots of activity
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)

    with db_manager.get_session() as session:
        # Get a tile with high clearing detections
        high_activity_tile = (
            session.query(NVMSResult).filter(NVMSResult.cleared > 50).first()
        )

        if high_activity_tile:
            find_tile_processing_history(high_activity_tile.tile_id)

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print("\nTo analyze a specific tile, run:")
    print("  py analyze_nvms_results.py <tile_id>")
    print("\nExample: py analyze_nvms_results.py 091089")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Analyze specific tile
        tile_id = sys.argv[1]
        find_tile_processing_history(tile_id)
    else:
        # Run full analysis
        main()

#!/usr/bin/env python
"""
Summary report of NVMS pilot results processing times and tile coverage.
Answers the key questions: when were tiles run and when was the last check.
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

def generate_summary_report():
    """Generate a comprehensive summary report."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)
    
    with db_manager.get_session() as session:
        print("NVMS PILOT RESULTS - PROCESSING SUMMARY REPORT")
        print("=" * 70)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Get all runs
        runs = session.query(NVMSRun).order_by(NVMSRun.run_id).all()
        print(f"PILOT RUNS OVERVIEW ({len(runs)} runs)")
        print("-" * 50)
        
        for run in runs:
            # Get results for this run
            results = session.query(NVMSResult).filter(
                NVMSResult.run_id == run.run_id
            ).all()
            
            if results:
                dates = [r.start_date_dt for r in results if r.start_date_dt]
                end_dates = [r.end_date_dt for r in results if r.end_date_dt]
                analysts = set(r.analyst for r in results if r.analyst)
                
                total_detections = sum((r.cleared or 0) + (r.not_cleared or 0) for r in results)
                total_cleared = sum(r.cleared or 0 for r in results)
                
                print(f"\n{run.run_id}:")
                print(f"  Tiles processed: {len(results)}")
                print(f"  Time period: {min(dates).strftime('%Y-%m-%d')} to {max(end_dates).strftime('%Y-%m-%d')}")
                print(f"  Analysts: {', '.join(sorted(analysts))}")
                print(f"  Total detections: {total_detections:,}")
                print(f"  Cleared detections: {total_cleared:,}")
        
        print(f"\n\nTILE PROCESSING STATUS")
        print("-" * 50)
        
        # Get all tiles and their last processing
        all_tiles = session.query(LandsatTile).all()
        
        # Find last processing time for each tile
        tile_status = {}
        for tile in all_tiles:
            # Get NVMS results for this tile
            nvms_results = session.query(NVMSResult).filter(
                NVMSResult.tile_id == tile.tile_id
            ).order_by(NVMSResult.end_date_dt.desc()).all()
            
            if nvms_results:
                last_result = nvms_results[0]
                tile_status[tile.tile_id] = {
                    'last_processed': last_result.end_date_dt,
                    'last_run': last_result.run_id,
                    'last_analyst': last_result.analyst,
                    'total_runs': len(nvms_results),
                    'path': tile.path,
                    'row': tile.row
                }
            else:
                tile_status[tile.tile_id] = {
                    'last_processed': None,
                    'last_run': None,
                    'last_analyst': None,
                    'total_runs': 0,
                    'path': tile.path,
                    'row': tile.row
                }
        
        # Summary statistics
        processed_tiles = [t for t in tile_status.values() if t['last_processed']]
        unprocessed_tiles = [t for t in tile_status.values() if not t['last_processed']]
        
        print(f"Total tiles in database: {len(all_tiles)}")
        print(f"Tiles with NVMS processing: {len(processed_tiles)}")
        print(f"Tiles never processed: {len(unprocessed_tiles)}")
        
        if processed_tiles:
            last_dates = [t['last_processed'] for t in processed_tiles]
            print(f"Most recent processing: {max(last_dates).strftime('%Y-%m-%d')}")
            print(f"Oldest processing: {min(last_dates).strftime('%Y-%m-%d')}")
        
        # Group by last processing date
        print(f"\n\nTILES BY LAST PROCESSING DATE")
        print("-" * 50)
        
        from collections import defaultdict
        by_date = defaultdict(list)
        
        for tile_id, info in tile_status.items():
            if info['last_processed']:
                date_str = info['last_processed'].strftime('%Y-%m-%d')
                by_date[date_str].append((tile_id, info))
        
        for date in sorted(by_date.keys(), reverse=True):
            tiles = by_date[date]
            runs = set(info['last_run'] for _, info in tiles)
            print(f"\n{date}: {len(tiles)} tiles (Runs: {', '.join(sorted(runs))})")
            
            # Show sample tiles
            sample_tiles = tiles[:5]
            for tile_id, info in sample_tiles:
                print(f"  {tile_id} (P{info['path']}/R{info['row']}) - {info['last_run']} by {info['last_analyst']}")
            
            if len(tiles) > 5:
                print(f"  ... and {len(tiles) - 5} more tiles")
        
        # Show unprocessed areas
        if unprocessed_tiles:
            print(f"\n\nUNPROCESSED TILES ({len(unprocessed_tiles)} tiles)")
            print("-" * 50)
            
            # Group by path/row for geographic context
            paths = sorted(set(t['path'] for t in unprocessed_tiles))
            print(f"Unprocessed paths: {min(paths)} to {max(paths)}")
            
            # Show sample
            sample_unprocessed = unprocessed_tiles[:10]
            for tile_info in sample_unprocessed:
                tile_id = next(tid for tid, info in tile_status.items() if info == tile_info)
                print(f"  {tile_id} (Path {tile_info['path']}, Row {tile_info['row']})")
            
            if len(unprocessed_tiles) > 10:
                print(f"  ... and {len(unprocessed_tiles) - 10} more tiles")
        
        print(f"\n\nHIGH ACTIVITY TILES")
        print("-" * 50)
        
        # Find tiles with multiple runs or high detections
        multi_run_tiles = [
            (tid, info) for tid, info in tile_status.items() 
            if info['total_runs'] > 1
        ]
        
        print(f"Tiles processed multiple times: {len(multi_run_tiles)}")
        
        for tile_id, info in multi_run_tiles[:10]:
            print(f"  {tile_id} (P{info['path']}/R{info['row']}): {info['total_runs']} runs, last: {info['last_processed'].strftime('%Y-%m-%d')} ({info['last_run']})")
        
        # High detection tiles
        high_detection_tiles = session.query(NVMSResult).filter(
            NVMSResult.cleared > 20
        ).order_by(NVMSResult.cleared.desc()).all()
        
        if high_detection_tiles:
            print(f"\nTiles with high clearing activity (>20 cleared):")
            for result in high_detection_tiles[:10]:
                total = (result.cleared or 0) + (result.not_cleared or 0)
                print(f"  {result.tile_id}: {result.cleared} cleared / {total} total ({result.run_id}, {result.analyst})")
        
        print(f"\n\nSUMMARY")
        print("=" * 70)
        print(f"• Database contains {len(all_tiles)} Australian Landsat tiles")
        print(f"• {len(processed_tiles)} tiles have NVMS processing history")
        print(f"• {len(unprocessed_tiles)} tiles have never been processed")
        print(f"• {len(multi_run_tiles)} tiles have been processed multiple times")
        print(f"• Most recent processing: {max(last_dates).strftime('%Y-%m-%d') if processed_tiles else 'None'}")
        
        total_detections_all = session.query(NVMSResult).all()
        if total_detections_all:
            all_cleared = sum(r.cleared or 0 for r in total_detections_all)
            all_total = sum((r.cleared or 0) + (r.not_cleared or 0) for r in total_detections_all)
            print(f"• Total detections across all runs: {all_total:,}")
            print(f"• Total cleared detections: {all_cleared:,} ({all_cleared/all_total*100:.1f}%)")
        
        print(f"\nFor detailed tile analysis, run: py analyze_nvms_results.py <tile_id>")

if __name__ == "__main__":
    generate_summary_report()
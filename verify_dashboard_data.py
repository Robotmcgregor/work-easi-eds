#!/usr/bin/env python
"""
Quick verification script to show what data is now in the dashboard.
"""

import sys
from pathlib import Path

# Add src directory to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.database.nvms_models import NVMSDetection, NVMSResult, NVMSRun
from src.config.settings import get_config


def main():
    print("EDS DASHBOARD DATA VERIFICATION")
    print("=" * 60)

    config = get_config()
    db = DatabaseManager(config.database.connection_url)

    with db.get_session() as session:
        # Count tiles
        total_tiles = session.query(LandsatTile).count()
        active_tiles = (
            session.query(LandsatTile).filter(LandsatTile.is_active == True).count()
        )

        print(f"📍 TILES:")
        print(f"   Total: {total_tiles}")
        print(f"   Active: {active_tiles}")

        # Count NVMS data
        runs = session.query(NVMSRun).count()
        results = session.query(NVMSResult).count()
        detections = session.query(NVMSDetection).count()

        print(f"\n🗂️  NVMS DATA:")
        print(f"   Runs: {runs}")
        print(f"   Results: {results}")
        print(f"   Detections: {detections}")

        # Sample some detection tiles
        if detections > 0:
            sample_dets = session.query(NVMSDetection).limit(5).all()
            print(f"\n🎯 SAMPLE DETECTIONS:")
            for det in sample_dets:
                print(f"   Tile {det.tile_id} ({det.run_id}): {det.properties}")

        print(f"\n🌐 DASHBOARD:")
        print(f"   URL: http://localhost:8050")
        print(
            f"   Shows: {active_tiles} tile markers + {detections} detection overlays"
        )
        print(f"   Basemap: OpenStreetMap (free)")

        # Status breakdown
        if active_tiles > 0:
            status_counts = {}
            for tile in (
                session.query(LandsatTile).filter(LandsatTile.is_active == True).all()
            ):
                status = tile.status
                status_counts[status] = status_counts.get(status, 0) + 1

            print(f"\n📊 TILE STATUS BREAKDOWN:")
            for status, count in sorted(status_counts.items()):
                print(f"   {status}: {count} tiles")


if __name__ == "__main__":
    main()

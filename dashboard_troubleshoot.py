#!/usr/bin/env python
"""
Quick data check for dashboard troubleshooting.
"""

import sys
from pathlib import Path
import json

# Add src to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.database.nvms_models import NVMSDetection, NVMSResult
from src.config.settings import get_config

def main():
    print("🔍 DASHBOARD TROUBLESHOOTING")
    print("=" * 60)
    
    config = get_config()
    db = DatabaseManager(config.database.connection_url)
    
    with db.get_session() as session:
        # Check basic data
        total_tiles = session.query(LandsatTile).count()
        print(f"📊 Total tiles in database: {total_tiles}")
        
        if total_tiles == 0:
            print("❌ NO TILES FOUND! This is the problem.")
            return
            
        # Check sample tile
        sample_tile = session.query(LandsatTile).first()
        print(f"📍 Sample tile: {sample_tile.tile_id}")
        print(f"   Center: {sample_tile.center_lat}, {sample_tile.center_lon}")
        print(f"   Has bounds: {'Yes' if sample_tile.bounds_geojson else 'No'}")
        
        if sample_tile.bounds_geojson:
            try:
                bounds = json.loads(sample_tile.bounds_geojson)
                coords = bounds['coordinates'][0]
                print(f"   Boundary points: {len(coords)}")
                print(f"   Sample point: {coords[0]}")
            except Exception as e:
                print(f"   ❌ Bounds JSON error: {e}")
        
        # Check coordinate ranges
        all_tiles = session.query(LandsatTile).all()
        lats = [t.center_lat for t in all_tiles]
        lons = [t.center_lon for t in all_tiles]
        
        print(f"\n📐 Coordinate ranges:")
        print(f"   Latitude: {min(lats):.2f} to {max(lats):.2f}")
        print(f"   Longitude: {min(lons):.2f} to {max(lons):.2f}")
        
        # Expected Australia ranges
        if min(lats) < -45 and max(lats) > -10 and min(lons) > 110 and max(lons) < 160:
            print("   ✅ Coordinates look like Australia")
        else:
            print("   ⚠️ Coordinates don't look like Australia")
            
        # Check NVMS data
        results = session.query(NVMSResult).count()
        detections = session.query(NVMSDetection).count()
        print(f"\n🗂️ NVMS data:")
        print(f"   Results: {results}")
        print(f"   Detections: {detections}")
        
        print(f"\n🌐 AVAILABLE DASHBOARDS:")
        print(f"   Main (enhanced): http://localhost:8050")
        print(f"   Debug: http://localhost:8051") 
        print(f"   Map test: http://localhost:8052")
        
        print(f"\n❓ TROUBLESHOOTING:")
        print("1. Open http://localhost:8052 first - do you see a map with 3 dots?")
        print("   - YES: Plotly works, go to step 2")
        print("   - NO: Browser/JavaScript issue, try different browser")
        print("")
        print("2. Open http://localhost:8051 - do you see debug info and red dots?")
        print("   - YES: Data loads OK, check main dashboard")
        print("   - NO: Data loading issue")
        print("")
        print("3. Check main dashboard http://localhost:8050")
        print("   - Should show metrics cards at top")
        print("   - Charts in middle")
        print("   - Large map at bottom")
        print("")
        print("4. In map, look for:")
        print("   - Australia outline (basemap)")
        print("   - Colored tile boundaries (lines)")
        print("   - Blue detection dots")
        print("   - Zoom controls")
        
        print(f"\n🎯 EXPECTED RESULTS:")
        print(f"   - {total_tiles} tile boundaries across Australia")
        print(f"   - Colored by last NVMS run (black/yellow/orange/red)")
        print(f"   - {detections} blue detection markers")
        print("   - OpenStreetMap basemap (roads, cities, etc.)")

if __name__ == "__main__":
    main()
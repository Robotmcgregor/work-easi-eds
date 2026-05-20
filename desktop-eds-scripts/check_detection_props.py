#!/usr/bin/env python
"""Quick script to check detection properties structure"""

import sys
from pathlib import Path

# Add src to Python path
proj_root = Path(__file__).parent
sys.path.insert(0, str(proj_root / "src"))

from src.database.connection import DatabaseManager
from src.database.nvms_models import NVMSDetection
from src.config.settings import get_config


def main():
    config = get_config()
    db = DatabaseManager(config.database.connection_url)

    with db.get_session() as session:
        # Get first few detections
        detections = session.query(NVMSDetection).limit(5).all()

        if not detections:
            print("No detections found")
            return

        print(f"Found {len(detections)} sample detections:")
        for i, det in enumerate(detections, 1):
            print(f"\nDetection {i} (ID {det.id}):")
            print(f"  Tile: {det.tile_id}")
            print(f"  Properties: {det.properties}")
            if det.properties and "IsClearing" in det.properties:
                print(f"  IsClearing: {det.properties['IsClearing']}")
            else:
                print("  No IsClearing field found")


if __name__ == "__main__":
    main()

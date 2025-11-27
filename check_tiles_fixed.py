import sys
sys.path.insert(0, 'src')

from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.config.settings import get_config

config = get_config()
db = DatabaseManager(config.database.connection_url)

with db.get_session() as session:
    tiles = session.query(LandsatTile).all()
    print(f'Total tiles in database: {len(tiles)}')
    
    if tiles:
        # Check geographic distribution
        lats = [t.center_lat for t in tiles if t.center_lat]
        lons = [t.center_lon for t in tiles if t.center_lon]
        paths = [t.path for t in tiles if t.path]
        rows = [t.row for t in tiles if t.row]
        
        print(f'\nGeographic coverage:')
        print(f'Latitude range: {min(lats):.1f} to {max(lats):.1f}')
        print(f'Longitude range: {min(lons):.1f} to {max(lons):.1f}')
        
        print(f'\nLandsat Path/Row coverage:')
        print(f'Paths: {min(paths)} to {max(paths)} ({len(set(paths))} unique paths)')
        print(f'Rows: {min(rows)} to {max(rows)} ({len(set(rows))} unique rows)')
        
        # List all unique paths with proper formatting
        unique_paths = sorted(set(paths))
        formatted_paths = [f'{p:03d}' for p in unique_paths]
        print(f'All paths (formatted): {formatted_paths}')
        
        # Check for missing paths in Australia range
        australia_paths = list(range(89, 117))  # Australia spans roughly 89-116
        missing_paths = [p for p in australia_paths if p not in unique_paths]
        formatted_missing = [f'{p:03d}' for p in missing_paths]
        print(f'Missing paths in Australia range (089-116): {formatted_missing}')
        
        # Sample tiles with proper formatting
        print(f'\nSample tiles:')
        for tile in tiles[:10]:
            print(f'  {tile.tile_id}: Path {tile.path:03d}, Row {tile.row:03d} - ({tile.center_lat:.1f}, {tile.center_lon:.1f})')
    else:
        print('No tiles found in database!')
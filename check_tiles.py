import sys
sys.path.insert(0, 'src')

from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.config.settings import get_config

config = get_config()
db = DatabaseManager(config.database.connection_url)

with db.get_session() as session:
    tiles = session.query(LandsatTile).all()
    print(f'Total tiles: {len(tiles)}')
    
    # Check bounds
    lats = [t.center_lat for t in tiles if t.center_lat]
    lons = [t.center_lon for t in tiles if t.center_lon]
    
    print(f'Latitude range: {min(lats):.1f} to {max(lats):.1f}')
    print(f'Longitude range: {min(lons):.1f} to {max(lons):.1f}')
    
    # Check paths
    paths = set()
    for tile in tiles:
        if tile.path_row:
            path = int(tile.path_row.split('_')[0])
            paths.add(path)
    
    print(f'Paths available: {sorted(paths)}')
    print(f'Path range: {min(paths)} to {max(paths)}')
    
    # Check for specific missing paths
    australia_paths = list(range(89, 117))  # Australia spans roughly paths 89-116
    missing = [p for p in australia_paths if p not in paths]
    print(f'Missing Australia paths: {missing}')
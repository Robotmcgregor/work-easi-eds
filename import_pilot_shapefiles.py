#!/usr/bin/env python
"""
Import NVMS pilot run shapefile data and link to existing results.
These shapefiles contain the actual detection polygons from the pilot runs.
"""

import sys
import os
import re
from pathlib import Path
import geopandas as gpd
from datetime import datetime
import pandas as pd

# Add src directory to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from src.database.connection import DatabaseManager
from src.database.models import LandsatTile
from src.database.nvms_models import NVMSRun, NVMSResult, ProcessingHistory
from src.config.settings import get_config
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape
import shapely.geometry

def create_detection_table():
    """Create table for storing individual detection polygons."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)
    
    # Define the detection table
    from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime, Text, ForeignKey
    from geoalchemy2 import Geometry
    
    engine = create_engine(config.database.connection_url)
    metadata = MetaData()
    
    # Create detections table
    detections_table = Table(
        'nvms_detections',
        metadata,
        Column('id', Integer, primary_key=True),
        Column('tile_id', String(10), ForeignKey('landsat_tiles.tile_id')),
        Column('run_id', String(50), ForeignKey('nvms_runs.run_id')),
        Column('detection_id', String(50)),  # From shapefile
        Column('detection_type', String(20)),  # cleared/not_cleared
        Column('confidence', Float),
        Column('area_ha', Float),
        Column('detection_date', DateTime),
        Column('geometry', Geometry('POLYGON', srid=4326)),
        Column('source_file', String(255)),
        Column('attributes', Text),  # JSON for additional attributes
        Column('created_at', DateTime, default=datetime.utcnow)
    )
    
    # Drop and recreate table
    try:
        detections_table.drop(engine, checkfirst=True)
        print("Dropped existing nvms_detections table")
    except:
        pass
    
    metadata.create_all(engine)
    print("Created nvms_detections table")

def parse_shapefile_name(filename):
    """Parse shapefile name to extract tile and date information."""
    # Example: lzolre_p089r080_d2023102420240831_dlwm6
    pattern = r'lzolre_p(\d{3})r(\d{3})_d(\d{8})(\d{8})_(\w+)'
    match = re.match(pattern, filename)
    
    if match:
        path = int(match.group(1))
        row = int(match.group(2))
        start_date = datetime.strptime(match.group(3), '%Y%m%d')
        end_date = datetime.strptime(match.group(4), '%Y%m%d')
        version = match.group(5)
        
        # Format tile_id as expected (3-digit path + 3-digit row)
        tile_id = f"{path:03d}{row:03d}"
        
        return {
            'tile_id': tile_id,
            'path': path,
            'row': row,
            'start_date': start_date,
            'end_date': end_date,
            'version': version
        }
    
    return None

def import_shapefile_detections():
    """Import detection polygons from shapefiles."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)
    
    shapefile_dir = Path("data/pilot_shp")
    
    with db_manager.get_session() as session:
        total_imported = 0
        
        for shp_folder in shapefile_dir.iterdir():
            if not shp_folder.is_dir():
                continue
                
            print(f"\nProcessing folder: {shp_folder.name}")
            
            # Parse folder name to get tile info
            tile_info = parse_shapefile_name(shp_folder.name)
            if not tile_info:
                print(f"Could not parse folder name: {shp_folder.name}")
                continue
            
            # Find the shapefile
            shp_file = shp_folder / f"{shp_folder.name}.shp"
            if not shp_file.exists():
                print(f"Shapefile not found: {shp_file}")
                continue
            
            # Check if this tile exists in our database
            tile = session.query(LandsatTile).filter(
                LandsatTile.tile_id == tile_info['tile_id']
            ).first()
            
            if not tile:
                print(f"Tile {tile_info['tile_id']} not found in database")
                continue
            
            # Find corresponding NVMS result
            nvms_result = session.query(NVMSResult).filter(
                NVMSResult.tile_id == tile_info['tile_id'],
                NVMSResult.run_id == 'NVMS_QLD_Run03'  # These shapefiles are from Run 3
            ).first()
            
            if not nvms_result:
                print(f"No NVMS result found for tile {tile_info['tile_id']} in Run 3")
                continue
            
            try:
                # Read shapefile
                gdf = gpd.read_file(shp_file)
                print(f"Read {len(gdf)} features from {shp_file.name}")
                
                # Print column names for debugging
                print(f"Columns: {list(gdf.columns)}")
                print(f"Sample data:\n{gdf.head()}")
                
                # Convert to WGS84 if needed
                if gdf.crs and gdf.crs.to_epsg() != 4326:
                    gdf = gdf.to_crs(epsg=4326)
                
                # Import each detection
                for idx, feature in gdf.iterrows():
                    # Create detection record
                    detection_data = {
                        'tile_id': tile_info['tile_id'],
                        'run_id': 'NVMS_QLD_Run03',
                        'detection_id': f"{tile_info['tile_id']}_{idx:04d}",
                        'detection_type': 'unknown',  # Will determine from attributes
                        'geometry': from_shape(feature.geometry, srid=4326),
                        'source_file': shp_file.name,
                        'detection_date': tile_info['end_date'],
                        'created_at': datetime.utcnow()
                    }
                    
                    # Extract attributes (column names vary by shapefile)
                    attributes = {}
                    for col in gdf.columns:
                        if col != 'geometry':
                            val = feature[col]
                            if pd.notna(val):
                                attributes[col] = str(val)
                    
                    detection_data['attributes'] = str(attributes)
                    
                    # Try to determine detection type and confidence from attributes
                    # Common column names: 'class', 'type', 'cleared', 'confidence', etc.
                    for col_name, value in attributes.items():
                        col_lower = col_name.lower()
                        if 'clear' in col_lower or 'class' in col_lower:
                            if 'clear' in str(value).lower():
                                detection_data['detection_type'] = 'cleared'
                            elif 'not' in str(value).lower():
                                detection_data['detection_type'] = 'not_cleared'
                        
                        if 'conf' in col_lower:
                            try:
                                detection_data['confidence'] = float(value)
                            except:
                                pass
                    
                    # Calculate area if not provided
                    try:
                        # Area in hectares (geometry is in WGS84, so we need to project for accurate area)
                        geom_utm = gpd.GeoSeries([feature.geometry], crs='EPSG:4326').to_crs('EPSG:3577')  # Australian Albers
                        area_m2 = geom_utm.area.iloc[0]
                        detection_data['area_ha'] = area_m2 / 10000.0
                    except:
                        detection_data['area_ha'] = None
                    
                    # Insert into database
                    from sqlalchemy import text
                    insert_sql = text("""
                        INSERT INTO nvms_detections 
                        (tile_id, run_id, detection_id, detection_type, confidence, area_ha, 
                         detection_date, geometry, source_file, attributes, created_at)
                        VALUES 
                        (:tile_id, :run_id, :detection_id, :detection_type, :confidence, :area_ha,
                         :detection_date, ST_GeomFromWKB(:geometry, 4326), :source_file, :attributes, :created_at)
                    """)
                    
                    session.execute(insert_sql, {
                        'tile_id': detection_data['tile_id'],
                        'run_id': detection_data['run_id'],
                        'detection_id': detection_data['detection_id'],
                        'detection_type': detection_data['detection_type'],
                        'confidence': detection_data['confidence'],
                        'area_ha': detection_data['area_ha'],
                        'detection_date': detection_data['detection_date'],
                        'geometry': detection_data['geometry'].data,
                        'source_file': detection_data['source_file'],
                        'attributes': detection_data['attributes'],
                        'created_at': detection_data['created_at']
                    })
                
                session.commit()
                total_imported += len(gdf)
                print(f"Imported {len(gdf)} detections for tile {tile_info['tile_id']}")
                
            except Exception as e:
                print(f"Error processing {shp_file}: {e}")
                session.rollback()
                continue
        
        print(f"\nTotal detections imported: {total_imported}")

def verify_import():
    """Verify the imported shapefile data."""
    config = get_config()
    db_manager = DatabaseManager(config.database.connection_url)
    
    with db_manager.get_session() as session:
        from sqlalchemy import text
        
        # Count total detections
        result = session.execute(text("SELECT COUNT(*) FROM nvms_detections")).scalar()
        print(f"Total detections in database: {result}")
        
        # Count by tile
        results = session.execute(text("""
            SELECT tile_id, COUNT(*) as detection_count,
                   COUNT(CASE WHEN detection_type = 'cleared' THEN 1 END) as cleared_count,
                   COUNT(CASE WHEN detection_type = 'not_cleared' THEN 1 END) as not_cleared_count,
                   AVG(area_ha) as avg_area_ha
            FROM nvms_detections 
            GROUP BY tile_id
            ORDER BY detection_count DESC
        """)).fetchall()
        
        print(f"\nDetections by tile:")
        for row in results:
            print(f"  {row[0]}: {row[1]} total ({row[2]} cleared, {row[3]} not cleared, avg {row[4]:.2f} ha)")
        
        # Sample some detection attributes
        sample = session.execute(text("""
            SELECT tile_id, detection_type, area_ha, attributes
            FROM nvms_detections 
            LIMIT 5
        """)).fetchall()
        
        print(f"\nSample detections:")
        for row in sample:
            print(f"  {row[0]}: {row[1]}, {row[2]:.2f} ha, attrs: {row[3][:100]}...")

def main():
    """Main import function."""
    print("NVMS PILOT SHAPEFILE IMPORT")
    print("=" * 50)
    
    # Create detection table
    create_detection_table()
    
    # Import shapefiles
    import_shapefile_detections()
    
    # Verify import
    verify_import()
    
    print("\nShapefile import complete!")
    print("Detection polygons are now linked to NVMS results.")

if __name__ == "__main__":
    main()
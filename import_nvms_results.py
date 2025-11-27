#!/usr/bin/env python
"""
Import NVMS pilot results into the EDS database.
Processes Run01, Run02, and Run03 CSV files and creates processing history.
"""

import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
import logging

# Add src directory to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from src.database.connection import DatabaseManager
from src.database.models import Base, LandsatTile
from src.database.nvms_models import NVMSRun, NVMSResult, ProcessingHistory
from src.config.settings import get_config
from sqlalchemy import create_engine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/nvms_import.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def create_nvms_tables(db_manager):
    """Create NVMS-specific tables if they don't exist."""
    try:
        # Import the models to register them
        from src.database.nvms_models import NVMSRun, NVMSResult, ProcessingHistory
        
        # Create tables
        Base.metadata.create_all(db_manager.engine)
        logger.info("NVMS tables created successfully")
        return True
    except Exception as e:
        logger.error(f"Error creating NVMS tables: {e}")
        return False

def clean_string_value(value):
    """Clean string values, converting NaN to empty string or None."""
    if pd.isna(value) or str(value).lower() == 'nan':
        return None
    return str(value).strip()

def parse_date_string(date_input):
    """Parse date string/datetime from various formats to datetime."""
    if pd.isna(date_input) or date_input == '':
        return None
    
    # If it's already a datetime object, return it
    if isinstance(date_input, datetime):
        return date_input
    
    # Try parsing string formats
    try:
        date_str = str(date_input).strip()
        
        # Try format '20230304' (YYYYMMDD)
        if len(date_str) == 8 and date_str.isdigit():
            return datetime.strptime(date_str, '%Y%m%d')
        
        # Try ISO format 'YYYY-MM-DD'
        if '-' in date_str and len(date_str) == 10:
            return datetime.strptime(date_str, '%Y-%m-%d')
            
        # Try parsing as datetime string
        return pd.to_datetime(date_input)
        
    except (ValueError, TypeError):
        logger.warning(f"Could not parse date: {date_input}")
        return None

def import_nvms_run(csv_path, run_id, run_number, db_manager):
    """Import a single NVMS run from CSV file."""
    logger.info(f"Importing {run_id} from {csv_path}")
    
    # Read CSV file
    try:
        df = pd.read_csv(csv_path)
        logger.info(f"Loaded {len(df)} records from {csv_path}")
    except Exception as e:
        logger.error(f"Error reading CSV file: {e}")
        return False
    
    with db_manager.get_session() as session:
        # Create or update NVMS run record
        nvms_run = session.query(NVMSRun).filter(NVMSRun.run_id == run_id).first()
        if not nvms_run:
            nvms_run = NVMSRun(
                run_id=run_id,
                run_number=run_number,
                description=f"NVMS Queensland Run {run_number:02d} - Pilot land clearing detection results"
            )
            session.add(nvms_run)
            session.flush()  # Get the ID
        
        imported_count = 0
        updated_count = 0
        error_count = 0
        
        for idx, row in df.iterrows():
            try:
                # Extract tile information
                path = int(row['path']) if pd.notna(row['path']) else None
                row_num = int(row['row']) if pd.notna(row['row']) else None
                
                if not path or not row_num:
                    logger.warning(f"Row {idx}: Missing path/row information")
                    error_count += 1
                    continue
                
                tile_id = f"{path:03d}{row_num:03d}"
                
                # Check if tile exists in the database
                tile = session.query(LandsatTile).filter(LandsatTile.tile_id == tile_id).first()
                if not tile:
                    logger.warning(f"Tile {tile_id} not found in database, skipping")
                    error_count += 1
                    continue
                
                # Parse dates
                start_date_dt = parse_date_string(row.get('start_date_dt'))
                end_date_dt = parse_date_string(row.get('end_date_dt'))
                
                if not start_date_dt or not end_date_dt:
                    logger.warning(f"Row {idx}: Invalid date information for tile {tile_id}")
                    error_count += 1
                    continue
                
                # Check if result already exists
                existing_result = session.query(NVMSResult).filter(
                    NVMSResult.run_id == run_id,
                    NVMSResult.tile_id == tile_id
                ).first()
                
                if existing_result:
                    # Update existing record
                    existing_result.visual_check = clean_string_value(row.get('visual_check'))
                    existing_result.analyst = clean_string_value(row.get('analyst'))
                    existing_result.comments = clean_string_value(row.get('comments'))
                    existing_result.shp_path = clean_string_value(row.get('shp_path'))
                    existing_result.cleared = int(row['cleared']) if pd.notna(row.get('cleared')) else None
                    existing_result.not_cleared = int(row['not_cleared']) if pd.notna(row.get('not_cleared')) else None
                    existing_result.supplied_to_ceb = clean_string_value(row.get('supplied_to_ceb'))
                    existing_result.start_date = clean_string_value(row.get('start_date'))
                    existing_result.end_date = clean_string_value(row.get('end_date'))
                    existing_result.start_date_dt = start_date_dt
                    existing_result.end_date_dt = end_date_dt
                    updated_count += 1
                else:
                    # Create new result record
                    nvms_result = NVMSResult(
                        run_id=run_id,
                        tile_id=tile_id,
                        visual_check=clean_string_value(row.get('visual_check')),
                        analyst=clean_string_value(row.get('analyst')),
                        comments=clean_string_value(row.get('comments')),
                        shp_path=clean_string_value(row.get('shp_path')),
                        cleared=int(row['cleared']) if pd.notna(row.get('cleared')) else None,
                        not_cleared=int(row['not_cleared']) if pd.notna(row.get('not_cleared')) else None,
                        supplied_to_ceb=clean_string_value(row.get('supplied_to_ceb')),
                        start_date=clean_string_value(row.get('start_date')),
                        end_date=clean_string_value(row.get('end_date')),
                        start_date_dt=start_date_dt,
                        end_date_dt=end_date_dt,
                        path=path,
                        row=row_num
                    )
                    session.add(nvms_result)
                    imported_count += 1
                
                # Create or update processing history entry
                existing_history = session.query(ProcessingHistory).filter(
                    ProcessingHistory.tile_id == tile_id,
                    ProcessingHistory.processing_run == run_id
                ).first()
                
                if not existing_history:
                    # Calculate totals
                    cleared_count = int(row['cleared']) if pd.notna(row.get('cleared')) else 0
                    not_cleared_count = int(row['not_cleared']) if pd.notna(row.get('not_cleared')) else 0
                    total_detections = cleared_count + not_cleared_count
                    
                    processing_history = ProcessingHistory(
                        tile_id=tile_id,
                        processing_type='NVMS_PILOT',
                        processing_run=run_id,
                        time_start=start_date_dt,
                        time_end=end_date_dt,
                        detections_total=total_detections,
                        detections_cleared=cleared_count,
                        detections_not_cleared=not_cleared_count,
                        analyst=clean_string_value(row.get('analyst')),
                        status='completed',
                        notes=clean_string_value(row.get('comments'))
                    )
                    session.add(processing_history)
                
            except Exception as e:
                logger.error(f"Error processing row {idx} for tile {tile_id}: {e}")
                error_count += 1
                continue
        
        # Commit all changes
        session.commit()
        
        logger.info(f"{run_id} import complete:")
        logger.info(f"  - New records: {imported_count}")
        logger.info(f"  - Updated records: {updated_count}")
        logger.info(f"  - Errors: {error_count}")
        
        return True

def generate_summary_report(db_manager):
    """Generate a summary report of all NVMS data."""
    with db_manager.get_session() as session:
        # Get run summaries
        runs = session.query(NVMSRun).order_by(NVMSRun.run_number).all()
        
        print("\n" + "="*60)
        print("NVMS PILOT RESULTS SUMMARY")
        print("="*60)
        
        for run in runs:
            results = session.query(NVMSResult).filter(NVMSResult.run_id == run.run_id).all()
            
            if not results:
                continue
                
            # Calculate statistics
            total_tiles = len(results)
            tiles_with_clearing = len([r for r in results if r.cleared and r.cleared > 0])
            total_cleared = sum(r.cleared for r in results if r.cleared)
            total_not_cleared = sum(r.not_cleared for r in results if r.not_cleared)
            total_detections = (total_cleared or 0) + (total_not_cleared or 0)
            
            # Get date ranges
            start_dates = [r.start_date_dt for r in results if r.start_date_dt]
            end_dates = [r.end_date_dt for r in results if r.end_date_dt]
            
            earliest_start = min(start_dates) if start_dates else "Unknown"
            latest_end = max(end_dates) if end_dates else "Unknown"
            
            # Get analyst breakdown
            analysts = {}
            for result in results:
                analyst = result.analyst or 'Unknown'
                analysts[analyst] = analysts.get(analyst, 0) + 1
            
            print(f"\n{run.run_id}:")
            print(f"  Tiles processed: {total_tiles}")
            print(f"  Tiles with clearing detected: {tiles_with_clearing}")
            print(f"  Total detections: {total_detections}")
            print(f"    - Cleared: {total_cleared or 0}")
            print(f"    - Not cleared: {total_not_cleared or 0}")
            print(f"  Date range: {earliest_start} to {latest_end}")
            print(f"  Analysts: {dict(analysts)}")
            
            # Show path/row coverage
            paths = sorted(set(r.path for r in results if r.path))
            rows = sorted(set(r.row for r in results if r.row))
            if paths and rows:
                print(f"  Path coverage: {min(paths)}-{max(paths)} ({len(paths)} paths)")
                print(f"  Row coverage: {min(rows)}-{max(rows)} ({len(rows)} rows)")

def main():
    """Main function to import all NVMS pilot results."""
    try:
        logger.info("Starting NVMS pilot results import...")
        
        # Initialize database
        config = get_config()
        db_manager = DatabaseManager(config.database.connection_url)
        
        # Create NVMS tables
        if not create_nvms_tables(db_manager):
            logger.error("Failed to create NVMS tables")
            return
        
        # Define CSV files and run information
        pilot_data_dir = project_root / "data" / "pilot_results"
        runs_to_import = [
            {
                'csv_path': pilot_data_dir / "NVMS_QLD_Run01_Processed_Record_clean.csv",
                'run_id': 'NVMS_QLD_Run01',
                'run_number': 1
            },
            {
                'csv_path': pilot_data_dir / "NVMS_QLD_Run02_Processed_Record_clean.csv",
                'run_id': 'NVMS_QLD_Run02',
                'run_number': 2
            },
            {
                'csv_path': pilot_data_dir / "NVMS_QLD_Run03_Processed_Record_clean.csv",
                'run_id': 'NVMS_QLD_Run03',
                'run_number': 3
            }
        ]
        
        # Import each run
        for run_info in runs_to_import:
            if run_info['csv_path'].exists():
                success = import_nvms_run(
                    run_info['csv_path'],
                    run_info['run_id'],
                    run_info['run_number'],
                    db_manager
                )
                if not success:
                    logger.error(f"Failed to import {run_info['run_id']}")
            else:
                logger.warning(f"CSV file not found: {run_info['csv_path']}")
        
        # Generate summary report
        generate_summary_report(db_manager)
        
        logger.info("NVMS pilot results import completed successfully")
        
        print("\n" + "="*60)
        print("NEXT STEPS:")
        print("1. View results in dashboard: py start_dashboard.py")
        print("2. Query processing history by tile")
        print("3. Compare pilot results with live EDS processing")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Error during NVMS import: {e}")
        raise

if __name__ == "__main__":
    main()
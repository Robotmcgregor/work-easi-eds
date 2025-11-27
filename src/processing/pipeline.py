"""
Core EDS (Early Detection System) processing pipeline.
This module handles the execution of land clearing detection algorithms on Landsat tiles.
"""

import os
import logging
import subprocess
import tempfile
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import concurrent.futures
from dataclasses import dataclass
import time

from ..database import TileManager, JobManager, AlertManager, ProcessingStatus
from ..utils.tile_management import get_australian_tile_grid

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of EDS processing on a tile."""
    success: bool
    tile_id: str
    processing_time: float
    alerts_detected: int
    area_processed_ha: float
    error_message: str = None
    output_files: List[str] = None


@dataclass
class ProcessingConfig:
    """Configuration for EDS processing."""
    # Time range for processing
    start_date: datetime
    end_date: datetime
    
    # Processing parameters
    confidence_threshold: float = 0.7
    min_clearing_area_ha: float = 1.0
    max_cloud_coverage: float = 20.0
    
    # Output settings
    output_directory: str = None
    save_intermediate_files: bool = False
    
    # Resource limits
    max_concurrent_jobs: int = 4
    timeout_minutes: int = 60


class EDSProcessor:
    """
    Main EDS processing class that handles land clearing detection on Landsat tiles.
    
    This is a framework for integrating your existing EDS algorithms.
    Replace the mock processing methods with calls to your actual EDS code.
    """
    
    def __init__(self, config: ProcessingConfig):
        """
        Initialize the EDS processor.
        
        Args:
            config: Processing configuration
        """
        self.config = config
        self.tile_grid = get_australian_tile_grid()
        
        # Set up output directory
        if not self.config.output_directory:
            self.config.output_directory = os.path.join(
                os.getcwd(), 'data', 'processing_results'
            )
        os.makedirs(self.config.output_directory, exist_ok=True)
        
        logger.info(f"EDS Processor initialized with output directory: {self.config.output_directory}")
    
    def process_single_tile(self, tile_id: str) -> ProcessingResult:
        """
        Process a single Landsat tile for land clearing detection.
        
        Args:
            tile_id: The tile identifier (e.g., "090084")
            
        Returns:
            ProcessingResult with the outcomes of processing
        """
        start_time = time.time()
        
        try:
            logger.info(f"Starting EDS processing for tile {tile_id}")
            
            # Get tile information from database
            tile = TileManager.get_tile_by_id(tile_id)
            if not tile:
                raise ValueError(f"Tile {tile_id} not found in database")
            
            # Update tile status to processing
            TileManager.update_tile_status(tile_id, ProcessingStatus.PROCESSING.value)
            
            # Create processing job record
            job = JobManager.create_job(
                tile_id=tile_id,
                time_start=self.config.start_date,
                time_end=self.config.end_date
            )
            
            # Store job_id to avoid session issues
            job_id = job.job_id
            
            # Update job status
            JobManager.update_job_status(job_id, ProcessingStatus.PROCESSING.value, 0)
            
            # ***** REPLACE THIS SECTION WITH YOUR ACTUAL EDS ALGORITHM *****
            # This is where you would integrate your existing EDS code
            processing_result = self._run_eds_algorithm(tile, job_id)
            # ***** END REPLACEMENT SECTION *****
            
            processing_time = time.time() - start_time
            
            # Update job with results
            JobManager.update_job_status(
                job_id,
                ProcessingStatus.COMPLETED.value,
                100,
                None
            )
            
            # Update tile status
            TileManager.update_tile_status(
                tile_id,
                ProcessingStatus.COMPLETED.value,
                f"Processed successfully. {processing_result.alerts_detected} alerts detected."
            )
            
            logger.info(f"Completed processing tile {tile_id} in {processing_time:.2f}s. "
                       f"Detected {processing_result.alerts_detected} alerts.")
            
            return ProcessingResult(
                success=True,
                tile_id=tile_id,
                processing_time=processing_time,
                alerts_detected=processing_result.alerts_detected,
                area_processed_ha=processing_result.area_processed_ha,
                output_files=processing_result.output_files
            )
            
        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = f"Failed to process tile {tile_id}: {str(e)}"
            logger.error(error_msg)
            
            # Update job with error
            if 'job' in locals():
                JobManager.update_job_status(
                    job.job_id,
                    ProcessingStatus.FAILED.value,
                    0,
                    error_msg
                )
            
            # Update tile status
            TileManager.update_tile_status(
                tile_id,
                ProcessingStatus.FAILED.value,
                error_msg
            )
            
            return ProcessingResult(
                success=False,
                tile_id=tile_id,
                processing_time=processing_time,
                alerts_detected=0,
                area_processed_ha=0,
                error_message=error_msg
            )
    
    def _run_eds_algorithm(self, tile, job_id: str) -> ProcessingResult:
        """
        Run the actual EDS algorithm on a tile.
        
        **THIS IS A MOCK IMPLEMENTATION - REPLACE WITH YOUR ACTUAL EDS CODE**
        
        Args:
            tile: LandsatTile database object
            job_id: Processing job ID
            
        Returns:
            ProcessingResult with detection results
        """
        # ***** REPLACE THIS ENTIRE METHOD WITH YOUR EDS ALGORITHM *****
        
        # Acquire inputs: list/download from S3 to local cache if configured
        try:
            from .data_access import DataAccessor
            accessor = DataAccessor()
            local_inputs = accessor.ensure_local_inputs(
                tile_id=tile.tile_id,
                start=self.config.start_date.date(),
                end=self.config.end_date.date(),
                prefix=None,
                download=True,
                max_files=100
            )
            logger.info(f"Input files prepared for tile {tile.tile_id}: {len(local_inputs)} file(s)")
        except Exception as e:
            logger.warning(f"Data access step skipped or failed: {e}")

        # Simulate processing steps
        logger.info(f"Downloading Landsat data for tile {tile.tile_id}...")
        time.sleep(2)  # Simulate download time
        
        JobManager.update_job_status(job_id, ProcessingStatus.PROCESSING.value, 25)
        
        logger.info(f"Preprocessing imagery for tile {tile.tile_id}...")
        time.sleep(3)  # Simulate preprocessing
        
        JobManager.update_job_status(job_id, ProcessingStatus.PROCESSING.value, 50)
        
        logger.info(f"Running change detection for tile {tile.tile_id}...")
        time.sleep(4)  # Simulate change detection
        
        JobManager.update_job_status(job_id, ProcessingStatus.PROCESSING.value, 75)
        
        logger.info(f"Analyzing results for tile {tile.tile_id}...")
        time.sleep(2)  # Simulate analysis
        
        JobManager.update_job_status(job_id, ProcessingStatus.PROCESSING.value, 90)
        
        # Mock detection results
        import random
        alerts_detected = random.randint(0, 5)  # Random number of alerts
        
        # Create mock alerts if any detected
        for i in range(alerts_detected):
            # Generate random coordinates within tile bounds
            lat_offset = random.uniform(-0.9, 0.9)
            lon_offset = random.uniform(-0.9, 0.9)
            
            detection_lat = tile.center_lat + lat_offset
            detection_lon = tile.center_lon + lon_offset
            
            # Mock detection parameters
            confidence = random.uniform(self.config.confidence_threshold, 1.0)
            area_ha = random.uniform(self.config.min_clearing_area_ha, 50.0)
            detection_date = self.config.start_date + timedelta(
                days=random.randint(0, (self.config.end_date - self.config.start_date).days)
            )
            
            # Create alert in database
            AlertManager.create_alert(
                job_id=job_id,
                tile_id=tile.tile_id,
                detection_lat=detection_lat,
                detection_lon=detection_lon,
                detection_date=detection_date,
                confidence_score=confidence,
                area_hectares=area_ha,
                clearing_type="forest" if random.random() > 0.5 else "vegetation"
            )
        
        # Mock output files
        output_files = []
        if self.config.save_intermediate_files:
            output_files = [
                f"{self.config.output_directory}/tile_{tile.tile_id}_change_map.tif",
                f"{self.config.output_directory}/tile_{tile.tile_id}_alerts.json"
            ]
        
        return ProcessingResult(
            success=True,
            tile_id=tile.tile_id,
            processing_time=0,  # Will be calculated by caller
            alerts_detected=alerts_detected,
            area_processed_ha=185 * 185,  # Approximate Landsat tile area
            output_files=output_files
        )
        
        # ***** END MOCK IMPLEMENTATION - REPLACE WITH YOUR EDS CODE *****
    
    def process_multiple_tiles(self, tile_ids: List[str]) -> List[ProcessingResult]:
        """
        Process multiple tiles in parallel.
        
        Args:
            tile_ids: List of tile identifiers to process
            
        Returns:
            List of ProcessingResult objects
        """
        logger.info(f"Starting batch processing of {len(tile_ids)} tiles")
        
        results = []
        
        # Process tiles in parallel using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_concurrent_jobs
        ) as executor:
            
            # Submit all jobs
            future_to_tile = {
                executor.submit(self.process_single_tile, tile_id): tile_id
                for tile_id in tile_ids
            }
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_tile):
                tile_id = future_to_tile[future]
                try:
                    result = future.result(timeout=self.config.timeout_minutes * 60)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Exception processing tile {tile_id}: {e}")
                    results.append(ProcessingResult(
                        success=False,
                        tile_id=tile_id,
                        processing_time=0,
                        alerts_detected=0,
                        area_processed_ha=0,
                        error_message=str(e)
                    ))
        
        # Summary statistics
        successful = sum(1 for r in results if r.success)
        total_alerts = sum(r.alerts_detected for r in results)
        total_time = sum(r.processing_time for r in results)
        
        logger.info(f"Batch processing complete: {successful}/{len(tile_ids)} successful, "
                   f"{total_alerts} total alerts, {total_time:.2f}s total processing time")
        
        return results
    
    def process_tiles_needing_update(self, hours_since_last: int = 24) -> List[ProcessingResult]:
        """
        Process all tiles that need updates based on time since last processing.
        
        Args:
            hours_since_last: Number of hours since last processing to trigger reprocessing
            
        Returns:
            List of ProcessingResult objects
        """
        # Get tiles that need processing
        tiles_to_process = TileManager.get_tiles_needing_processing(hours_since_last)
        tile_ids = [tile.tile_id for tile in tiles_to_process]
        
        if not tile_ids:
            logger.info("No tiles need processing at this time")
            return []
        
        logger.info(f"Found {len(tile_ids)} tiles needing processing (last processed > {hours_since_last}h ago)")
        
        return self.process_multiple_tiles(tile_ids)
    
    def process_all_tiles(self) -> List[ProcessingResult]:
        """
        Process all active tiles in the system.
        
        Returns:
            List of ProcessingResult objects
        """
        all_tiles = TileManager.get_all_tiles(active_only=True)
        tile_ids = [tile.tile_id for tile in all_tiles]
        
        logger.info(f"Processing all {len(tile_ids)} active tiles")
        
        return self.process_multiple_tiles(tile_ids)


class EDSPipelineManager:
    """High-level manager for EDS processing operations."""
    
    @staticmethod
    def create_processing_config(days_back: int = 7, **kwargs) -> ProcessingConfig:
        """
        Create a processing configuration with sensible defaults.
        
        Args:
            days_back: Number of days back from today to set as start date
            **kwargs: Additional configuration parameters
            
        Returns:
            ProcessingConfig object
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)

        config = ProcessingConfig(
            start_date=start_date,
            end_date=end_date,
            **kwargs
        )

        return config
    
    @staticmethod
    def run_tile_processing(tile_id: str, config: ProcessingConfig = None) -> ProcessingResult:
        """
        Run EDS processing on a single tile.
        
        Args:
            tile_id: Tile identifier
            config: Processing configuration (uses defaults if None)
            
        Returns:
            ProcessingResult
        """
        if config is None:
            config = EDSPipelineManager.create_processing_config()
        
        processor = EDSProcessor(config)
        return processor.process_single_tile(tile_id)
    
    @staticmethod
    def run_batch_processing(tile_ids: List[str], config: ProcessingConfig = None) -> List[ProcessingResult]:
        """
        Run EDS processing on multiple tiles.
        
        Args:
            tile_ids: List of tile identifiers
            config: Processing configuration (uses defaults if None)
            
        Returns:
            List of ProcessingResult objects
        """
        if config is None:
            config = EDSPipelineManager.create_processing_config()
        
        processor = EDSProcessor(config)
        return processor.process_multiple_tiles(tile_ids)
    
    @staticmethod
    def run_automatic_processing(hours_since_last: int = 24, config: ProcessingConfig = None) -> List[ProcessingResult]:
        """
        Run automatic processing on tiles that need updates.
        
        Args:
            hours_since_last: Hours since last processing to trigger reprocessing
            config: Processing configuration (uses defaults if None)
            
        Returns:
            List of ProcessingResult objects
        """
        if config is None:
            # For automatic processing, use last processing time as reference
            last_tile = TileManager.get_tiles_needing_processing(1)
            if last_tile:
                # Calculate time range from last processing to now
                config = EDSPipelineManager.create_processing_config(days_back=1)
            else:
                config = EDSPipelineManager.create_processing_config()
        
        processor = EDSProcessor(config)
        return processor.process_tiles_needing_update(hours_since_last)
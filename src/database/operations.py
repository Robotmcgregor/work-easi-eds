"""
Database operations and queries for the EDS application.
"""

from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc
import logging
import uuid

from .models import LandsatTile, ProcessingJob, DetectionAlert, SystemStatus, ProcessingStatus
from .connection import get_db

logger = logging.getLogger(__name__)


class TileManager:
    """Manages operations related to Landsat tiles."""
    
    @staticmethod
    def get_tile_by_id(tile_id: str) -> Optional[LandsatTile]:
        """Get a specific tile by its ID."""
        with get_db() as session:
            return session.query(LandsatTile).filter(LandsatTile.tile_id == tile_id).first()
    
    @staticmethod
    def get_all_tiles(active_only: bool = True) -> List[LandsatTile]:
        """Get all tiles, optionally filtering to active tiles only."""
        with get_db() as session:
            query = session.query(LandsatTile)
            if active_only:
                query = query.filter(LandsatTile.is_active == True)
            return query.order_by(LandsatTile.path, LandsatTile.row).all()
    
    @staticmethod
    def get_tiles_by_status(status: str, active_only: bool = True) -> List[LandsatTile]:
        """Get tiles filtered by processing status."""
        with get_db() as session:
            query = session.query(LandsatTile).filter(LandsatTile.status == status)
            if active_only:
                query = query.filter(LandsatTile.is_active == True)
            return query.order_by(LandsatTile.processing_priority.desc()).all()
    
    @staticmethod
    def get_tiles_needing_processing(hours_since_last: int = 24) -> List[LandsatTile]:
        """
        Get tiles that need processing based on time since last processing.
        
        Args:
            hours_since_last: Number of hours since last processing to consider for reprocessing
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_since_last)
        
        with get_db() as session:
            return session.query(LandsatTile).filter(
                and_(
                    LandsatTile.is_active == True,
                    or_(
                        LandsatTile.last_processed.is_(None),
                        LandsatTile.last_processed < cutoff_time
                    ),
                    LandsatTile.status.in_([
                        ProcessingStatus.PENDING.value,
                        ProcessingStatus.COMPLETED.value,
                        ProcessingStatus.FAILED.value
                    ])
                )
            ).order_by(LandsatTile.processing_priority.desc()).all()
    
    @staticmethod
    def update_tile_status(tile_id: str, status: str, notes: str = None) -> bool:
        """Update the status of a tile."""
        try:
            with get_db() as session:
                tile = session.query(LandsatTile).filter(LandsatTile.tile_id == tile_id).first()
                if tile:
                    tile.status = status
                    if notes:
                        tile.processing_notes = notes
                    if status == ProcessingStatus.COMPLETED.value:
                        tile.last_processed = datetime.utcnow()
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to update tile status: {e}")
            return False
    
    @staticmethod
    def create_tile(tile_id: str, path: int, row: int, center_lat: float, 
                   center_lon: float, bounds_geojson: str = None, geometry=None, area_km2: float = None) -> LandsatTile:
        """Create a new Landsat tile record."""
        try:
            with get_db() as session:
                # Convert geometry to GeoJSON if provided
                if geometry and bounds_geojson is None:
                    import json
                    bounds_geojson = json.dumps(geometry.__geo_interface__)
                
                tile = LandsatTile(
                    tile_id=tile_id,
                    path=path,
                    row=row,
                    center_lat=center_lat,
                    center_lon=center_lon,
                    bounds_geojson=bounds_geojson
                )
                session.add(tile)
                session.commit()
                session.refresh(tile)
                return tile
        except Exception as e:
            logger.error(f"Failed to create tile: {e}")
            raise
    
    @staticmethod
    def update_tile_geometry(tile_id: str, geometry, center_lat: float, center_lon: float, area_km2: float = None) -> bool:
        """Update tile geometry and location data from shapefile."""
        try:
            with get_db() as session:
                tile = session.query(LandsatTile).filter(LandsatTile.tile_id == tile_id).first()
                if tile:
                    # Convert geometry to GeoJSON
                    import json
                    tile.bounds_geojson = json.dumps(geometry.__geo_interface__)
                    tile.center_lat = center_lat
                    tile.center_lon = center_lon
                    
                    # Store area if provided (could add area_km2 field to model later)
                    if area_km2:
                        # For now, store in processing_notes as additional info
                        tile.processing_notes = f"Area: {area_km2:.2f} km²"
                    
                    session.commit()
                    logger.info(f"Updated geometry for tile {tile_id}")
                    return True
                else:
                    logger.warning(f"Tile {tile_id} not found for geometry update")
                    return False
        except Exception as e:
            logger.error(f"Failed to update tile geometry: {e}")
            return False
    
    @staticmethod
    def get_tile(tile_id: str) -> Optional[LandsatTile]:
        """Get a tile by ID (alias for get_tile_by_id for consistency)."""
        return TileManager.get_tile_by_id(tile_id)


class JobManager:
    """Manages processing job operations."""
    
    @staticmethod
    def create_job(tile_id: str, time_start: datetime, time_end: datetime) -> ProcessingJob:
        """Create a new processing job."""
        try:
            job_id = f"job_{tile_id}_{int(datetime.utcnow().timestamp())}"
            
            with get_db() as session:
                job = ProcessingJob(
                    job_id=job_id,
                    tile_id=tile_id,
                    time_start=time_start,
                    time_end=time_end
                )
                session.add(job)
                session.commit()
                session.refresh(job)
                return job
        except Exception as e:
            logger.error(f"Failed to create job: {e}")
            raise
    
    @staticmethod
    def get_job_by_id(job_id: str) -> Optional[ProcessingJob]:
        """Get a specific job by its ID."""
        with get_db() as session:
            return session.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
    
    @staticmethod
    def get_active_jobs() -> List[ProcessingJob]:
        """Get all currently active (processing) jobs."""
        with get_db() as session:
            return session.query(ProcessingJob).filter(
                ProcessingJob.status == ProcessingStatus.PROCESSING.value
            ).all()
    
    @staticmethod
    def get_jobs_by_tile(tile_id: str, limit: int = 10) -> List[ProcessingJob]:
        """Get recent jobs for a specific tile."""
        with get_db() as session:
            return session.query(ProcessingJob).filter(
                ProcessingJob.tile_id == tile_id
            ).order_by(desc(ProcessingJob.created_at)).limit(limit).all()
    
    @staticmethod
    def update_job_status(job_id: str, status: str, progress: int = None, 
                         error_message: str = None) -> bool:
        """Update job status and progress."""
        try:
            with get_db() as session:
                job = session.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
                if job:
                    job.status = status
                    if progress is not None:
                        job.progress_percent = progress
                    if error_message:
                        job.error_message = error_message
                    
                    if status == ProcessingStatus.PROCESSING.value and not job.started_at:
                        job.started_at = datetime.utcnow()
                    elif status in [ProcessingStatus.COMPLETED.value, ProcessingStatus.FAILED.value]:
                        job.completed_at = datetime.utcnow()
                        if job.started_at:
                            job.processing_time_seconds = (job.completed_at - job.started_at).total_seconds()
                    
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to update job status: {e}")
            return False
    
    @staticmethod
    def get_failed_jobs(hours_back: int = 24) -> List[ProcessingJob]:
        """Get jobs that failed in the last N hours."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        
        with get_db() as session:
            return session.query(ProcessingJob).filter(
                and_(
                    ProcessingJob.status == ProcessingStatus.FAILED.value,
                    ProcessingJob.completed_at >= cutoff_time
                )
            ).all()


class AlertManager:
    """Manages detection alert operations."""
    
    @staticmethod
    def create_alert(job_id: str, tile_id: str, detection_lat: float, detection_lon: float,
                    detection_date: datetime, confidence_score: float, area_hectares: float,
                    detection_geojson: str = None, clearing_type: str = None) -> DetectionAlert:
        """Create a new detection alert."""
        try:
            alert_id = f"alert_{tile_id}_{int(detection_date.timestamp())}"
            
            with get_db() as session:
                alert = DetectionAlert(
                    alert_id=alert_id,
                    job_id=job_id,
                    tile_id=tile_id,
                    detection_lat=detection_lat,
                    detection_lon=detection_lon,
                    detection_date=detection_date,
                    confidence_score=confidence_score,
                    area_hectares=area_hectares,
                    detection_geojson=detection_geojson,
                    clearing_type=clearing_type
                )
                session.add(alert)
                session.commit()
                session.refresh(alert)
                return alert
        except Exception as e:
            logger.error(f"Failed to create alert: {e}")
            raise
    
    @staticmethod
    def get_alerts_by_tile(tile_id: str, days_back: int = 30) -> List[DetectionAlert]:
        """Get alerts for a specific tile in the last N days."""
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        with get_db() as session:
            return session.query(DetectionAlert).filter(
                and_(
                    DetectionAlert.tile_id == tile_id,
                    DetectionAlert.detection_date >= cutoff_date
                )
            ).order_by(desc(DetectionAlert.detection_date)).all()
    
    @staticmethod
    def get_recent_alerts(hours_back: int = 24) -> List[DetectionAlert]:
        """Get all alerts from the last N hours."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        
        with get_db() as session:
            return session.query(DetectionAlert).filter(
                DetectionAlert.created_at >= cutoff_time
            ).order_by(desc(DetectionAlert.detection_date)).all()
    
    @staticmethod
    def update_alert_verification(alert_id: str, verification_status: str, 
                                verified_by: str, notes: str = None) -> bool:
        """Update alert verification status."""
        try:
            with get_db() as session:
                alert = session.query(DetectionAlert).filter(
                    DetectionAlert.alert_id == alert_id
                ).first()
                if alert:
                    alert.verification_status = verification_status
                    alert.is_verified = verification_status == "confirmed"
                    alert.verified_by = verified_by
                    alert.verified_at = datetime.utcnow()
                    if notes:
                        alert.verification_notes = notes
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to update alert verification: {e}")
            return False


class SystemStatusManager:
    """Manages system status and statistics."""
    
    @staticmethod
    def get_system_stats() -> Dict:
        """Get current system statistics."""
        with get_db() as session:
            # Count tiles by status
            tile_stats = session.query(
                LandsatTile.status,
                func.count(LandsatTile.id).label('count')
            ).filter(LandsatTile.is_active == True).group_by(LandsatTile.status).all()
            
            # Count active jobs
            active_jobs = session.query(ProcessingJob).filter(
                ProcessingJob.status == ProcessingStatus.PROCESSING.value
            ).count()
            
            # Count recent alerts
            today = datetime.utcnow().date()
            alerts_today = session.query(DetectionAlert).filter(
                func.date(DetectionAlert.created_at) == today
            ).count()
            
            # Count jobs processed today
            jobs_today = session.query(ProcessingJob).filter(
                func.date(ProcessingJob.created_at) == today
            ).count()
            
            return {
                'tile_stats': {stat.status: stat.count for stat in tile_stats},
                'active_jobs': active_jobs,
                'alerts_today': alerts_today,
                'jobs_today': jobs_today,
                'last_updated': datetime.utcnow()
            }
    
    @staticmethod
    def update_system_status(status: str = "healthy"):
        """Update the overall system status."""
        try:
            with get_db() as session:
                system_status = session.query(SystemStatus).first()
                if not system_status:
                    system_status = SystemStatus()
                    session.add(system_status)
                
                system_status.system_status = status
                system_status.last_health_check = datetime.utcnow()
                
                # Update statistics
                stats = SystemStatusManager.get_system_stats()
                system_status.active_jobs = stats['active_jobs']
                system_status.total_alerts_today = stats['alerts_today']
                system_status.processed_tiles_today = stats['jobs_today']
                
                session.commit()
        except Exception as e:
            logger.error(f"Failed to update system status: {e}")
            raise
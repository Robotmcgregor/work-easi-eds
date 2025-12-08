"""
Database models for the EDS (Early Detection System) application.
"""

from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from datetime import datetime
import enum

Base = declarative_base()


class ProcessingStatus(enum.Enum):
    """Status enum for tile processing"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class LandsatTile(Base):
    """
    Model for tracking Landsat tiles across Australia.
    Each tile represents a geographic area that can be processed by the EDS system.
    """

    __tablename__ = "landsat_tiles"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Tile identification
    tile_id = Column(
        String(20), unique=True, nullable=False, index=True
    )  # e.g., "090084", "091084"
    path = Column(Integer, nullable=False, index=True)  # Landsat path
    row = Column(Integer, nullable=False, index=True)  # Landsat row

    # Geographic information
    center_lat = Column(Float, nullable=False)
    center_lon = Column(Float, nullable=False)
    bounds_geojson = Column(Text)  # GeoJSON polygon of tile boundaries

    # Processing status and timing
    status = Column(
        String(20), nullable=False, default=ProcessingStatus.PENDING.value, index=True
    )
    last_processed = Column(DateTime, nullable=True, index=True)
    last_updated = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )
    created_at = Column(DateTime, nullable=False, default=func.now())

    # Processing metadata
    processing_priority = Column(Integer, default=5)  # 1-10, higher = more priority
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    processing_notes = Column(Text)

    # Data availability
    latest_landsat_date = Column(DateTime, nullable=True)
    data_quality_score = Column(Float, nullable=True)  # 0-1 quality assessment

    # Create composite indexes for common queries
    __table_args__ = (
        Index("idx_path_row", "path", "row"),
        Index("idx_status_priority", "status", "processing_priority"),
        Index("idx_active_status", "is_active", "status"),
    )


class ProcessingJob(Base):
    """
    Model for tracking individual processing jobs.
    Each job represents a single execution of the EDS algorithm on one or more tiles.
    """

    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Job identification
    job_id = Column(String(50), unique=True, nullable=False, index=True)
    tile_id = Column(String(20), nullable=False, index=True)  # Foreign key to tile_id

    # Job timing
    created_at = Column(DateTime, nullable=False, default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Job parameters
    time_start = Column(DateTime, nullable=False)  # Start of time range to process
    time_end = Column(DateTime, nullable=False)  # End of time range to process

    # Job status and results
    status = Column(
        String(20), nullable=False, default=ProcessingStatus.PENDING.value, index=True
    )
    progress_percent = Column(Integer, default=0)

    # Results and metadata
    alerts_detected = Column(Integer, default=0)
    area_processed_ha = Column(Float, nullable=True)
    processing_time_seconds = Column(Float, nullable=True)

    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

    # File paths and outputs
    output_path = Column(String(500), nullable=True)
    log_path = Column(String(500), nullable=True)

    # Create indexes for common queries
    __table_args__ = (
        Index("idx_tile_status", "tile_id", "status"),
        Index("idx_created_status", "created_at", "status"),
        Index("idx_time_range", "time_start", "time_end"),
    )


class DetectionAlert(Base):
    """
    Model for storing land clearing detection alerts.
    Each alert represents a potential land clearing event detected by the EDS system.
    """

    __tablename__ = "detection_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Alert identification
    alert_id = Column(String(50), unique=True, nullable=False, index=True)
    job_id = Column(
        String(50), nullable=False, index=True
    )  # Foreign key to processing_jobs
    tile_id = Column(
        String(20), nullable=False, index=True
    )  # Foreign key to landsat_tiles

    # Geographic information
    detection_lat = Column(Float, nullable=False, index=True)
    detection_lon = Column(Float, nullable=False, index=True)
    detection_geojson = Column(Text)  # GeoJSON of detected clearing area

    # Detection details
    detection_date = Column(DateTime, nullable=False, index=True)
    confidence_score = Column(Float, nullable=False)  # 0-1 confidence level
    area_hectares = Column(Float, nullable=False)

    # Classification
    clearing_type = Column(
        String(50), nullable=True
    )  # e.g., "forest", "vegetation", "unknown"
    severity = Column(String(20), nullable=True)  # e.g., "low", "medium", "high"

    # Verification status
    is_verified = Column(Boolean, default=False, nullable=False)
    verification_status = Column(
        String(20), default="pending"
    )  # pending, confirmed, false_positive
    verified_by = Column(String(100), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verification_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    # Create spatial and temporal indexes
    __table_args__ = (
        Index("idx_location", "detection_lat", "detection_lon"),
        Index("idx_date_confidence", "detection_date", "confidence_score"),
        Index("idx_tile_date", "tile_id", "detection_date"),
        Index("idx_verification", "is_verified", "verification_status"),
    )


class SystemStatus(Base):
    """
    Model for tracking overall system status and statistics.
    """

    __tablename__ = "system_status"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Status tracking
    last_full_run = Column(DateTime, nullable=True)
    active_jobs = Column(Integer, default=0)
    failed_jobs_last_24h = Column(Integer, default=0)

    # Statistics
    total_tiles = Column(Integer, default=0)
    processed_tiles_today = Column(Integer, default=0)
    total_alerts_today = Column(Integer, default=0)

    # System health
    system_status = Column(String(20), default="healthy")  # healthy, warning, error
    last_health_check = Column(DateTime, nullable=False, default=func.now())

    # Performance metrics
    avg_processing_time = Column(Float, nullable=True)  # seconds per tile
    queue_length = Column(Integer, default=0)

    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

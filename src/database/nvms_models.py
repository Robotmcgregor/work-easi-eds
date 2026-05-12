"""
Database models for EDS pilot results and processing runs.
Extends the existing EDS models to track historical processing results.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    Boolean,
    ForeignKey,
    Float,
    JSON,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from .models import Base

# For geospatial storage and JSON properties
from geoalchemy2 import Geometry


class EDSRun(Base):
    """Represents an EDS processing run (Run01, Run02, Run03)."""

    __tablename__ = "eds_runs"

    run_id = Column(String(20), primary_key=True)  # e.g., 'EDS_QLD_Run01'
    run_number = Column(Integer, nullable=False)  # 1, 2, 3
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to results
    results = relationship("EDSResult", back_populates="run")


class EDSResult(Base):
    """Represents the results of processing a specific tile in an EDS run."""

    __tablename__ = "eds_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(20), ForeignKey("eds_runs.run_id"), nullable=False)
    tile_id = Column(String(10), ForeignKey("landsat_tiles.tile_id"), nullable=False)

    # Processing metadata
    visual_check = Column(String(50))  # 'complete', etc.
    analyst = Column(String(10))  # 'RB', 'GS', 'KM', 'RM'
    comments = Column(Text)
    shp_path = Column(Text)

    # Results
    cleared = Column(Integer)  # Number of cleared detections
    not_cleared = Column(Integer)  # Number of not cleared detections
    supplied_to_ceb = Column(String(10))  # 'y', 'n', or empty

    # Time period processed
    start_date = Column(String(8))  # Original format: '20230304'
    end_date = Column(String(8))  # Original format: '20231022'
    start_date_dt = Column(DateTime)  # Parsed datetime
    end_date_dt = Column(DateTime)  # Parsed datetime

    # Tile coordinates (for verification)
    path = Column(Integer, nullable=False)
    row = Column(Integer, nullable=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    run = relationship("EDSRun", back_populates="results")
    tile = relationship("LandsatTile")
    # Link to spatial detections (shapefile geometries)
    detections = relationship("EDSDetection", back_populates="result")


class ProcessingHistory(Base):
    """
    Tracks the complete processing history for each tile.
    Links EDS processing jobs with EDS historical results.
    """

    __tablename__ = "processing_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tile_id = Column(String(10), ForeignKey("landsat_tiles.tile_id"), nullable=False)

    # Processing details
    processing_type = Column(
        String(20), nullable=False
    )  # 'EDS_PILOT', 'EDS_LIVE', 'EDS_BATCH'
    processing_run = Column(String(50))  # 'EDS_QLD_Run01', job_id, etc.

    # Time information
    time_start = Column(DateTime, nullable=False)
    time_end = Column(DateTime, nullable=False)
    processed_at = Column(DateTime, default=datetime.utcnow)

    # Results summary
    detections_total = Column(Integer, default=0)
    detections_cleared = Column(Integer, default=0)
    detections_not_cleared = Column(Integer, default=0)

    # Processing metadata
    analyst = Column(String(10))
    status = Column(String(20), default="completed")
    notes = Column(Text)
    confidence_threshold = Column(Float)

    # Relationships
    tile = relationship("LandsatTile")


class EDSDetection(Base):
    """Stores individual detection geometries imported from EDS shapefiles.

    Each record links to the EDS run and the tile that contains the detection.
    Geometry is stored using PostGIS via GeoAlchemy2.
    Properties stores original shapefile attributes as JSON.
    """

    __tablename__ = "eds_detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(20), ForeignKey("eds_runs.run_id"), nullable=False)
    result_id = Column(Integer, ForeignKey("eds_results.id"), nullable=True)
    tile_id = Column(String(10), ForeignKey("landsat_tiles.tile_id"), nullable=True)

    # Original shapefile properties
    properties = Column(JSON)

    # Geometry storage as GeoJSON in JSON (fallback when PostGIS is not available)
    # This keeps geometry available for visualization without requiring PostGIS.
    geom_geojson = Column(JSON)
    geom_wkt = Column(Text)

    # Deterministic geometry hash for duplicate prevention.
    # Format: md5(run_id|tile_id|normalized_wkt). Normalized WKT strips repeated spaces.
    # Unique across table so re-import of same geometry for same run/tile is skipped.
    geom_hash = Column(String(64), unique=True, index=True)

    imported_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    run = relationship("EDSRun")
    result = relationship("EDSResult", back_populates="detections")
    tile = relationship("LandsatTile")


# Backwards compatibility aliases for old NVMS naming
NVMSRun = EDSRun
NVMSResult = EDSResult
NVMSDetection = EDSDetection

"""
Quality Control models for EDS validation workflow
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from datetime import datetime
import enum

from .models import Base


class QCStatus(enum.Enum):
    """Quality Control status enum"""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    REQUIRES_REVIEW = "requires_review"


class QCValidation(Base):
    """
    Quality Control validation records for land clearing detections.
    Tracks staff review and validation of automated clearing detections.
    """

    __tablename__ = "qc_validations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Link to original detection
    nvms_detection_id = Column(
        Integer, ForeignKey("nvms_detections.id"), nullable=False, index=True
    )
    tile_id = Column(String(20), nullable=False, index=True)

    # QC Details
    qc_status = Column(
        String(20), nullable=False, default=QCStatus.PENDING.value, index=True
    )
    reviewed_by = Column(String(100), nullable=True)  # Staff member name/ID
    reviewed_at = Column(DateTime, nullable=True)

    # Validation results
    is_confirmed_clearing = Column(
        Boolean, nullable=True
    )  # True=confirmed, False=rejected, None=pending
    confidence_score = Column(Integer, nullable=True)  # 1-5 confidence rating

    # Comments and notes
    reviewer_comments = Column(Text, nullable=True)
    validation_notes = Column(Text, nullable=True)

    # Follow-up actions
    requires_field_visit = Column(Boolean, default=False)
    priority_level = Column(String(20), default="normal")  # low, normal, high, urgent

    # Metadata
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(
        DateTime, nullable=False, default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<QCValidation(id={self.id}, tile={self.tile_id}, status={self.qc_status})>"


class QCAuditLog(Base):
    """
    Audit log for QC validation changes.
    Tracks all changes made during the validation process.
    """

    __tablename__ = "qc_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Reference
    qc_validation_id = Column(
        Integer, ForeignKey("qc_validations.id"), nullable=False, index=True
    )

    # Change details
    action = Column(
        String(50), nullable=False
    )  # created, status_changed, comments_added, etc.
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    # Who and when
    changed_by = Column(String(100), nullable=False)
    changed_at = Column(DateTime, nullable=False, default=func.now())

    # Context
    change_reason = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)

    def __repr__(self):
        return f"<QCAuditLog(id={self.id}, action={self.action}, by={self.changed_by})>"

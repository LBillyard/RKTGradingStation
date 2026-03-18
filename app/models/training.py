"""Training grade and calibration report models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Float, Integer, Text, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class TrainingGrade(Base):
    """Links an expert's manual grade to the AI's grade for training/calibration."""
    __tablename__ = "training_grades"

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"), unique=True)

    # Expert manual grades
    expert_centering: Mapped[float] = mapped_column(Float)
    expert_corners: Mapped[float] = mapped_column(Float)
    expert_edges: Mapped[float] = mapped_column(Float)
    expert_surface: Mapped[float] = mapped_column(Float)
    expert_final: Mapped[float] = mapped_column(Float)
    expert_defect_notes: Mapped[Optional[str]] = mapped_column(Text)

    # AI grades (populated when AI grades the card)
    ai_centering: Mapped[Optional[float]] = mapped_column(Float)
    ai_corners: Mapped[Optional[float]] = mapped_column(Float)
    ai_edges: Mapped[Optional[float]] = mapped_column(Float)
    ai_surface: Mapped[Optional[float]] = mapped_column(Float)
    ai_final: Mapped[Optional[float]] = mapped_column(Float)
    ai_raw_score: Mapped[Optional[float]] = mapped_column(Float)

    # Computed deltas (AI - Expert)
    delta_centering: Mapped[Optional[float]] = mapped_column(Float)
    delta_corners: Mapped[Optional[float]] = mapped_column(Float)
    delta_edges: Mapped[Optional[float]] = mapped_column(Float)
    delta_surface: Mapped[Optional[float]] = mapped_column(Float)
    delta_final: Mapped[Optional[float]] = mapped_column(Float)

    # Metadata
    sensitivity_profile: Mapped[Optional[str]] = mapped_column(String(30))
    operator_name: Mapped[str] = mapped_column(String(100))
    expertise_level: Mapped[str] = mapped_column(String(20), default="standard")
    created_at: Mapped[created_at_col]


class CalibrationReport(Base):
    """Snapshot of calibration analysis with threshold recommendations."""
    __tablename__ = "calibration_reports"

    id: Mapped[uuid_pk]
    sample_count: Mapped[int] = mapped_column(Integer)
    date_range_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    date_range_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    profile_filter: Mapped[Optional[str]] = mapped_column(String(30))
    franchise_filter: Mapped[Optional[str]] = mapped_column(String(50))

    # Average deltas (AI - Expert)
    avg_delta_centering: Mapped[float] = mapped_column(Float, default=0.0)
    avg_delta_corners: Mapped[float] = mapped_column(Float, default=0.0)
    avg_delta_edges: Mapped[float] = mapped_column(Float, default=0.0)
    avg_delta_surface: Mapped[float] = mapped_column(Float, default=0.0)
    avg_delta_final: Mapped[float] = mapped_column(Float, default=0.0)

    # Standard deviations
    std_delta_centering: Mapped[float] = mapped_column(Float, default=0.0)
    std_delta_corners: Mapped[float] = mapped_column(Float, default=0.0)
    std_delta_edges: Mapped[float] = mapped_column(Float, default=0.0)
    std_delta_surface: Mapped[float] = mapped_column(Float, default=0.0)
    std_delta_final: Mapped[float] = mapped_column(Float, default=0.0)

    # Recommendations
    recommendations_json: Mapped[Optional[dict]] = mapped_column(JSON)
    match_rate: Mapped[Optional[float]] = mapped_column(Float)  # % where AI == expert within 0.5

    # Application status
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_by: Mapped[Optional[str]] = mapped_column(String(100))
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at_col]

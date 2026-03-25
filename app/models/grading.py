"""Grading models: defect findings, grade decisions, and grade history."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, JSON, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class DefectFinding(Base):
    """A single defect detected during grading analysis."""
    __tablename__ = "defect_findings"
    __table_args__ = (
        Index("idx_defect_findings_card_id", "card_record_id"),
        Index("idx_defect_findings_category", "category"),
    )

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"))
    category: Mapped[str] = mapped_column(String(30))  # centering, corner, edge, surface
    defect_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))  # minor, moderate, major, critical
    location_description: Mapped[Optional[str]] = mapped_column(String(200))
    side: Mapped[str] = mapped_column(String(10), default="front")
    bbox_x: Mapped[Optional[int]] = mapped_column(Integer)
    bbox_y: Mapped[Optional[int]] = mapped_column(Integer)
    bbox_w: Mapped[Optional[int]] = mapped_column(Integer)
    bbox_h: Mapped[Optional[int]] = mapped_column(Integer)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    score_impact: Mapped[Optional[float]] = mapped_column(Float)
    is_noise: Mapped[bool] = mapped_column(Boolean, default=False)
    debug_image_path: Mapped[Optional[str]] = mapped_column(String(500))
    details_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[created_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="defect_findings")


class GradeDecision(Base):
    """Final grade decision for a card."""
    __tablename__ = "grade_decisions"
    __table_args__ = (
        Index("idx_grade_decisions_card_id", "card_record_id"),
        Index("idx_grade_decisions_status", "status"),
    )

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"), unique=True)
    centering_score: Mapped[Optional[float]] = mapped_column(Float)
    corners_score: Mapped[Optional[float]] = mapped_column(Float)
    edges_score: Mapped[Optional[float]] = mapped_column(Float)
    surface_score: Mapped[Optional[float]] = mapped_column(Float)
    raw_grade: Mapped[Optional[float]] = mapped_column(Float)
    final_grade: Mapped[Optional[float]] = mapped_column(Float)
    centering_ratio_lr: Mapped[Optional[str]] = mapped_column(String(20))
    centering_ratio_tb: Mapped[Optional[str]] = mapped_column(String(20))
    grade_caps_json: Mapped[Optional[dict]] = mapped_column(JSON)
    sensitivity_profile: Mapped[str] = mapped_column(String(30), default="standard")
    auto_grade: Mapped[Optional[float]] = mapped_column(Float)
    operator_override_grade: Mapped[Optional[float]] = mapped_column(Float)
    override_reason: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    graded_by: Mapped[Optional[str]] = mapped_column(String(100))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    defect_count: Mapped[int] = mapped_column(Integer, default=0)
    grading_confidence: Mapped[Optional[float]] = mapped_column(Float)
    ai_review_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="grade_decisions")


class GradeHistory(Base):
    """Historical record of a grading attempt."""
    __tablename__ = "grade_history"
    __table_args__ = (
        Index("idx_grade_history_card_record_id", "card_record_id"),
    )

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"))
    centering_score: Mapped[Optional[float]] = mapped_column(Float)
    corners_score: Mapped[Optional[float]] = mapped_column(Float)
    edges_score: Mapped[Optional[float]] = mapped_column(Float)
    surface_score: Mapped[Optional[float]] = mapped_column(Float)
    raw_grade: Mapped[Optional[float]] = mapped_column(Float)
    final_grade: Mapped[Optional[float]] = mapped_column(Float)
    sensitivity_profile: Mapped[str] = mapped_column(String(30), default="standard")
    defect_count: Mapped[int] = mapped_column(Integer, default=0)
    grade_caps_json: Mapped[Optional[dict]] = mapped_column(JSON)
    graded_at: Mapped[created_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="grade_history")

"""Authenticity check and decision models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, JSON, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, uuid_pk, created_at_col


class AuthenticityCheck(Base):
    """Individual authenticity check result."""
    __tablename__ = "authenticity_checks"
    __table_args__ = (
        Index("idx_authenticity_checks_card_record_id", "card_record_id"),
    )

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"))
    check_type: Mapped[str] = mapped_column(String(50))
    passed: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float)
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    processing_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[created_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="authenticity_checks")


class AuthenticityDecision(Base):
    """Overall authenticity decision for a card."""
    __tablename__ = "authenticity_decisions"

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"), unique=True)
    overall_status: Mapped[str] = mapped_column(String(30))  # authentic, suspect, reject, manual_review
    confidence: Mapped[float] = mapped_column(Float)
    checks_passed: Mapped[int] = mapped_column(Integer, default=0)
    checks_failed: Mapped[int] = mapped_column(Integer, default=0)
    checks_total: Mapped[int] = mapped_column(Integer, default=0)
    flags_json: Mapped[Optional[dict]] = mapped_column(JSON)
    operator_override_status: Mapped[Optional[str]] = mapped_column(String(30))
    override_reason: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="authenticity_decisions")

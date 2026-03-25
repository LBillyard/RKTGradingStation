"""Card record and identity result models."""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class CardRecord(Base):
    """Central record for a graded card, linking all related data."""
    __tablename__ = "card_records"
    __table_args__ = (
        Index("idx_card_records_session_id", "session_id"),
        Index("idx_card_records_card_name", "card_name"),
        Index("idx_card_records_status", "status"),
        Index("idx_card_records_franchise", "franchise"),
    )

    id: Mapped[uuid_pk]
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("scan_sessions.id"))
    front_image_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("card_images.id"))
    back_image_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("card_images.id"))
    pokewallet_card_id: Mapped[Optional[str]] = mapped_column(String(100))
    card_name: Mapped[Optional[str]] = mapped_column(String(200))
    set_name: Mapped[Optional[str]] = mapped_column(String(200))
    set_code: Mapped[Optional[str]] = mapped_column(String(50))
    collector_number: Mapped[Optional[str]] = mapped_column(String(30))
    rarity: Mapped[Optional[str]] = mapped_column(String(50))
    card_type: Mapped[Optional[str]] = mapped_column(String(50))
    hp: Mapped[Optional[str]] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(10), default="en")
    franchise: Mapped[str] = mapped_column(String(50), default="pokemon")
    identification_confidence: Mapped[Optional[float]] = mapped_column(Float)
    identification_method: Mapped[Optional[str]] = mapped_column(String(50))
    serial_number: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    # Child relationships with cascade delete-orphan
    identity_results: Mapped[List["CardIdentityResult"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan"
    )
    grade_decisions: Mapped[List["GradeDecision"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="GradeDecision.card_record_id",
    )
    defect_findings: Mapped[List["DefectFinding"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="DefectFinding.card_record_id",
    )
    grade_history: Mapped[List["GradeHistory"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="GradeHistory.card_record_id",
    )
    authenticity_checks: Mapped[List["AuthenticityCheck"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="AuthenticityCheck.card_record_id",
    )
    authenticity_decisions: Mapped[List["AuthenticityDecision"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="AuthenticityDecision.card_record_id",
    )
    ocr_results: Mapped[List["OCRResult"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="OCRResult.card_record_id",
    )
    print_jobs: Mapped[List["PrintJob"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="PrintJob.card_record_id",
    )
    nfc_tags: Mapped[List["NfcTag"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="NfcTag.card_record_id",
    )
    slab_assemblies: Mapped[List["SlabAssembly"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="SlabAssembly.card_record_id",
    )
    training_grades: Mapped[List["TrainingGrade"]] = relationship(
        back_populates="card_record", cascade="all, delete-orphan",
        foreign_keys="TrainingGrade.card_record_id",
    )


class CardIdentityResult(Base):
    """Detailed result of card identification attempt."""
    __tablename__ = "card_identity_results"
    __table_args__ = (
        Index("idx_card_identity_results_card_record_id", "card_record_id"),
    )

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"))
    search_query: Mapped[Optional[str]] = mapped_column(String(500))
    best_match_id: Mapped[Optional[str]] = mapped_column(String(100))
    best_match_name: Mapped[Optional[str]] = mapped_column(String(200))
    best_match_confidence: Mapped[Optional[float]] = mapped_column(Float)
    alternatives_json: Mapped[Optional[str]] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(50), default="ocr_api")
    requires_manual_review: Mapped[bool] = mapped_column(default=False)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="identity_results")

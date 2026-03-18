"""Card record and identity result models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class CardRecord(Base):
    """Central record for a graded card, linking all related data."""
    __tablename__ = "card_records"

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


class CardIdentityResult(Base):
    """Detailed result of card identification attempt."""
    __tablename__ = "card_identity_results"

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

"""Scan session and card image models."""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Float, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class ScanSession(Base):
    """A scanning session containing front and/or back card images."""
    __tablename__ = "scan_sessions"

    id: Mapped[uuid_pk]
    operator_name: Mapped[Optional[str]] = mapped_column(String(100))
    scanner_device_id: Mapped[Optional[str]] = mapped_column(String(200))
    scan_preset: Mapped[str] = mapped_column(String(50), default="detailed")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[created_at_col]
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[created_at_col]

    images: Mapped[List["CardImage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class CardImage(Base):
    """A single scanned image (front or back) of a card."""
    __tablename__ = "card_images"
    __table_args__ = (
        Index("idx_card_images_session_id", "session_id"),
    )

    id: Mapped[uuid_pk]
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("scan_sessions.id"))
    side: Mapped[str] = mapped_column(String(10))  # "front" or "back"
    raw_path: Mapped[str] = mapped_column(String(500))
    processed_path: Mapped[Optional[str]] = mapped_column(String(500))
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500))
    dpi: Mapped[int] = mapped_column(Integer, default=600)
    width_px: Mapped[Optional[int]] = mapped_column(Integer)
    height_px: Mapped[Optional[int]] = mapped_column(Integer)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    linked_pair_id: Mapped[Optional[str]] = mapped_column(String(36))
    processing_status: Mapped[str] = mapped_column(String(20), default="raw")
    created_at: Mapped[created_at_col]

    session: Mapped["ScanSession"] = relationship(back_populates="images")

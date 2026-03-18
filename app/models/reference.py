"""Reference library models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col


class ReferenceCard(Base):
    """Approved reference card for comparison."""
    __tablename__ = "reference_cards"

    id: Mapped[uuid_pk]
    pokewallet_card_id: Mapped[Optional[str]] = mapped_column(String(100))
    card_name: Mapped[str] = mapped_column(String(200))
    set_name: Mapped[Optional[str]] = mapped_column(String(200))
    set_code: Mapped[Optional[str]] = mapped_column(String(50))
    collector_number: Mapped[Optional[str]] = mapped_column(String(30))
    rarity: Mapped[Optional[str]] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(10), default="en")
    franchise: Mapped[str] = mapped_column(String(50), default="pokemon")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(100))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at_col]


class ReferenceImage(Base):
    """Reference image for a card (front or back)."""
    __tablename__ = "reference_images"

    id: Mapped[uuid_pk]
    reference_card_id: Mapped[str] = mapped_column(String(36), ForeignKey("reference_cards.id"))
    side: Mapped[str] = mapped_column(String(10))
    image_path: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20))  # "scan" or "pokewallet"
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    width_px: Mapped[Optional[int]] = mapped_column(default=None)
    height_px: Mapped[Optional[int]] = mapped_column(default=None)
    created_at: Mapped[created_at_col]

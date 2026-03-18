"""Security template and pattern models."""

from typing import Optional

from sqlalchemy import String, Float, Text, ForeignKey, JSON, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class SecurityTemplate(Base):
    """Template defining which security patterns to apply."""
    __tablename__ = "security_templates"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    pattern_types: Mapped[dict] = mapped_column(JSON)  # {"microtext": true, "dots": true, ...}
    microtext_content: Mapped[Optional[str]] = mapped_column(String(500))
    microtext_height_mm: Mapped[float] = mapped_column(Float, default=0.4)
    dot_count: Mapped[int] = mapped_column(Integer, default=64)
    dot_radius_mm: Mapped[float] = mapped_column(Float, default=0.1)
    qr_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    witness_marks_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]


class SecurityPattern(Base):
    """Generated security pattern."""
    __tablename__ = "security_patterns"

    id: Mapped[uuid_pk]
    engraving_job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    pattern_type: Mapped[str] = mapped_column(String(50))
    svg_data: Mapped[Optional[str]] = mapped_column(Text)
    verification_hash: Mapped[Optional[str]] = mapped_column(String(128))
    seed_value: Mapped[Optional[str]] = mapped_column(String(200))
    position_x_mm: Mapped[Optional[float]] = mapped_column(Float)
    position_y_mm: Mapped[Optional[float]] = mapped_column(Float)
    width_mm: Mapped[Optional[float]] = mapped_column(Float)
    height_mm: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[created_at_col]

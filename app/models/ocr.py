"""OCR result models."""

from typing import Optional

from sqlalchemy import String, Integer, Float, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base, uuid_pk, created_at_col


class OCRResult(Base):
    """Result of OCR processing on a card image."""
    __tablename__ = "ocr_results"

    id: Mapped[uuid_pk]
    card_image_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_images.id"))
    card_record_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("card_records.id"))
    engine_used: Mapped[str] = mapped_column(String(20))  # "paddleocr" or "tesseract"
    language_detected: Mapped[Optional[str]] = mapped_column(String(10))
    language_confidence: Mapped[Optional[float]] = mapped_column(Float)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    parsed_fields: Mapped[Optional[dict]] = mapped_column(JSON)
    bboxes_json: Mapped[Optional[str]] = mapped_column(Text)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    processing_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[created_at_col]

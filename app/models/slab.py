"""Slab assembly, print job, and NFC tag models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Float, Integer, Text, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base, uuid_pk, created_at_col, updated_at_col


class PrintJob(Base):
    """Tracks a label print operation for a slab insert."""
    __tablename__ = "print_jobs"
    __table_args__ = (
        Index("idx_print_jobs_card_record_id", "card_record_id"),
    )

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"))
    serial_number: Mapped[str] = mapped_column(String(50))
    template_name: Mapped[Optional[str]] = mapped_column(String(100))
    label_width_mm: Mapped[float] = mapped_column(Float)
    label_height_mm: Mapped[float] = mapped_column(Float)
    dpi: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[Optional[str]] = mapped_column(String(500))
    printer_name: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    printed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="print_jobs")


class NfcTag(Base):
    """Tracks a programmed NFC tag embedded in a slab."""
    __tablename__ = "nfc_tags"
    __table_args__ = (
        Index("idx_nfc_tags_card_record_id", "card_record_id"),
    )

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"))
    serial_number: Mapped[str] = mapped_column(String(50))
    tag_type: Mapped[str] = mapped_column(String(20))  # "ntag213" or "ntag424_dna"
    tag_uid: Mapped[Optional[str]] = mapped_column(String(32))
    ndef_url: Mapped[Optional[str]] = mapped_column(Text)
    sdm_configured: Mapped[bool] = mapped_column(Boolean, default=False)
    key_version: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    programmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="nfc_tags")


class SlabAssembly(Base):
    """Tracks the full slab assembly workflow for one graded card."""
    __tablename__ = "slab_assemblies"

    id: Mapped[uuid_pk]
    card_record_id: Mapped[str] = mapped_column(String(36), ForeignKey("card_records.id"), unique=True)
    serial_number: Mapped[str] = mapped_column(String(50))
    grade: Mapped[Optional[float]] = mapped_column(Float)
    print_job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("print_jobs.id"))
    nfc_213_tag_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("nfc_tags.id"))
    nfc_424_tag_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("nfc_tags.id"))
    workflow_status: Mapped[str] = mapped_column(String(30), default="graded")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_at_col]
    updated_at: Mapped[updated_at_col]

    card_record: Mapped["CardRecord"] = relationship(back_populates="slab_assemblies")
